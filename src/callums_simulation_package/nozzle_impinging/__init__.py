"""Nozzle impingement simulation entry points."""

from .._domain import run_domain


def run(config, stages=None, **kwargs):
    return run_domain("nozzle_impinging", config, stages=stages, **kwargs)


__all__ = ["run"]
