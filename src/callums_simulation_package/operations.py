"""A small declarative adapter for versioned PyFluent settings operations."""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Any, Iterable, Mapping


PLACEHOLDER = re.compile(r"\{\{([A-Za-z_][A-Za-z0-9_]*)\}\}")


class OperationError(RuntimeError):
    """Raised when a declarative Fluent operation fails."""


def interpolate(value: Any, context: Mapping[str, str]) -> Any:
    if isinstance(value, str):
        return PLACEHOLDER.sub(lambda match: context[match.group(1)], value)
    if isinstance(value, list):
        return [interpolate(item, context) for item in value]
    if isinstance(value, dict):
        return {key: interpolate(item, context) for key, item in value.items()}
    return value


def resolve(root: Any, path: str) -> Any:
    """Resolve slash-delimited attributes; ``@name`` selects a named child."""

    current = root
    for segment in filter(None, path.split("/")):
        if segment.startswith("@"):
            current = current[segment[1:]]
        else:
            current = getattr(current, segment)
    return current


def deep_merge(base: dict[str, Any], update: Mapping[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in update.items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def apply_operation(root: Any, operation: Mapping[str, Any], context: Mapping[str, str]) -> Any:
    action = operation.get("action")
    path = operation.get("path")
    if not isinstance(action, str) or not isinstance(path, str):
        raise OperationError("each operation requires string action and path values")
    target = resolve(root, path)

    if action == "set":
        value = interpolate(operation.get("value"), context)
        return target.set_state(value)
    if action == "patch":
        update = interpolate(operation.get("value", {}), context)
        return target.set_state(deep_merge(target.get_state(), update))
    if action == "set_item":
        name = str(interpolate(operation["name"], context))
        target[name] = interpolate(operation.get("value"), context)
        return None
    if action == "create":
        name = str(interpolate(operation["name"], context))
        return target.create(name=name)
    if action == "delete":
        name = str(interpolate(operation["name"], context))
        if operation.get("if_exists", False) and name not in getattr(target, "child_names", []):
            return None
        return target.delete(name=name)
    if action == "call":
        args = interpolate(operation.get("args", []), context)
        kwargs = interpolate(operation.get("kwargs", {}), context)
        return target(*args, **kwargs)
    raise OperationError(f"unsupported operation action: {action}")


def apply_operations(
    root: Any,
    operations: Iterable[Mapping[str, Any]],
    context: Mapping[str, str],
) -> None:
    for index, operation in enumerate(operations, start=1):
        try:
            apply_operation(root, operation, context)
        except Exception as exc:
            path = operation.get("path", "<missing>")
            action = operation.get("action", "<missing>")
            raise OperationError(
                f"operation {index} failed ({action} {path}): {type(exc).__name__}: {exc}"
            ) from exc
