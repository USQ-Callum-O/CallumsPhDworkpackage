"""Export reusable line, plane, and existing-surface data from Fluent."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Mapping

from ..artifacts import RunArtifacts
from ..config import ConfigError, SimulationConfig
from ..fluent import managed_session
from ..operations import apply_operations


SAFE_EXPORT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _ensure_named(collection: Any, name: str) -> Any:
    if name not in getattr(collection, "child_names", []):
        collection.create(name=name)
    return collection[name]


def _prepare_surface(session: Any, spec: Mapping[str, Any]) -> str:
    name = str(spec.get("name", ""))
    if not SAFE_EXPORT_NAME.fullmatch(name):
        raise ConfigError(f"invalid export surface name: {name!r}")
    kind = spec.get("kind", "existing")
    if kind == "existing":
        return name
    if kind == "line":
        line = _ensure_named(session.settings.results.surfaces.line_surface, name)
        line.p0 = spec["p0"]
        line.p1 = spec["p1"]
        return name
    if kind == "plane":
        plane = _ensure_named(session.settings.results.surfaces.plane_surface, name)
        method = spec.get("method", "xy-plane")
        plane.method = method
        if method == "three-points":
            plane.p0 = spec["p0"]
            plane.p1 = spec["p1"]
            plane.p2 = spec["p2"]
            if "bounded" in spec:
                plane.bounded = bool(spec["bounded"])
            return name
        coordinate_key = {"xy-plane": "z", "yz-plane": "x", "zx-plane": "y"}.get(method)
        if coordinate_key is None:
            raise ConfigError(f"unsupported plane method: {method}")
        setattr(plane, coordinate_key, float(spec[coordinate_key]))
        return name
    raise ConfigError(f"unsupported export surface kind: {kind}")


def _output_directory(artifacts: RunArtifacts, value: str) -> Path:
    directories = {
        "line": artifacts.line_data,
        "contour": artifacts.contour_data,
        "throat": artifacts.throat_data,
    }
    try:
        return directories[value]
    except KeyError as exc:
        raise ConfigError("export destination must be 'line', 'contour', or 'throat'") from exc


def _write_profile(
    session: Any,
    artifacts: RunArtifacts,
    surface_name: str,
    raw: Any,
) -> None:
    if raw is None:
        return
    if not isinstance(raw, Mapping):
        raise ConfigError(f"profile definition for {surface_name!r} must be an object")
    filename = str(raw.get("filename", ""))
    if not SAFE_EXPORT_NAME.fullmatch(filename) or Path(filename).suffix.lower() != ".prof":
        raise ConfigError(f"invalid Fluent profile filename: {filename!r}")
    fields = raw.get("fields")
    if (
        not isinstance(fields, list)
        or not fields
        or any(not isinstance(field, str) or not field for field in fields)
    ):
        raise ConfigError(f"profile definition for {surface_name!r} requires string fields")
    output = artifacts.profile_data / filename
    session.tui.file.write_profile(
        output.as_posix(),
        surface_name,
        "()",
        *fields,
        "()",
    )


def run_export(
    config: SimulationConfig,
    artifacts: RunArtifacts,
    launcher: Any = None,
) -> None:
    """Load case/data and export configured surfaces as Fluent ASCII CSV."""

    exports = config.export.get("surfaces", [])
    operations = config.export.get("operations", [])
    if not isinstance(exports, list) or not isinstance(operations, list):
        raise ConfigError("export.surfaces and export.operations must be arrays")
    if not artifacts.case.is_file() or not artifacts.data.is_file():
        raise FileNotFoundError(
            f"Export requires both case and data files: {artifacts.case}, {artifacts.data}"
        )

    with managed_session("solver", config.launch, launcher) as session:
        session.settings.file.read_case(file_name=str(artifacts.case))
        session.settings.file.read_data(file_name=str(artifacts.data))
        context = artifacts.context() | {
            name: path.as_posix() for name, path in config.inputs.items()
        }
        apply_operations(session, operations, context)
        for index, spec in enumerate(exports, start=1):
            if not isinstance(spec, Mapping):
                raise ConfigError(f"export surface {index} must be an object")
            surface_name = _prepare_surface(session, spec)
            fields = spec.get("fields")
            if not isinstance(fields, list) or not fields:
                raise ConfigError(f"export surface {surface_name!r} requires fields")
            destination = _output_directory(artifacts, str(spec.get("destination", "contour")))
            output = destination / f"{surface_name}.csv"
            session.settings.file.export.ascii(
                file_name=output.as_posix(),
                surface_name_list=[surface_name],
                delimiter="comma",
                cell_func_domain=list(fields),
            )
            _write_profile(session, artifacts, surface_name, spec.get("profile"))
