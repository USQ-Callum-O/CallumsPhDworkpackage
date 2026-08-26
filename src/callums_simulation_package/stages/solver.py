"""Configuration-driven Fluent solver stage."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..artifacts import RunArtifacts
from ..config import ConfigError, SimulationConfig
from ..fluent import managed_session
from ..operations import apply_operations


SAFE_ANIMATION_NAME = re.compile(r"^[A-Za-z0-9._-]+$")


def _require_file(path: Path, description: str) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"{description} does not exist: {path}")


def _read_input(session: Any, source: str, artifacts: RunArtifacts) -> None:
    if source == "mesh":
        _require_file(artifacts.mesh, "Mesh input")
        session.settings.file.read_case(file_name=str(artifacts.mesh))
        return
    if source == "case_data":
        _require_file(artifacts.case, "Case input")
        _require_file(artifacts.data, "Data input")
        session.settings.file.read_case(file_name=str(artifacts.case))
        session.settings.file.read_data(file_name=str(artifacts.data))
        return
    raise ConfigError("solver.input must be 'mesh' or 'case_data'")


def run_solver(
    config: SimulationConfig,
    artifacts: RunArtifacts,
    launcher: Any = None,
) -> None:
    """Read the mesh, apply solver operations, run, and save case/data."""

    solver = config.solver
    operations = solver.get("operations")
    if not isinstance(operations, list) or not operations:
        raise ConfigError("solver.operations must be a non-empty array")
    # Validate output settings before starting Fluent. A typo in a GIF name or
    # autosave frequency should not be discovered after a long HPC calculation.
    _autosave_values(solver)
    _animation_output_specs(solver)
    with managed_session("solver", config.launch, launcher) as session:
        _read_input(session, str(solver.get("input", "mesh")), artifacts)
        _configure_autosave(session, solver, artifacts)
        context = artifacts.context() | {
            name: path.as_posix() for name, path in config.inputs.items()
        }
        apply_operations(session, operations, context)
        if solver.get("write_case_data", True):
            # The canonical final pair is deliberately unsuffixed. Autosaves use
            # their own subdirectory, so neither output can overwrite the other.
            session.settings.file.write_case_data(
                file_name=str(artifacts.case_data_base)
            )
    _write_animation_outputs(solver, artifacts)


def _positive_int(value: Any, setting: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ConfigError(f"{setting} must be a positive integer")
    return value


def _autosave_settings(session: Any) -> Any:
    try:
        return session.settings.solution.calculation_activity.auto_save
    except AttributeError:
        # Older Fluent settings trees expose the same group below file.
        return session.settings.file.auto_save


def _autosave_values(
    solver: Mapping[str, Any],
) -> tuple[int, str, int] | None:
    autosave = solver.get("autosave")
    if autosave is None:
        return None
    if not isinstance(autosave, Mapping):
        raise ConfigError("solver.autosave must be an object")

    frequency = _positive_int(
        autosave.get("data_frequency"),
        "solver.autosave.data_frequency",
    )
    suffix = str(autosave.get("suffix", "time-step"))
    if suffix not in {"time-step", "flow-time", "iteration"}:
        raise ConfigError(
            "solver.autosave.suffix must be 'time-step', 'flow-time', or 'iteration'"
        )
    digits = _positive_int(
        autosave.get("digits", 5),
        "solver.autosave.digits",
    )
    return frequency, suffix, digits


def _configure_autosave(
    session: Any,
    solver: Mapping[str, Any],
    artifacts: RunArtifacts,
) -> None:
    values = _autosave_values(solver)
    if values is None:
        return
    frequency, suffix, digits = values

    auto_save = _autosave_settings(session)
    auto_save.root_name.set_state(artifacts.autosave_base.as_posix())
    auto_save.data_frequency.set_state(frequency)
    suffix_settings = auto_save.append_file_name_with
    try:
        suffix_settings.file_suffix_type.set_state(suffix)
        suffix_settings.file_decimal_digit.set_state(digits)
    except AttributeError:
        # Compatibility with Fluent trees where the suffix is a scalar.
        suffix_settings.set_state(suffix)
        auto_save.number_of_digits.set_state(digits)


def _natural_name(path: Path) -> list[int | str]:
    return [
        int(part) if part.isdigit() else part.lower()
        for part in re.split(r"(\d+)", path.name)
    ]


def _animation_output_specs(solver: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    outputs = solver.get("animation_outputs", [])
    if not isinstance(outputs, list):
        raise ConfigError("solver.animation_outputs must be an array")

    filenames: set[str] = set()
    validated: list[Mapping[str, Any]] = []
    for index, output in enumerate(outputs):
        location = f"solver.animation_outputs[{index}]"
        if not isinstance(output, Mapping):
            raise ConfigError(f"{location} must be an object")
        prefix = str(output.get("frame_prefix", ""))
        filename = str(output.get("filename", ""))
        if not SAFE_ANIMATION_NAME.fullmatch(prefix):
            raise ConfigError(f"Invalid {location}.frame_prefix: {prefix!r}")
        if not SAFE_ANIMATION_NAME.fullmatch(filename) or not filename.endswith(".gif"):
            raise ConfigError(f"Invalid {location}.filename: {filename!r}")
        if filename in filenames:
            raise ConfigError(f"Duplicate animation filename: {filename!r}")
        filenames.add(filename)

        duration = output.get("frame_duration_seconds", 0.1)
        if (
            isinstance(duration, bool)
            or not isinstance(duration, (int, float))
            or duration <= 0
        ):
            raise ConfigError(f"{location}.frame_duration_seconds must be positive")
        loop = output.get("loop", 0)
        if isinstance(loop, bool) or not isinstance(loop, int) or loop < 0:
            raise ConfigError(f"{location}.loop must be a non-negative integer")
        validated.append(output)
    return validated


def _write_animation_outputs(
    solver: Mapping[str, Any],
    artifacts: RunArtifacts,
    imageio: Any = None,
) -> list[Path]:
    outputs = _animation_output_specs(solver)
    if not outputs:
        return []
    if imageio is None:
        try:
            import imageio.v2 as imageio
        except ImportError as exc:
            raise ConfigError(
                "Animation output requires the optional 'plot' dependency"
            ) from exc

    written: list[Path] = []
    for output in outputs:
        prefix = str(output.get("frame_prefix", ""))
        filename = str(output.get("filename", ""))
        duration = output.get("frame_duration_seconds", 0.1)
        frames = sorted(
            artifacts.animation_frames.glob(f"{prefix}*.png"),
            key=_natural_name,
        )
        if not frames:
            raise FileNotFoundError(
                f"No animation frames matched {prefix!r} in "
                f"{artifacts.animation_frames}"
            )
        destination = artifacts.animation / filename
        with imageio.get_writer(
            destination,
            mode="I",
            duration=float(duration),
            loop=output.get("loop", 0),
        ) as writer:
            for frame in frames:
                writer.append_data(imageio.imread(frame))
        written.append(destination)
    return written
