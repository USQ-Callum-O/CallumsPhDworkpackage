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
from .solver import _autosave_settings


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
    # Explicit resume checkpoints are indexed independently of Fluent's .flprj
    # files.  This makes them discoverable even when restored native autosave
    # state is inactive or unreliable.
    for index in sorted(artifacts.autosave.rglob("checkpoint-step-*.json")):
        try:
            record = json.loads(index.read_text(encoding="utf-8"))
            step = int(record["time_step"])
            flow_time = float(record["flow_time_s"])
            case = _local_file(index.parent, str(record["case_file"]))
            data = _local_file(index.parent, str(record["data_file"]))
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ConfigError(f"Unreadable resume checkpoint index: {index}") from exc
        if checkpoint_step is not None and step != checkpoint_step:
            continue
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


def _write_checkpoint(session, directory: Path, config, step: int, flow_time: float,
                      case: Path, *, retain: int = 3) -> None:
    """Write and index one data checkpoint, retaining a bounded recent history."""
    data = directory / f"{config.run_name}-resume-{step:05d}.dat.h5"
    session.settings.file.write_data(file_name=str(data))
    if not data.is_file() or data.stat().st_size < 8:
        raise RuntimeError(f"Fluent did not write the requested checkpoint data file: {data}")
    index = directory / f"checkpoint-step-{step:05d}.json"
    index.write_text(json.dumps({
        "schema_version": 1,
        "time_step": step,
        "flow_time_s": flow_time,
        "case_file": case.name,
        "data_file": data.name,
    }, indent=2) + "\n", encoding="utf-8")
    indexes = sorted(directory.glob("checkpoint-step-*.json"))
    for old_index in indexes[:-retain]:
        try:
            old = json.loads(old_index.read_text(encoding="utf-8"))
            old_data = directory / str(old["data_file"])
            if old_data.is_file():
                old_data.unlink()
        finally:
            old_index.unlink(missing_ok=True)


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
        # Fluent 2025 R1 can fail at the end of a Settings-API data read when a
        # saved DPM sampling option is currently inactive (notably
        # sort-sample-files).  The TUI readers load the same checkpoint without
        # replaying that inactive Settings-API leaf.
        session.tui.file.read_case(str(plan.case))
        session.tui.file.read_data(str(plan.data))
        _verify_state(session, plan.step, plan.flow_time)
        controls = session.settings.solution.run_calculation.transient_controls
        loaded_dt = float(controls.time_step_size.get_state())
        if not math.isclose(loaded_dt, plan.step_size, rel_tol=1e-9):
            raise RuntimeError(f"Saved time step {loaded_dt} differs from configured {plan.step_size}")
        remaining = plan.target_step - plan.step
        if remaining:
            # Do not depend on restored Fluent autosave state.  Disable native
            # autosave and write verified checkpoints explicitly after bounded
            # calculation chunks.
            auto_save = _autosave_settings(session)
            auto_save.data_frequency.set_state(0)
            checkpoint_case = autosave / f"{config.run_name}-resume.cas.h5"
            session.settings.file.write_case(file_name=str(checkpoint_case))
            if not checkpoint_case.is_file() or checkpoint_case.stat().st_size < 8:
                raise RuntimeError(f"Fluent did not write the resume checkpoint case: {checkpoint_case}")
            # Redirect existing animation objects; never recreate scenes or injections.
            animations = session.settings.solution.calculation_activity.solution_animations
            for name in animations.get_object_names():
                animations[name].storage_dir.set_state(frames.as_posix())
            sampling = config.solver.get("dpm_sampling")
            sampling_artifacts = artifacts
            if sampling is not None:
                # Never move or overwrite an earlier interval.  Each resume writes
                # to its own immutable directory; analysis merges intervals later.
                interval = artifacts.data_export / "DPM_sample_intervals" / attempt
                interval.mkdir(parents=True, exist_ok=False)
                sampling_artifacts = replace(artifacts, dpm_samples=interval)
                sampling = dict(sampling, append_sample=False)
                (interval / "resume_interval.json").write_text(json.dumps({
                    "start_time_s": plan.flow_time,
                    "target_time_s": plan.target_step * plan.step_size,
                    "checkpoint_step": plan.step,
                    "note": "Immutable resumed interval; merge during analysis.",
                }, indent=2) + "\n", encoding="utf-8")
            advanced = 0
            with (record_particles(session, sampling, sampling_artifacts)
                  if sampling else nullcontext()):
                while advanced < remaining:
                    chunk = min(plan.autosave_frequency, remaining - advanced)
                    controls.time_step_count.set_state(chunk)
                    session.settings.solution.run_calculation.calculate()
                    advanced += chunk
                    expected_step = plan.step + advanced
                    expected_time = plan.flow_time + advanced * plan.step_size
                    _verify_state(session, expected_step, expected_time)
                    _write_checkpoint(
                        session, autosave, config, expected_step, expected_time,
                        checkpoint_case, retain=3,
                    )
            _verify_state(session, plan.target_step, plan.target_step * plan.step_size)
        session.settings.file.write_case_data(file_name=str(artifacts.case_data_base))
