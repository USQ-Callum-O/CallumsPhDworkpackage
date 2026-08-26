"""Headless, configuration-driven plots for exported Fluent CSV data."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Mapping

from ..artifacts import RunArtifacts
from ..config import ConfigError, SimulationConfig


SAFE_FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\.(?:png|jpg|jpeg|pdf)$", re.IGNORECASE)


def _libraries() -> tuple[Any, Any, Any]:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
        import pandas as pd
    except ImportError as exc:
        raise RuntimeError(
            "Plotting dependencies are missing; install with: pip install -e '.[plot]'"
        ) from exc
    return plt, np, pd


def _source_path(artifacts: RunArtifacts, raw: str) -> Path:
    source = (artifacts.data_export / raw).resolve()
    if not source.is_relative_to(artifacts.data_export.resolve()):
        raise ConfigError("plot source must stay inside the run's Data_export directory")
    if not source.is_file():
        raise FileNotFoundError(f"plot source does not exist: {source}")
    return source


def _frame(pd: Any, source: Path) -> Any:
    frame = pd.read_csv(source, comment="(", skip_blank_lines=True)
    frame.columns = [str(column).strip().strip('"').strip("()") for column in frame.columns]
    return frame


def _filename(raw: Any) -> str:
    value = str(raw or "")
    if not SAFE_FILENAME.fullmatch(value):
        raise ConfigError(f"invalid plot filename: {value!r}")
    return value


def _line_plot(spec: Mapping[str, Any], artifacts: RunArtifacts, plt: Any, pd: Any) -> None:
    frame = _frame(pd, _source_path(artifacts, str(spec["source"])))
    x_name = str(spec["x"])
    y_names = spec["y"]
    if not isinstance(y_names, list) or not y_names:
        raise ConfigError("line plot y must be a non-empty array")
    missing = [name for name in [x_name, *y_names] if name not in frame.columns]
    if missing:
        raise ConfigError(f"line plot columns not found: {missing}")
    figure, axis = plt.subplots(figsize=(8, 5))
    for y_name in y_names:
        axis.plot(frame[x_name], frame[y_name], label=y_name)
    axis.set_xlabel(spec.get("x_label", x_name))
    axis.set_ylabel(spec.get("y_label", "Value"))
    axis.set_title(spec.get("title", ""))
    axis.grid(True, alpha=0.25)
    if len(y_names) > 1:
        axis.legend()
    figure.tight_layout()
    figure.savefig(artifacts.line_plot / _filename(spec.get("filename")), dpi=200)
    plt.close(figure)


def _contour_plot(
    spec: Mapping[str, Any], artifacts: RunArtifacts, plt: Any, np: Any, pd: Any
) -> None:
    frame = _frame(pd, _source_path(artifacts, str(spec["source"])))
    x_name, y_name, value_name = (str(spec[key]) for key in ("x", "y", "value"))
    missing = [name for name in (x_name, y_name, value_name) if name not in frame.columns]
    if missing:
        raise ConfigError(f"contour plot columns not found: {missing}")
    clean = frame[[x_name, y_name, value_name]].apply(pd.to_numeric, errors="coerce").dropna()
    finite = np.isfinite(clean.to_numpy()).all(axis=1)
    clean = clean.loc[finite]
    if len(clean) < 3:
        raise ConfigError("contour plot requires at least three finite points")
    figure, axis = plt.subplots(figsize=(8, 6))
    contour = axis.tricontourf(
        clean[x_name],
        clean[y_name],
        clean[value_name],
        levels=int(spec.get("levels", 30)),
        cmap=str(spec.get("cmap", "viridis")),
    )
    figure.colorbar(contour, ax=axis, label=spec.get("colorbar_label", value_name))
    axis.set_xlabel(spec.get("x_label", x_name))
    axis.set_ylabel(spec.get("y_label", y_name))
    axis.set_title(spec.get("title", ""))
    axis.set_aspect(spec.get("aspect", "equal"))
    figure.tight_layout()
    figure.savefig(artifacts.contour_plot / _filename(spec.get("filename")), dpi=200)
    plt.close(figure)


def run_plotting(config: SimulationConfig, artifacts: RunArtifacts, launcher: Any = None) -> None:
    """Generate all configured line and contour plots without a display server."""

    del launcher
    line_plots = config.plotting.get("line_plots", [])
    contour_plots = config.plotting.get("contour_plots", [])
    if not isinstance(line_plots, list) or not isinstance(contour_plots, list):
        raise ConfigError("plotting.line_plots and plotting.contour_plots must be arrays")
    plt, np, pd = _libraries()
    for spec in line_plots:
        _line_plot(spec, artifacts, plt, pd)
    for spec in contour_plots:
        _contour_plot(spec, artifacts, plt, np, pd)
