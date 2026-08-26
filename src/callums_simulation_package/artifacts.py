"""Canonical result-tree construction."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path


CATEGORY_DIRECTORIES = {
    "nozzle": "Nozzle_simulations",
    "hose": "Hose_simulations",
    "nozzle_environment": "Nozzle_environment_simulations",
    "nozzle_impinging": "Nozzle_impinging_simulations",
}


@dataclass(frozen=True)
class RunArtifacts:
    """All paths produced by one simulation run."""

    run_root: Path
    case_and_data: Path
    data_export: Path
    throat_data: Path
    contour_data: Path
    line_data: Path
    profile_data: Path
    autosave: Path
    autosave_base: Path
    animation: Path
    animation_frames: Path
    results_plotting: Path
    line_plot: Path
    contour_plot: Path
    mesh: Path
    case: Path
    data: Path
    case_data_base: Path
    manifest: Path

    @classmethod
    def from_config(cls, config: object) -> "RunArtifacts":
        category = getattr(config, "category")
        run_name = getattr(config, "run_name")
        results_root = getattr(config, "results_root")
        category_dir = CATEGORY_DIRECTORIES[category]
        run_root = results_root / category_dir / run_name
        case_and_data = run_root / "Case_and_data"
        autosave = case_and_data / "Autosave"
        animation = run_root / "Animation"
        data_export = run_root / "Data_export"
        results_plotting = run_root / "Results_plotting"
        case_data_base = case_and_data / run_name
        return cls(
            run_root=run_root,
            case_and_data=case_and_data,
            data_export=data_export,
            throat_data=data_export / "Throat_data",
            contour_data=data_export / "Contour_data",
            line_data=data_export / "Line_data",
            profile_data=data_export / "Profile_data",
            autosave=autosave,
            autosave_base=autosave / run_name,
            animation=animation,
            animation_frames=animation / "Frames",
            results_plotting=results_plotting,
            line_plot=results_plotting / "Line_plot",
            contour_plot=results_plotting / "Contour_plot",
            mesh=case_and_data / f"{run_name}.msh.h5",
            case=case_and_data / f"{run_name}.cas.h5",
            data=case_and_data / f"{run_name}.dat.h5",
            case_data_base=case_data_base,
            manifest=run_root / "run_manifest.json",
        )

    def create_directories(self) -> None:
        for directory in (
            self.case_and_data,
            self.throat_data,
            self.contour_data,
            self.line_data,
            self.profile_data,
            self.autosave,
            self.animation_frames,
            self.line_plot,
            self.contour_plot,
        ):
            directory.mkdir(parents=True, exist_ok=True)

    def as_dict(self) -> dict[str, str]:
        return {key: str(value) for key, value in asdict(self).items()}

    def context(self) -> dict[str, str]:
        return self.as_dict()

