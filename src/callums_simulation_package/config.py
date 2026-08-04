"""Load and validate portable simulation configuration files."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import platform
import re
from typing import Any, Iterable, Mapping


SCHEMA_VERSION = 1
CATEGORIES = {"nozzle", "hose", "nozzle_environment", "nozzle_impinging"}
STAGES = ("mesh", "solve", "export", "plot")
INPUT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class ConfigError(ValueError):
    """Raised when a simulation configuration is invalid."""


@dataclass(frozen=True)
class FluentLaunchConfig:
    precision: str = "double"
    dimension: int = 3
    processor_count: int | None = None
    product_version: str | None = None
    ui_mode: str = "no_gui"
    start_timeout: int = 600

    def kwargs(self) -> dict[str, Any]:
        values: dict[str, Any] = {
            "precision": self.precision,
            "dimension": self.dimension,
            "ui_mode": self.ui_mode,
            "start_timeout": self.start_timeout,
        }

        if self.processor_count is not None:
            values["processor_count"] = self.processor_count

        if self.product_version:
            values["product_version"] = self.product_version

        if self.additional_arguments:
            values["additional_arguments"] = self.additional_arguments

        return values


@dataclass(frozen=True)
class SimulationConfig:
    source: Path
    raw: Mapping[str, Any]
    simulation_id: str
    category: str
    run_name: str
    geometry: Path
    geometry_root: Path
    inputs: Mapping[str, Path]
    results_root: Path
    stages: tuple[str, ...]
    launch: FluentLaunchConfig
    meshing: Mapping[str, Any]
    solver: Mapping[str, Any]
    export: Mapping[str, Any]
    plotting: Mapping[str, Any]

    def stage_config(self, stage: str) -> Mapping[str, Any]:
        return {
            "mesh": self.meshing,
            "solve": self.solver,
            "export": self.export,
            "plot": self.plotting,
        }[stage]


def _mapping(value: Any, location: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ConfigError(f"{location} must be a JSON object")
    return value


def _resolve_root(raw: Any, config_dir: Path, environment_name: str) -> Path:
    override = os.environ.get(environment_name)
    value = override if override else raw
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"paths value for {environment_name} must be a non-empty string")
    expanded = Path(os.path.expandvars(os.path.expanduser(value)))
    if not expanded.is_absolute():
        expanded = config_dir / expanded
    return expanded.resolve()


def _versioned_run_name(simulation: Mapping[str, Any]) -> str:
    explicit = simulation.get("run_name")
    if explicit:
        return str(explicit)
    versions = _mapping(simulation.get("versions", {}), "simulation.versions")
    required = ("mesh", "solver", "post")
    missing = [key for key in required if not versions.get(key)]
    if missing:
        raise ConfigError(
            "simulation.run_name or all simulation.versions (mesh, solver, post) are required"
        )
    return "-".join([str(simulation["id"]), *(str(versions[key]) for key in required)])


def _launch_config(raw: Any) -> FluentLaunchConfig:
    values = _mapping(raw or {}, "fluent")
    processor_count = values.get("processor_count")
    if processor_count is not None and (
        not isinstance(processor_count, int)
        or isinstance(processor_count, bool)
        or processor_count < 1
    ):
        raise ConfigError("fluent.processor_count must be null or a positive integer")
    dimension = values.get("dimension", 3)
    if dimension not in (2, 3):
        raise ConfigError("fluent.dimension must be 2 or 3")
    precision = values.get("precision", "double")
    if precision not in ("single", "double"):
        raise ConfigError("fluent.precision must be 'single' or 'double'")
    return FluentLaunchConfig(
        precision=precision,
        dimension=dimension,
        processor_count=processor_count,
        product_version=values.get("product_version"),
        ui_mode=values.get("ui_mode", "no_gui"),
        start_timeout=int(values.get("start_timeout", 600)),
        additional_arguments=values.get("additional_arguments"),
    )


def _resolve_inputs(raw: Any, input_root: Path) -> Mapping[str, Path]:
    values = _mapping(raw or {}, "inputs")
    resolved: dict[str, Path] = {}
    for name, value in values.items():
        if not isinstance(name, str) or not INPUT_NAME.fullmatch(name):
            raise ConfigError("input names must be valid {{placeholder_name}} identifiers")
        if not isinstance(value, str) or not value.strip():
            raise ConfigError(f"inputs.{name} must be a non-empty path string")
        path = Path(os.path.expandvars(os.path.expanduser(value)))
        if not path.is_absolute():
            path = input_root / path
        resolved[name] = path.resolve()
    return resolved


def load_config(path: str | Path) -> SimulationConfig:
    """Load a versioned JSON config and resolve all external paths."""

    source = Path(path).expanduser().resolve()
    try:
        raw = json.loads(source.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise ConfigError(f"Configuration does not exist: {source}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Invalid JSON in {source}: {exc}") from exc
    root = _mapping(raw, "configuration")
    if root.get("schema_version") != SCHEMA_VERSION:
        raise ConfigError(f"schema_version must be {SCHEMA_VERSION}")

    simulation = _mapping(root.get("simulation"), "simulation")
    simulation_id = str(simulation.get("id", ""))
    category = str(simulation.get("category", ""))
    run_name = _versioned_run_name(simulation)
    if not SAFE_NAME.fullmatch(simulation_id):
        raise ConfigError("simulation.id may contain only letters, numbers, '.', '_' and '-'")
    if category not in CATEGORIES:
        raise ConfigError(f"simulation.category must be one of {sorted(CATEGORIES)}")
    if not SAFE_NAME.fullmatch(run_name):
        raise ConfigError("the generated run name is not filesystem-safe")

    paths = _mapping(root.get("paths"), "paths")
    geometry_root = _resolve_root(
        paths.get("geometry_root"), source.parent, "CALLUMS_GEOMETRY_ROOT"
    )
    results_root = _resolve_root(paths.get("results_root"), source.parent, "CALLUMS_RESULTS_ROOT")
    input_root = _resolve_root(
        paths.get("input_root", paths.get("geometry_root")),
        source.parent,
        "CALLUMS_INPUT_ROOT",
    )
    geometry_value = root.get("geometry")
    if not isinstance(geometry_value, str) or not geometry_value:
        raise ConfigError("geometry must be a non-empty path relative to paths.geometry_root")
    geometry = Path(os.path.expandvars(os.path.expanduser(geometry_value)))
    if not geometry.is_absolute():
        geometry = geometry_root / geometry
    geometry = geometry.resolve()

    requested_stages = root.get("stages", list(STAGES))
    if not isinstance(requested_stages, list) or not requested_stages:
        raise ConfigError("stages must be a non-empty JSON array")
    if len(set(requested_stages)) != len(requested_stages):
        raise ConfigError("stages must not contain duplicates")
    unknown_stages = [stage for stage in requested_stages if stage not in STAGES]
    if unknown_stages:
        raise ConfigError(f"unknown stages: {unknown_stages}")
    positions = [STAGES.index(stage) for stage in requested_stages]
    if positions != sorted(positions):
        raise ConfigError(f"stages must follow this order: {list(STAGES)}")

    return SimulationConfig(
        source=source,
        raw=root,
        simulation_id=simulation_id,
        category=category,
        run_name=run_name,
        geometry=geometry,
        geometry_root=geometry_root,
        inputs=_resolve_inputs(root.get("inputs"), input_root),
        results_root=results_root,
        stages=tuple(requested_stages),
        launch=_launch_config(root.get("fluent")),
        meshing=_mapping(root.get("meshing", {}), "meshing"),
        solver=_mapping(root.get("solver", {}), "solver"),
        export=_mapping(root.get("export", {}), "export"),
        plotting=_mapping(root.get("plotting", {}), "plotting"),
    )


def validate_inputs(
    config: SimulationConfig,
    system: str | None = None,
    stages: Iterable[str] | None = None,
) -> None:
    """Validate external inputs immediately before a real run."""

    selected = tuple(stages) if stages is not None else config.stages
    if "mesh" in selected and not config.geometry.is_file():
        raise ConfigError(f"Geometry file does not exist: {config.geometry}")
    current_system = (system or platform.system()).lower()
    is_linux_dsco = current_system == "linux" and config.geometry.suffix.lower() == ".dsco"
    if "mesh" in selected and is_linux_dsco:
        raise ConfigError(
            "Discovery .dsco geometry is not supported by Fluent Meshing on Linux. "
            "Generate the intermediary .pmdb on Windows and point geometry at that file."
        )
