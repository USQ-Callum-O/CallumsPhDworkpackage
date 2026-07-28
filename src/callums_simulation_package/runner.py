"""One fail-fast orchestrator for every simulation family."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
from typing import Any, Iterable, Mapping

from .artifacts import RunArtifacts
from .config import ConfigError, STAGES, SimulationConfig, load_config, validate_inputs


@dataclass(frozen=True)
class RunPlan:
    config: SimulationConfig
    artifacts: RunArtifacts
    stages: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "config": str(self.config.source),
            "simulation_id": self.config.simulation_id,
            "category": self.config.category,
            "run_name": self.config.run_name,
            "geometry": str(self.config.geometry),
            "inputs": {name: str(path) for name, path in self.config.inputs.items()},
            "stages": list(self.stages),
            "artifacts": self.artifacts.as_dict(),
        }


def _config(value: SimulationConfig | str | Path) -> SimulationConfig:
    return value if isinstance(value, SimulationConfig) else load_config(value)


def _select_stages(config: SimulationConfig, stages: Iterable[str] | None) -> tuple[str, ...]:
    selected = tuple(stages) if stages is not None else config.stages
    if not selected:
        raise ConfigError("at least one stage must be selected")
    unknown = [stage for stage in selected if stage not in config.stages]
    if unknown:
        raise ConfigError(f"selected stages are not enabled by the config: {unknown}")
    positions = [STAGES.index(stage) for stage in selected]
    if positions != sorted(positions) or len(set(selected)) != len(selected):
        raise ConfigError(f"selected stages must be unique and ordered as {list(STAGES)}")
    return selected


def plan(
    config: SimulationConfig | str | Path,
    stages: Iterable[str] | None = None,
) -> RunPlan:
    loaded = _config(config)
    return RunPlan(loaded, RunArtifacts.from_config(loaded), _select_stages(loaded, stages))


def _require_files(paths: Iterable[Path], description: str) -> None:
    missing = [path for path in paths if not path.is_file()]
    if missing:
        formatted = ", ".join(str(path) for path in missing)
        raise ConfigError(f"{description} does not exist: {formatted}")


def validate_plan_inputs(run_plan: RunPlan) -> None:
    """Validate platform inputs and artifacts needed before the first selected stage."""

    validate_inputs(run_plan.config, stages=run_plan.stages)
    selected = set(run_plan.stages)
    solver_input = str(run_plan.config.solver.get("input", "mesh"))

    if "solve" in selected:
        _require_files(run_plan.config.inputs.values(), "Auxiliary solver input")
        if solver_input == "mesh" and "mesh" not in selected:
            _require_files([run_plan.artifacts.mesh], "Mesh input")
        elif solver_input == "case_data":
            _require_files(
                [run_plan.artifacts.case, run_plan.artifacts.data],
                "Solver case/data input",
            )
        elif solver_input not in {"mesh", "case_data"}:
            raise ConfigError("solver.input must be 'mesh' or 'case_data'")

    if "export" in selected and "solve" not in selected:
        _require_files(
            [run_plan.artifacts.case, run_plan.artifacts.data],
            "Export case/data input",
        )

    if "plot" in selected and "export" not in selected:
        plot_specs = [
            *run_plan.config.plotting.get("line_plots", []),
            *run_plan.config.plotting.get("contour_plots", []),
        ]
        if not all(isinstance(spec, Mapping) for spec in plot_specs):
            raise ConfigError("plotting entries must be JSON objects")
        sources = [
            run_plan.artifacts.data_export / str(spec.get("source", "")) for spec in plot_specs
        ]
        _require_files(sources, "Plot input")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_json(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _manifest(run_plan: RunPlan) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "simulation_id": run_plan.config.simulation_id,
        "run_name": run_plan.config.run_name,
        "category": run_plan.config.category,
        "config": str(run_plan.config.source),
        "config_sha256": _sha256_json(run_plan.config.raw),
        "geometry": str(run_plan.config.geometry),
        "geometry_sha256": None,
        "created_at": _utc_now(),
        "completed_at": None,
        "status": "running",
        "host": platform.node(),
        "platform": platform.platform(),
        "python": sys.version,
        "scheduler": {
            "pbs_job_id": os.environ.get("PBS_JOBID"),
            "slurm_job_id": os.environ.get("SLURM_JOB_ID"),
        },
        "stages": {stage: {"status": "pending"} for stage in run_plan.config.stages},
        "artifacts": run_plan.artifacts.as_dict(),
        "executions": [],
    }


def _merge_prior_manifest(run_plan: RunPlan, current: dict[str, Any]) -> dict[str, Any]:
    path = run_plan.artifacts.manifest
    if not path.is_file():
        return current
    try:
        previous = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"Existing run manifest is unreadable: {path}") from exc
    if not isinstance(previous, Mapping):
        raise ConfigError(f"Existing run manifest is not a JSON object: {path}")
    if previous.get("run_name") != current["run_name"]:
        raise ConfigError(f"Existing run manifest belongs to another run: {path}")
    if previous.get("config_sha256") != current["config_sha256"]:
        raise ConfigError(
            "The config changed without a run-version change. Increment a simulation version "
            f"before reusing {run_plan.artifacts.run_root}"
        )

    current["created_at"] = previous.get("created_at", current["created_at"])
    current["geometry_sha256"] = previous.get("geometry_sha256") or current["geometry_sha256"]
    previous_stages = previous.get("stages", {})
    if isinstance(previous_stages, Mapping):
        for stage in current["stages"]:
            prior_state = previous_stages.get(stage)
            if isinstance(prior_state, Mapping):
                current["stages"][stage] = dict(prior_state)
    previous_executions = previous.get("executions", [])
    if isinstance(previous_executions, list):
        current["executions"] = previous_executions
    return current


def _write_json(path: Path, data: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _stage_functions() -> dict[str, Any]:
    from .stages import run_export, run_meshing, run_plotting, run_solver

    return {
        "mesh": run_meshing,
        "solve": run_solver,
        "export": run_export,
        "plot": run_plotting,
    }


def run(
    config: SimulationConfig | str | Path,
    stages: Iterable[str] | None = None,
    *,
    launcher: Any = None,
) -> RunPlan:
    """Run selected stages sequentially and record a durable manifest."""

    run_plan = plan(config, stages)
    validate_plan_inputs(run_plan)
    run_plan.artifacts.create_directories()
    manifest = _manifest(run_plan)
    if run_plan.config.geometry.is_file():
        manifest["geometry_sha256"] = _sha256_file(run_plan.config.geometry)
    manifest = _merge_prior_manifest(run_plan, manifest)
    execution = {
        "stages": list(run_plan.stages),
        "started_at": _utc_now(),
        "completed_at": None,
        "status": "running",
        "host": platform.node(),
        "platform": platform.platform(),
        "scheduler": {
            "pbs_job_id": os.environ.get("PBS_JOBID"),
            "slurm_job_id": os.environ.get("SLURM_JOB_ID"),
        },
    }
    manifest["executions"].append(execution)
    _write_json(run_plan.artifacts.manifest, manifest)

    functions = _stage_functions()
    try:
        for stage in run_plan.stages:
            state = manifest["stages"][stage]
            state.pop("error", None)
            state.update(status="running", started_at=_utc_now(), execution=len(manifest["executions"]))
            _write_json(run_plan.artifacts.manifest, manifest)
            functions[stage](run_plan.config, run_plan.artifacts, launcher=launcher)
            state.update(status="completed", completed_at=_utc_now())
            _write_json(run_plan.artifacts.manifest, manifest)
    except Exception as exc:
        state.update(
            status="failed",
            completed_at=_utc_now(),
            error=f"{type(exc).__name__}: {exc}",
        )
        execution.update(status="failed", completed_at=_utc_now())
        manifest.update(status="failed", completed_at=_utc_now())
        _write_json(run_plan.artifacts.manifest, manifest)
        raise

    execution.update(status="completed", completed_at=_utc_now())
    all_completed = all(
        state.get("status") == "completed" for state in manifest["stages"].values()
    )
    manifest.update(
        status="completed" if all_completed else "partial",
        completed_at=_utc_now(),
    )
    _write_json(run_plan.artifacts.manifest, manifest)
    return run_plan
