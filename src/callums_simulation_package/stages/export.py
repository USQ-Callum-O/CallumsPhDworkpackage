"""Export surface data and direct Fluent surface-integral results."""

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


def _report_value(raw: Any, result_key: str) -> float:
    """Extract a scalar from Fluent's surface-integral query response."""

    if isinstance(raw, Mapping):
        if result_key in raw:
            return _report_value(raw[result_key], result_key)
        for value in raw.values():
            try:
                return _report_value(value, result_key)
            except ConfigError:
                continue
    elif isinstance(raw, (list, tuple)):
        for value in raw:
            try:
                return _report_value(value, result_key)
            except ConfigError:
                continue
    elif isinstance(raw, Real) and not isinstance(raw, bool):
        return float(raw)
    raise ConfigError(
        f"Fluent returned no numeric value for surface integral {result_key!r}: {raw!r}"
    )


def _difference_fields(report_value: float, integral_value: float) -> dict[str, Any]:
    difference = report_value - integral_value
    relative = (
        abs(difference) / abs(integral_value) * 100.0
        if integral_value != 0.0
        else None
    )
    return {
        "surface_report_value": report_value,
        "surface_integral_value": integral_value,
        "report_minus_integral": difference,
        "absolute_difference": abs(difference),
        "relative_difference_percent": relative,
    }


def _write_pressure_method_comparison(
    session: Any,
    artifacts: RunArtifacts,
    raw_reports: Any,
    raw_integrals: Any,
) -> None:
    if raw_reports is None:
        raw_reports = []
    if raw_integrals is None:
        raw_integrals = []
    if not isinstance(raw_reports, list):
        raise ConfigError("export.surface_reports must be an array")
    if not isinstance(raw_integrals, list):
        raise ConfigError("export.surface_integrals must be an array")
    if not raw_reports and not raw_integrals:
        return
    if not raw_reports or not raw_integrals:
        raise ConfigError(
            "pressure comparison requires both export.surface_reports and "
            "export.surface_integrals"
        )

    definitions = session.settings.solution.report_definitions
    surface_integrals = session.settings.results.report.surface_integrals
    report_values: dict[str, float] = {}
    report_specs: dict[str, Mapping[str, Any]] = {}
    for index, spec in enumerate(raw_reports, start=1):
        if not isinstance(spec, Mapping):
            raise ConfigError(f"export surface report {index} must be an object")
        name = str(spec.get("name", ""))
        surface_name = str(spec.get("surface", ""))
        field = str(spec.get("field", "pressure"))
        report_type = str(spec.get("report_type", "surface-areaavg"))
        if not SAFE_EXPORT_NAME.fullmatch(name):
            raise ConfigError(f"invalid surface report name: {name!r}")
        if name in report_values:
            raise ConfigError(f"duplicate surface report name: {name!r}")
        if report_type != "surface-areaavg":
            raise ConfigError(
                f"unsupported surface report type for {name!r}: {report_type!r}"
            )
        report = _ensure_named(definitions.surface, name)
        report.report_type = report_type
        report.field = field
        report.surface_names = [surface_name]
        result = definitions.compute(report_defs=[name])
        report_values[name] = _report_value(result, name)
        report_specs[name] = spec

    integral_values: dict[str, float] = {}
    integral_specs: dict[str, Mapping[str, Any]] = {}
    for index, spec in enumerate(raw_integrals, start=1):
        if not isinstance(spec, Mapping):
            raise ConfigError(f"export surface integral {index} must be an object")
        name = str(spec.get("name", ""))
        surface_name = str(spec.get("surface", ""))
        field = str(spec.get("field", "pressure"))
        integral_type = str(spec.get("integral_type", "area-weighted-average"))
        if not SAFE_EXPORT_NAME.fullmatch(name):
            raise ConfigError(f"invalid surface integral name: {name!r}")
        if name in integral_values:
            raise ConfigError(f"duplicate surface integral name: {name!r}")
        if not SAFE_EXPORT_NAME.fullmatch(surface_name):
            raise ConfigError(
                f"invalid surface name for integral {name!r}: {surface_name!r}"
            )
        if integral_type != "area-weighted-average":
            raise ConfigError(
                f"unsupported surface integral type for {name!r}: {integral_type!r}"
            )
        result = surface_integrals.get_area_weighted_avg(
            report_of=field,
            surface_names=[surface_name],
        )
        integral_values[name] = _report_value(result, surface_name)
        integral_specs[name] = spec

    # A config may contain extra surface reports that are not intended for the
    # report-vs-integral comparison. Compare only names present in both lists.
    matched_names = [name for name in report_values if name in integral_values]
    if not matched_names:
        raise ConfigError(
            "pressure comparison requires at least one matching surface report "
            "and surface integral name"
        )

    rows: list[dict[str, Any]] = []
    for name in matched_names:
        integral_value = integral_values[name]
        report_spec = report_specs[name]
        integral_spec = integral_specs[name]
        for key in ("surface", "field", "axial_position_m", "units"):
            if report_spec.get(key) != integral_spec.get(key):
                raise ConfigError(
                    f"surface report and integral {name!r} disagree on {key!r}"
                )
        rows.append(
            {
                "measurement_name": name,
                "surface_name": str(integral_spec["surface"]),
                "axial_position_or_span_m": float(
                    integral_spec["axial_position_m"]
                ),
                "field": str(integral_spec.get("field", "pressure")),
                **_difference_fields(report_values[name], integral_value),
                "units": str(integral_spec.get("units", "Pa")),
            }
        )

    if len(rows) == 2:
        report_drop = rows[0]["surface_report_value"] - rows[1]["surface_report_value"]
        integral_drop = (
            rows[0]["surface_integral_value"] - rows[1]["surface_integral_value"]
        )
        rows.append(
            {
                "measurement_name": "pressure_drop_start_minus_end",
                "surface_name": (
                    f"{rows[0]['surface_name']} - {rows[1]['surface_name']}"
                ),
                "axial_position_or_span_m": (
                    rows[1]["axial_position_or_span_m"]
                    - rows[0]["axial_position_or_span_m"]
                ),
                "field": "pressure",
                **_difference_fields(report_drop, integral_drop),
                "units": "Pa",
            }
        )

    output = artifacts.data_export / "pressure-loss.csv"
    with output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _area_weighted_average(
    surface_integrals: Any,
    field: str,
    surface_name: str,
) -> float:
    """Return one Fluent area-weighted average as a scalar."""

    result = surface_integrals.get_area_weighted_avg(
        report_of=field,
        surface_names=[surface_name],
    )
    return _report_value(result, surface_name)


def _volume_weighted_average(
    session: Any,
    field: str,
    cell_zone: str,
) -> float:
    """Return one Fluent cell-zone volume-weighted average as a scalar."""

    volume_integrals = session.settings.results.report.volume_integrals
    result = volume_integrals.get_volume_average(
        cell_zones=[cell_zone],
        cell_function=field,
    )
    return _report_value(result, cell_zone)


def _area_integral_expression(session: Any, expression: str, surface_name: str) -> float:
    """Evaluate an arbitrary Fluent expression over a named surface."""

    reduction = getattr(getattr(session, "fields", None), "reduction", None)
    area_integral = getattr(reduction, "area_integral", None)
    if area_integral is None:
        raise ConfigError(
            "This PyFluent version does not expose fields.reduction.area_integral; "
            "upgrade PyFluent or export this momentum integral directly in Fluent."
        )
    result = area_integral(expression=expression, locations=[surface_name])
    return _report_value(result, surface_name)


def _write_momentum_flux(
    session: Any,
    artifacts: RunArtifacts,
    raw: Any,
) -> None:
    """Write carrier-gas mass and axial momentum fluxes at configured planes.

    For an axial plane, the gas axial momentum flux is the sum of the static-
    pressure force and convective contribution integral(rho * uz**2 dA).
    Pressure is exported as gauge static pressure; its constant reference
    cancels when comparing equal-area hose planes.
    """

    if raw is None:
        return
    if not isinstance(raw, Mapping):
        raise ConfigError("export.momentum_flux must be an object")
    surfaces = raw.get("surfaces")
    if not isinstance(surfaces, list) or not surfaces:
        raise ConfigError("export.momentum_flux.surfaces must be a non-empty list")
    filename = str(raw.get("output_filename", "gas_momentum_flux_by_plane.csv"))
    if not SAFE_EXPORT_NAME.fullmatch(filename) or Path(filename).suffix.lower() != ".csv":
        raise ConfigError(f"invalid momentum-flux filename: {filename!r}")
    p_expr = str(raw.get("pressure_expression", "StaticPressure"))
    mdot_expr = str(raw.get("gas_mass_flux_expression", "Density*Velocity.z"))
    mom_expr = str(
        raw.get(
            "gas_convective_axial_momentum_expression",
            "Density*Velocity.z*Velocity.z",
        )
    )
    rows = []
    for index, spec in enumerate(surfaces, start=1):
        if not isinstance(spec, Mapping):
            raise ConfigError(f"export.momentum_flux.surfaces[{index}] must be an object")
        name = str(spec.get("surface", ""))
        if not SAFE_EXPORT_NAME.fullmatch(name):
            raise ConfigError(f"invalid momentum-flux surface name: {name!r}")
        try:
            reduction = getattr(getattr(session, "fields", None), "reduction", None)
            area_method = getattr(reduction, "area", None)
            if area_method is None:
                raise ConfigError("PyFluent fields.reduction.area is unavailable")
            area = _report_value(area_method(locations=[name]), name)
            pressure_force = _area_integral_expression(session, p_expr, name)
            gas_mass_flow = _area_integral_expression(session, mdot_expr, name)
            gas_convective = _area_integral_expression(session, mom_expr, name)
        except Exception as exc:
            # Preserve the normal surface exports if a site PyFluent build does
            # not support one of the expression reductions. The explicit error
            # is included in a status row rather than silently approximating
            # these fluxes from area averages.
            rows.append({
                "surface": name,
                "z_m": float(spec.get("z_m", float("nan"))),
                "status": f"integral_failed: {type(exc).__name__}: {exc}",
                "area_m2": float("nan"),
                "gas_mass_flow_kg_s": float("nan"),
                "pressure_force_N": float("nan"),
                "gas_convective_axial_momentum_flux_N": float("nan"),
                "gas_axial_momentum_flux_N": float("nan"),
            })
            continue
        rows.append({
            "surface": name,
            "z_m": float(spec.get("z_m", float("nan"))),
            "status": "ok",
            "area_m2": area,
            "gas_mass_flow_kg_s": gas_mass_flow,
            "pressure_force_N": pressure_force,
            "gas_convective_axial_momentum_flux_N": gas_convective,
            "gas_axial_momentum_flux_N": pressure_force + gas_convective,
        })
    output = artifacts.data_export / filename
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _write_flow_summary(
    session: Any,
    config: SimulationConfig,
    artifacts: RunArtifacts,
    raw: Any,
) -> None:
    """Export bulk properties, Reynolds number, and Darcy friction factor."""

    if raw is None:
        return
    if not isinstance(raw, Mapping):
        raise ConfigError("export.flow_summary must be an object")

    filename = str(raw.get("output_filename", "flow-summary.csv"))
    if not SAFE_EXPORT_NAME.fullmatch(filename) or Path(filename).suffix.lower() != ".csv":
        raise ConfigError(f"invalid flow-summary filename: {filename!r}")

    additional_rows = raw.get("additional_rows", [])
    if not isinstance(additional_rows, list):
        raise ConfigError("export.flow_summary.additional_rows must be an array")

    shared = dict(raw)
    shared.pop("additional_rows", None)
    method_specs: list[dict[str, Any]] = [shared]
    for index, overrides in enumerate(additional_rows, start=1):
        if not isinstance(overrides, Mapping):
            raise ConfigError(
                f"export.flow_summary.additional_rows[{index}] must be an object"
            )
        method_specs.append(shared | dict(overrides))

    surface_integrals = session.settings.results.report.surface_integrals

    surface_cache: dict[tuple[str, str], float] = {}
    volume_cache: dict[tuple[str, str], float] = {}

    def surface_average(field: str, surface_name: str) -> float:
        key = (field, surface_name)
        if key not in surface_cache:
            surface_cache[key] = _area_weighted_average(
                surface_integrals,
                field,
                surface_name,
            )
        return surface_cache[key]

    def volume_average(field: str, cell_zone: str) -> float:
        key = (field, cell_zone)
        if key not in volume_cache:
            volume_cache[key] = _volume_weighted_average(session, field, cell_zone)
        return volume_cache[key]

    rows: list[dict[str, Any]] = []
    method_names: set[str] = set()
    for index, spec in enumerate(method_specs, start=1):
        method_name = str(spec.get("method_name", "baseline"))
        if not SAFE_EXPORT_NAME.fullmatch(method_name):
            raise ConfigError(
                f"invalid flow-summary method name in row {index}: {method_name!r}"
            )
        if method_name in method_names:
            raise ConfigError(f"duplicate flow-summary method name: {method_name!r}")
        method_names.add(method_name)

        start_surface = str(spec.get("start_surface", ""))
        end_surface = str(spec.get("end_surface", ""))
        for label, surface_name in (
            ("start_surface", start_surface),
            ("end_surface", end_surface),
        ):
            if not SAFE_EXPORT_NAME.fullmatch(surface_name):
                raise ConfigError(
                    f"invalid export.flow_summary row {index} {label}: {surface_name!r}"
                )

            definition_key = label.replace("surface", "surface_definition")
            definition = spec.get(definition_key)
            if definition is not None:
                if not isinstance(definition, Mapping):
                    raise ConfigError(
                        f"export.flow_summary row {index} {definition_key} must be an object"
                    )
                prepared = dict(definition)
                prepared.setdefault("name", surface_name)
                if str(prepared["name"]) != surface_name:
                    raise ConfigError(
                        f"export.flow_summary row {index} {definition_key} name must "
                        f"match {label}"
                    )
                _prepare_surface(session, prepared)

        start_position = float(spec["start_axial_position_m"])
        end_position = float(spec["end_axial_position_m"])
        length = end_position - start_position
        diameter = float(spec["hydraulic_diameter_m"])
        viscosity = float(spec["dynamic_viscosity_pa_s"])
        if length <= 0.0:
            raise ConfigError("flow-summary end position must exceed start position")
        if diameter <= 0.0:
            raise ConfigError("flow-summary hydraulic diameter must be positive")
        if viscosity <= 0.0:
            raise ConfigError("flow-summary dynamic viscosity must be positive")

        pressure_field = str(spec.get("pressure_field", "pressure"))
        density_field = str(spec.get("density_field", "density"))
        velocity_field = str(spec.get("velocity_field", "z-velocity"))
        property_method = str(
            spec.get("fluid_property_average_method", "surface-area-average")
        )
        pressure_start = surface_average(pressure_field, start_surface)
        pressure_end = surface_average(pressure_field, end_surface)

        cell_zone: str | None = None
        if property_method == "surface-area-average":
            density_start = surface_average(density_field, start_surface)
            density_end = surface_average(density_field, end_surface)
            velocity_start = surface_average(velocity_field, start_surface)
            velocity_end = surface_average(velocity_field, end_surface)
            density_average = 0.5 * (density_start + density_end)
            velocity_average = abs(0.5 * (velocity_start + velocity_end))
        elif property_method == "volume-average":
            cell_zone = str(spec.get("fluid_property_cell_zone", ""))
            if not SAFE_EXPORT_NAME.fullmatch(cell_zone):
                raise ConfigError(
                    f"invalid flow-summary fluid property cell zone: {cell_zone!r}"
                )
            density_start = None
            density_end = None
            velocity_start = None
            velocity_end = None
            density_average = volume_average(density_field, cell_zone)
            velocity_average = abs(volume_average(velocity_field, cell_zone))
        else:
            raise ConfigError(
                "flow-summary fluid_property_average_method must be "
                "'surface-area-average' or 'volume-average'"
            )

        if density_average <= 0.0:
            raise ConfigError("flow-summary average density must be positive")
        if velocity_average <= 0.0:
            raise ConfigError("flow-summary average axial velocity must be non-zero")

        # Retain the signed start-minus-end value for diagnosis. A reversed or
        # developing solution can legitimately produce a non-positive value.
        pressure_drop = pressure_start - pressure_end
        pressure_drop_magnitude = abs(pressure_drop)
        reynolds_number = density_average * velocity_average * diameter / viscosity
        darcy_friction_factor = (
            2.0
            * pressure_drop_magnitude
            * diameter
            / (length * density_average * velocity_average**2)
        )
        rows.append(
            {
                "run_name": config.run_name,
                "cell_count": spec.get("cell_count"),
                "method_name": method_name,
                "pressure_field": pressure_field,
                "fluid_property_average_method": property_method,
                "fluid_property_cell_zone": cell_zone,
                "start_surface": start_surface,
                "end_surface": end_surface,
                "start_axial_position_m": start_position,
                "end_axial_position_m": end_position,
                "measurement_length_m": length,
                "hydraulic_diameter_m": diameter,
                "pressure_start_pa": pressure_start,
                "pressure_end_pa": pressure_end,
                "pressure_drop_pa": pressure_drop,
                "pressure_drop_magnitude_pa": pressure_drop_magnitude,
                "pressure_drop_direction_ok": pressure_drop > 0.0,
                "density_start_kg_m3": density_start,
                "density_end_kg_m3": density_end,
                "density_average_kg_m3": density_average,
                "axial_velocity_start_m_s": velocity_start,
                "axial_velocity_end_m_s": velocity_end,
                "axial_velocity_average_m_s": velocity_average,
                "dynamic_viscosity_average_pa_s": viscosity,
                "reynolds_number": reynolds_number,
                "darcy_friction_factor": darcy_friction_factor,
            }
        )

    output = artifacts.data_export / filename
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
    surface_integrals = config.export.get("surface_integrals", [])
    flow_summary = config.export.get("flow_summary")
    momentum_flux = config.export.get("momentum_flux")
    operations = config.export.get("operations", [])
    if (
        not isinstance(exports, list)
        or not isinstance(surface_reports, list)
        or not isinstance(surface_integrals, list)
        or not isinstance(operations, list)
    ):
        raise ConfigError(
            "export.surfaces, export.surface_reports, export.surface_integrals, "
            "and export.operations must be arrays"
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
        # The flow summary is independent of the optional pressure-method
        # comparison, so write it first.
        _write_flow_summary(session, config, artifacts, flow_summary)
        _write_momentum_flux(session, artifacts, momentum_flux)
        _write_pressure_method_comparison(
            session,
            artifacts,
            surface_reports,
            surface_integrals,
        )
