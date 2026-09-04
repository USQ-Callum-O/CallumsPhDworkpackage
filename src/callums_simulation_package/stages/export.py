"""Export reusable line, plane, and existing-surface data from Fluent."""

from __future__ import annotations

import csv
from numbers import Real
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


def _report_value(raw: Any, report_name: str) -> float:
    """Extract a scalar from Fluent's report-definitions.compute response."""

    if isinstance(raw, Mapping):
        if report_name in raw:
            return _report_value(raw[report_name], report_name)
        for value in raw.values():
            try:
                return _report_value(value, report_name)
            except ConfigError:
                continue
    elif isinstance(raw, (list, tuple)):
        for value in raw:
            try:
                return _report_value(value, report_name)
            except ConfigError:
                continue
    elif isinstance(raw, Real) and not isinstance(raw, bool):
        return float(raw)
    raise ConfigError(
        f"Fluent returned no numeric value for surface report {report_name!r}: {raw!r}"
    )


def _write_surface_reports(
    session: Any,
    artifacts: RunArtifacts,
    raw_reports: Any,
) -> None:
    if raw_reports is None:
        return
    if not isinstance(raw_reports, list):
        raise ConfigError("export.surface_reports must be an array")
    if not raw_reports:
        return

    definitions = session.settings.solution.report_definitions
    rows: list[dict[str, Any]] = []
    for index, spec in enumerate(raw_reports, start=1):
        if not isinstance(spec, Mapping):
            raise ConfigError(f"export surface report {index} must be an object")
        name = str(spec.get("name", ""))
        surface_name = str(spec.get("surface", ""))
        field = str(spec.get("field", "pressure"))
        report_type = str(spec.get("report_type", "area-weighted-avg"))
        if not SAFE_EXPORT_NAME.fullmatch(name):
            raise ConfigError(f"invalid surface report name: {name!r}")
        if not SAFE_EXPORT_NAME.fullmatch(surface_name):
            raise ConfigError(
                f"invalid surface name for report {name!r}: {surface_name!r}"
            )
        report = _ensure_named(definitions.surface, name)
        report.report_type = report_type
        report.field = field
        report.surface_names = [surface_name]
        result = definitions.compute(report_defs=[name])
        rows.append(
            {
                "report_name": name,
                "surface_name": surface_name,
                "axial_position_or_span_m": float(spec["axial_position_m"]),
                "field": field,
                "report_type": report_type,
                "value": _report_value(result, name),
                "units": str(spec.get("units", "Pa")),
            }
        )

    if len(rows) == 2:
        rows.append(
            {
                "report_name": "pressure_drop_start_minus_end",
                "surface_name": (
                    f"{rows[0]['surface_name']} - {rows[1]['surface_name']}"
                ),
                "axial_position_or_span_m": (
                    rows[1]["axial_position_or_span_m"]
                    - rows[0]["axial_position_or_span_m"]
                ),
                "field": "pressure",
                "report_type": "derived-difference",
                "value": rows[0]["value"] - rows[1]["value"],
                "units": "Pa",
            }
        )

    output = artifacts.data_export / "pressure-loss.csv"
    with output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def run_export(
    config: SimulationConfig,
    artifacts: RunArtifacts,
    launcher: Any = None,
) -> None:
    """Load case/data and export configured surfaces as Fluent ASCII CSV."""

    exports = config.export.get("surfaces", [])
    surface_reports = config.export.get("surface_reports", [])
    operations = config.export.get("operations", [])
    if (
        not isinstance(exports, list)
        or not isinstance(surface_reports, list)
        or not isinstance(operations, list)
    ):
        raise ConfigError(
            "export.surfaces, export.surface_reports, and export.operations must be arrays"
        )
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
        _write_surface_reports(session, artifacts, surface_reports)
