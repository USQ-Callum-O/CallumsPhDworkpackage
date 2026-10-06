"""Record Fluent DPM crossings during transient calculation."""

from contextlib import contextmanager
from collections.abc import Mapping
import json
from typing import Any
import warnings

from ..config import ConfigError
from .export import _prepare_surface


def validate_sampling(raw: Any) -> None:
    if raw is None:
        return
    if not isinstance(raw, Mapping):
        raise ConfigError("solver.dpm_sampling must be an object")
    injections = raw.get("injections")
    surfaces = raw.get("surfaces")
    if not isinstance(injections, list) or not injections or any(
        not isinstance(name, str) or not name for name in injections
    ):
        raise ConfigError("solver.dpm_sampling.injections requires injection names")
    if not isinstance(surfaces, list) or not surfaces or any(
        not isinstance(surface, Mapping) or surface.get("kind") != "plane"
        for surface in surfaces
    ):
        raise ConfigError("solver.dpm_sampling.surfaces requires plane definitions")
    for key in ("append_sample", "accumulate_rates", "sort_sample_files"):
        if key in raw and not isinstance(raw[key], bool):
            raise ConfigError(f"solver.dpm_sampling.{key} must be boolean")
    boundaries = raw.get("boundaries", [])
    if not isinstance(boundaries, list) or any(
        not isinstance(name, str) or not name for name in boundaries
    ):
        raise ConfigError("solver.dpm_sampling.boundaries must be a name array")


@contextmanager
def record_particles(session: Any, raw: Mapping[str, Any], artifacts: Any):
    """Start before calculate, flush on success or failure, and index actual output."""
    validate_sampling(raw)
    artifacts.dpm_samples.mkdir(parents=True, exist_ok=True)
    planes = [_prepare_surface(session, surface) for surface in raw["surfaces"]]
    boundaries = raw.get("boundaries", [])
    existing = list(artifacts.dpm_samples.glob("*.dpm"))
    if existing and not raw.get("append_sample", False):
        raise ConfigError(
            "DPM samples already exist; use a fresh run directory or explicitly enable "
            "solver.dpm_sampling.append_sample to extend them"
        )
    # Sampling has no filename argument in Fluent 2025 R1. Change the server's
    # directory explicitly: changing only the Python cwd is insufficient on HPC.
    session.chdir(artifacts.dpm_samples.as_posix())
    sample = session.settings.results.report.discrete_phase.sample_trajectories
    sample.sort_sample_files.set_state(raw.get("sort_sample_files", True))
    sample.start_file_write(
        injections=raw["injections"], boundaries=boundaries, lines=[], planes=planes,
        append_sample=raw.get("append_sample", False),
        accumulate_rates=raw.get("accumulate_rates", True),
    )
    failed = False
    try:
        yield
    except BaseException:
        failed = True
        raise
    finally:
        try:
            sample.stop_file_write()
        except Exception as exc:
            if not failed:
                raise
            warnings.warn(f"DPM sampling flush failed during solver failure: {exc}")
        files = sorted(artifacts.dpm_samples.glob("*.dpm"))
        index = {
            "injections": raw["injections"], "planes": planes,
            "boundaries": boundaries, "solver_failed": failed,
            "files": [{"name": path.name, "bytes": path.stat().st_size} for path in files],
            "expected_files": [f"{name}.dpm" for name in [*planes, *boundaries]],
        }
        (artifacts.dpm_samples / "sampling_manifest.json").write_text(
            json.dumps(index, indent=2) + "\n", encoding="utf-8"
        )
        if not files and not failed:
            raise RuntimeError(
                f"Fluent sampling produced no .dpm files in {artifacts.dpm_samples}; "
                "inspect the transcript and particle injection/fate summary"
            )
