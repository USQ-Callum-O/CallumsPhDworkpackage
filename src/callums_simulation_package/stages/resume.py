"""Continue fixed-step transient runs from Fluent autosave project entries.

Never replay solver.operations: those include initialization and wall-film resets.
"""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import uuid
import xml.etree.ElementTree as ET

from ..artifacts import RunArtifacts
from ..config import ConfigError, SimulationConfig
from ..fluent import managed_session
from .particle_sampling import record_particles, validate_sampling
from .solver import _autosave_settings, _configure_autosave


@dataclass(frozen=True)
class ResumePlan:
    case: Path
    data: Path
    step: int
    flow_time: float
    target_step: int
    step_size: float
    max_iterations: int
    autosave_frequency: int

    def as_dict(self):
        return {
            "case": str(self.case), "data": str(self.data),
            "checkpoint_step": self.step, "checkpoint_flow_time_s": self.flow_time,
            "target_step": self.target_step,
            "target_flow_time_s": self.target_step * self.step_size,
            "remaining_steps": self.target_step - self.step,
            "autosave_frequency": self.autosave_frequency,
        }


def _positive_integer(value, name):
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ConfigError(f"{name} must be a positive integer")
    return value


def _local_file(directory: Path, value: str) -> Path:
    path = (directory / value).resolve()
    if not path.is_relative_to(directory.resolve()):
        raise ConfigError(f"Autosave project references a file outside its directory: {value}")
    return path


def prepare_resume(config: SimulationConfig, artifacts: RunArtifacts, *,
                   checkpoint_step=None, autosave_frequency=5) -> ResumePlan:
    """Use Fluent's recorded case/data association, not filename guesses or mtime order."""
    frequency = _positive_integer(autosave_frequency, "autosave_frequency")
    if checkpoint_step is not None:
        _positive_integer(checkpoint_step, "checkpoint_step")
    controls = {}
    prefix = "settings/solution/run_calculation/transient_controls/"
    operations = config.solver.get("operations", [])
    for operation in operations:
        if operation.get("action") == "set" and operation.get("path", "").startswith(prefix):
            controls[operation["path"][len(prefix):]] = operation["value"]
    calculates = [op for op in operations
                  if op.get("path") == "settings/solution/run_calculation/calculate"]
    if len(calculates) != 1 or operations[-1] != calculates[0]:
        raise ConfigError("Resume requires one calculate operation at the end of solver.operations")
    if controls.get("type") != "Fixed" or controls.get("method") != "User-Specified":
        raise ConfigError("Resume currently supports Fixed, User-Specified time steps only")
    target = _positive_integer(controls.get("time_step_count"), "target time_step_count")
    iterations = _positive_integer(controls.get("max_iter_per_time_step"), "max_iter_per_time_step")
    dt = float(controls.get("time_step_size", 0))
    if not math.isfinite(dt) or dt <= 0:
        raise ConfigError("time_step_size must be positive and finite")
    validate_sampling(config.solver.get("dpm_sampling"))
    candidates = []
    for project in sorted(artifacts.autosave.rglob(f"{config.run_name}.flprj")):
        try:
            # Fluent's XML-like format uses tags such as Run::OutputType,
            # which are not legal XML namespace names. Normalize tag names only.
            contents = project.read_text(encoding="utf-8-sig")
            contents = re.sub(r"(</?[\w.-]+)::", r"\1__", contents)
            root = ET.fromstring(contents)
        except ET.ParseError as exc:
            raise ConfigError(f"Unreadable autosave project: {project}; restore it before resuming") from exc
        for output in root.iter():
            metadata = output.find("Metadata")
            if metadata is None or metadata.find("time-step") is None:
                continue
            step = int(metadata.find("time-step").attrib["value"])
            if checkpoint_step is not None and step != checkpoint_step:
                continue
            flow_time = float(metadata.find("time").attrib["value"])
            for item in output:
                url = item.find("URL")
                if url is None or not url.get("value", "").endswith(".dat.h5"):
                    continue
                case_ref = item.find("Metadata/Case")
                if case_ref is None or not case_ref.get("value", "").startswith("LINK:"):
                    raise ConfigError(f"Missing case association in {project}")
                data = _local_file(project.parent, url.attrib["value"])
                case = _local_file(project.parent, case_ref.attrib["value"][5:])
                if case.is_file() and data.is_file():
                    candidates.append((step, data.stat().st_mtime_ns, case, data, flow_time))
    if not candidates:
        raise ConfigError(f"No matching case/data pair indexed by a .flprj in {artifacts.autosave}")
    step, _, case, data, flow_time = max(candidates, key=lambda item: item[:2])
    # Do not silently fall back from a corrupt newest checkpoint.
    # Metadata-only preflight avoids hydrating multi-GB cloud placeholders locally.
    # Fluent validates file contents when loading, before any calculation/sampling changes.
    if case.stat().st_size < 8 or data.stat().st_size < 8:
        raise ConfigError("Selected checkpoint is empty or truncated; select an older --checkpoint-step")
    if step > target or not math.isclose(flow_time, step * dt, rel_tol=1e-7, abs_tol=1e-9):
        raise ConfigError("Checkpoint time/step is inconsistent with the configured transient horizon")
    return ResumePlan(case, data, step, flow_time, target, dt, iterations, frequency)


def _verify_state(session, step, flow_time):
    actual_step = session.rp_vars("time-step")
    actual_time = float(session.rp_vars("flow-time"))
    if actual_step != step or not math.isclose(actual_time, flow_time, rel_tol=1e-7, abs_tol=1e-9):
        raise RuntimeError(
            f"Fluent state is step {actual_step}, time {actual_time}; expected {step}, {flow_time}"
        )


def run_resume(config, artifacts, launcher=None, *, resume_plan: ResumePlan):
    """Read saved physics and fields, then advance only the remaining time steps."""
    plan = resume_plan
    attempt = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    history = artifacts.run_root / "Resume_history" / attempt
    autosave = artifacts.autosave / attempt
    frames = artifacts.animation_frames / attempt
    for directory in (history, autosave, frames):
        directory.mkdir(parents=True, exist_ok=False)
    (history / "resume.json").write_text(json.dumps(plan.as_dict(), indent=2) + "\n", encoding="utf-8")
    with managed_session("solver", config.launch, launcher) as session:
        session.settings.file.read_case(file_name=str(plan.case))
        session.settings.file.read_data(file_name=str(plan.data))
        _verify_state(session, plan.step, plan.flow_time)
        controls = session.settings.solution.run_calculation.transient_controls
        loaded_dt = float(controls.time_step_size.get_state())
        if not math.isclose(loaded_dt, plan.step_size, rel_tol=1e-9):
            raise RuntimeError(f"Saved time step {loaded_dt} differs from configured {plan.step_size}")
        remaining = plan.target_step - plan.step
        if remaining:
            # Separate autosave roots protect the input case and every prior attempt.
            resumed_artifacts = replace(artifacts, autosave=autosave,
                                        autosave_base=autosave / config.run_name)
            _configure_autosave(session, {"autosave": {
                "data_frequency": plan.autosave_frequency, "suffix": "time-step", "digits": 5,
            }}, resumed_artifacts)
            auto_save = _autosave_settings(session)
            auto_save.retain_most_recent_files.set_state(True)
            auto_save.max_files.set_state(3)
            # Redirect existing animation objects; never recreate scenes or injections.
            animations = session.settings.solution.calculation_activity.solution_animations
            for name in animations.get_object_names():
                animations[name].storage_dir.set_state(frames.as_posix())
            sampling = config.solver.get("dpm_sampling")
            if sampling is not None:
                # Unflushed and post-checkpoint rows cannot safely be appended. Keep all
                # originals, including parallel rank files, for separate analysis.
                if artifacts.dpm_samples.exists():
                    artifacts.dpm_samples.rename(history / "DPM_samples")
                artifacts.dpm_samples.mkdir(parents=True)
                sampling = dict(sampling, append_sample=False)
                (artifacts.dpm_samples / "resume_interval.json").write_text(json.dumps({
                    "start_time_s": plan.flow_time,
                    "target_time_s": plan.target_step * plan.step_size,
                    "prior_samples": str(history / "DPM_samples"),
                    "note": "These samples cover this resumed interval only, not the full run.",
                }, indent=2) + "\n", encoding="utf-8")
            controls.time_step_count.set_state(remaining)
            with (record_particles(session, sampling, artifacts) if sampling else nullcontext()):
                session.settings.solution.run_calculation.calculate()
            _verify_state(session, plan.target_step, plan.target_step * plan.step_size)
        session.settings.file.write_case_data(file_name=str(artifacts.case_data_base))
