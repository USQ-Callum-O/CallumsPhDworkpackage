"""Read-only inventory and static audit for the legacy simulation tree."""

from __future__ import annotations

import argparse
import ast
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path, PureWindowsPath
import re
import tokenize
from typing import Any


EXCLUDED_PARTS = {".venv", "__pycache__", ".git"}
PATH_KEYS = {
    "geometry_file",
    "geometry_script",
    "meshing_script",
    "solver_script",
    "Results_script",
    "Results_export_script",
    "Results_plotting_script",
    "resume_script",
    "resume_data_file",
    "rgp_air_file",
    "rgp_h2o_vapor_file",
    "Partially_solved",
}
WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:[\\/]")


def included(path: Path) -> bool:
    return not EXCLUDED_PARTS.intersection(path.parts)


def dotted_name(node: ast.AST) -> str | None:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def has_main_guard(tree: ast.Module) -> bool:
    for node in tree.body:
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if not isinstance(test, ast.Compare) or len(test.ops) != 1:
            continue
        if not isinstance(test.left, ast.Name) or test.left.id != "__name__":
            continue
        values = [test.left, *test.comparators]
        if any(isinstance(value, ast.Constant) and value.value == "__main__" for value in values):
            return True
    return False


def top_level_executable_count(tree: ast.Module) -> int:
    safe = (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    count = 0
    for node in tree.body:
        if isinstance(node, safe):
            continue
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            continue
        if isinstance(node, ast.Assign) and all(
            isinstance(target, ast.Name) for target in node.targets
        ):
            continue
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            continue
        if isinstance(node, ast.If) and has_main_guard(ast.Module(body=[node], type_ignores=[])):
            continue
        count += 1
    return count


def source_text(path: Path) -> str:
    with tokenize.open(path) as handle:
        return handle.read()


def analyse_python(path: Path, root: Path) -> dict[str, Any]:
    relative = path.relative_to(root).as_posix()
    try:
        source = source_text(path)
    except (OSError, UnicodeError, SyntaxError) as exc:
        return {"path": relative, "read_error": f"{type(exc).__name__}: {exc}"}

    result: dict[str, Any] = {
        "path": relative,
        "lines": len(source.splitlines()),
        "bytes": len(source.encode("utf-8")),
        "sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
    }
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        result["syntax_error"] = f"line {exc.lineno}: {exc.msg}"
        return result

    imports: set[str] = set()
    calls: Counter[str] = Counter()
    hardcoded_paths: set[str] = set()
    bare_except = 0
    broad_except = 0
    mutable_defaults = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.add(node.module or "")
        elif isinstance(node, ast.Call):
            name = dotted_name(node.func)
            if name:
                calls[name] += 1
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if WINDOWS_ABSOLUTE.match(node.value):
                hardcoded_paths.add(node.value)
        elif isinstance(node, ast.ExceptHandler):
            if node.type is None:
                bare_except += 1
            elif isinstance(node.type, ast.Name) and node.type.id in {"Exception", "BaseException"}:
                broad_except += 1
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defaults = [*node.args.defaults, *node.args.kw_defaults]
            mutable_defaults += sum(
                isinstance(default, (ast.List, ast.Dict, ast.Set)) for default in defaults
            )

    result.update(
        {
            "functions": sum(
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) for node in tree.body
            ),
            "classes": sum(isinstance(node, ast.ClassDef) for node in tree.body),
            "imports": sorted(imports),
            "calls": dict(calls.most_common()),
            "has_main_guard": has_main_guard(tree),
            "top_level_executable": top_level_executable_count(tree),
            "hardcoded_paths": sorted(hardcoded_paths),
            "bare_except": bare_except,
            "broad_except": broad_except,
            "mutable_defaults": mutable_defaults,
            "uses_sys_argv": "sys.argv" in calls or "sys.argv" in source,
            "uses_os_chdir": "os.chdir" in calls,
            "uses_subprocess": any(name.startswith("subprocess.") for name in calls),
            "uses_launch_fluent": any(name.endswith("launch_fluent") for name in calls),
            "uses_plt_show": "plt.show" in calls or "matplotlib.pyplot.show" in calls,
        }
    )
    return result


def windows_path_exists(raw: str) -> bool:
    if not WINDOWS_ABSOLUTE.match(raw):
        return False
    windows = PureWindowsPath(raw)
    return Path(windows.drive + windows.root, *windows.parts[1:]).exists()


def analyse_config(path: Path, root: Path) -> dict[str, Any]:
    relative = path.relative_to(root).as_posix()
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return {"path": relative, "error": f"{type(exc).__name__}: {exc}"}

    missing_inputs: list[dict[str, str]] = []
    absolute_values: list[str] = []
    for key, value in data.items():
        if not isinstance(value, str) or not WINDOWS_ABSOLUTE.match(value):
            continue
        absolute_values.append(key)
        if key in PATH_KEYS and not windows_path_exists(value):
            missing_inputs.append({"key": key, "value": value})
    return {
        "path": relative,
        "keys": sorted(data),
        "absolute_path_keys": sorted(absolute_values),
        "missing_inputs": missing_inputs,
    }


def summarise(root: Path) -> dict[str, Any]:
    python_files = sorted(path for path in root.rglob("*.py") if included(path))
    config_files = sorted(path for path in root.rglob("*.json") if included(path))
    python = [analyse_python(path, root) for path in python_files]
    configs = [analyse_config(path, root) for path in config_files]

    hashes: dict[str, list[str]] = defaultdict(list)
    for item in python:
        if "sha256" in item:
            hashes[item["sha256"]].append(item["path"])

    import_counts: Counter[str] = Counter()
    for item in python:
        import_counts.update(item.get("imports", []))

    return {
        "root": str(root),
        "summary": {
            "python_files": len(python),
            "config_files": len(configs),
            "python_lines": sum(item.get("lines", 0) for item in python),
            "syntax_errors": sum("syntax_error" in item for item in python),
            "read_errors": sum("read_error" in item for item in python),
            "files_with_top_level_execution": sum(
                item.get("top_level_executable", 0) > 0 for item in python
            ),
            "files_with_hardcoded_paths": sum(bool(item.get("hardcoded_paths")) for item in python),
            "files_using_sys_argv": sum(item.get("uses_sys_argv", False) for item in python),
            "files_using_launch_fluent": sum(
                item.get("uses_launch_fluent", False) for item in python
            ),
            "files_using_plt_show": sum(item.get("uses_plt_show", False) for item in python),
            "missing_config_inputs": sum(len(item.get("missing_inputs", [])) for item in configs),
            "exact_duplicate_groups": sum(len(paths) > 1 for paths in hashes.values()),
        },
        "common_imports": import_counts.most_common(30),
        "duplicate_groups": [paths for paths in hashes.values() if len(paths) > 1],
        "python": python,
        "configs": configs,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="Legacy code directory to audit")
    parser.add_argument("--output", type=Path, help="Optional JSON report path")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = summarise(args.root.resolve())
    rendered = json.dumps(report, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
