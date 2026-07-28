"""PyFluent lifecycle helpers with scheduler-safe launch defaults."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from .config import FluentLaunchConfig


class FluentUnavailableError(RuntimeError):
    """Raised when the optional PyFluent dependency is unavailable."""


def launch(mode: str, config: FluentLaunchConfig) -> Any:
    try:
        import ansys.fluent.core as pyfluent
    except ImportError as exc:
        raise FluentUnavailableError(
            "PyFluent is not installed. Install with: pip install -e '.[fluent]'"
        ) from exc
    return pyfluent.launch_fluent(mode=mode, **config.kwargs())


@contextmanager
def managed_session(mode: str, config: FluentLaunchConfig, launcher: Any = None) -> Iterator[Any]:
    """Launch one Fluent session and always return its resources/license."""

    session = None
    try:
        session = (launcher or launch)(mode, config)
        yield session
    finally:
        if session is not None:
            session.exit()

