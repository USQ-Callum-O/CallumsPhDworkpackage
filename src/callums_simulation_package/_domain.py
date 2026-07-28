from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from .config import ConfigError, SimulationConfig, load_config
from .runner import RunPlan, run


def run_domain(
    expected_category: str,
    config: SimulationConfig | str | Path,
    stages: Iterable[str] | None = None,
    **kwargs: Any,
) -> RunPlan:
    loaded = config if isinstance(config, SimulationConfig) else load_config(config)
    if loaded.category != expected_category:
        raise ConfigError(
            f"{expected_category} entry point received a {loaded.category} configuration"
        )
    return run(loaded, stages=stages, **kwargs)

