"""Configuration-driven Fluent solver stage."""

from __future__ import annotations

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
    with managed_session("solver", config.launch, launcher) as session:
        _read_input(session, str(solver.get("input", "mesh")), artifacts)
        context = artifacts.context() | {
            name: path.as_posix() for name, path in config.inputs.items()
        }
        apply_operations(session, operations, context)
        if solver.get("write_case_data", True):
            session.settings.file.write_case_data(case_filename=str(artifacts.case_data_base))

