"""Command-line interface for local and PBS batch execution."""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
import re
from typing import Sequence

from .config import ConfigError, load_config
from .runner import plan, run, validate_plan_inputs


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="callums-sim", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("validate", "plan", "run"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("config", type=Path)
        subparser.add_argument(
            "--stages",
            nargs="+",
            choices=("mesh", "solve", "export", "plot"),
            help="Validate, plan, or run only this ordered subset of stages",
        )
    resume = subparsers.add_parser("resume", help="Continue a saved fixed-step transient solution")
    resume.add_argument("config", type=Path)
    resume.add_argument("--stages", nargs="+", choices=("solve", "export", "plot"),
                        default=["solve", "export", "plot"])
    resume.add_argument("--dry-run", action="store_true", help="Inspect checkpoint without launching Fluent")
    resume.add_argument("--checkpoint-step", type=int, help="Select a particular saved time step")
    resume.add_argument("--autosave-frequency", type=int, default=5)
    resume.add_argument("--processors", type=int, help="Override launch CPU count without editing physics config")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "resume":
            from .stages.resume import prepare_resume

            config = load_config(args.config)
            if args.processors is not None:
                if args.processors < 1:
                    raise ConfigError("--processors must be positive")
                additional = re.sub(r"(?<!\S)-t\s*\d+\b", "", config.launch.additional_arguments or "").strip()
                config = replace(config, launch=replace(
                    config.launch, processor_count=args.processors,
                    additional_arguments=f"{additional} -t{args.processors}".strip(),
                ))
            options = {"checkpoint_step": args.checkpoint_step,
                       "autosave_frequency": args.autosave_frequency}
            run_plan = plan(config, args.stages)
            if run_plan.stages[0] != "solve":
                raise ConfigError("Resume stages must start with solve")
            checkpoint = prepare_resume(config, run_plan.artifacts, **options)
            print(json.dumps(checkpoint.as_dict() | {"launch": config.launch.kwargs()}, indent=2))
            if args.dry_run:
                # Include the existing manifest guard in preflight, without writing it.
                from .runner import _manifest, _merge_prior_manifest

                _merge_prior_manifest(run_plan, _manifest(run_plan))
                return 0
            run(config, args.stages, resume_options=options)
            print(f"Completed resumed stages: {run_plan.artifacts.run_root}")
            return 0
        if args.command == "validate":
            run_plan = plan(args.config, args.stages)
            validate_plan_inputs(run_plan)
            print(f"Valid: {run_plan.config.source}")
            return 0
        if args.command == "plan":
            print(json.dumps(plan(args.config, args.stages).as_dict(), indent=2))
            return 0
        run_plan = run(args.config, args.stages)
        print(f"Completed: {run_plan.artifacts.run_root}")
        return 0
    except (ConfigError, FileNotFoundError, RuntimeError) as exc:
        print(f"ERROR: {exc}")
        return 2

