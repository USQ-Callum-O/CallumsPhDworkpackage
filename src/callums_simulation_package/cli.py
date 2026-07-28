"""Command-line interface for local and PBS batch execution."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .config import ConfigError
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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
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

