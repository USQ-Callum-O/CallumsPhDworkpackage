"""Configuration-driven Fluent solver stage."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..artifacts import RunArtifacts
from ..config import ConfigError, SimulationConfig
from ..fluent import managed_session
from ..operations import apply_operations


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
    # Validate autosave settings before starting Fluent.
    _autosave_values(solver)
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

