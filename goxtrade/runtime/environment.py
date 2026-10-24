"""Keep direct worker entry points on this checkout's package path."""
import os

from goxtrade.paths import ROOT


def worker_environment(**overrides):
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(ROOT), environment.get("PYTHONPATH")) if part
    )
    environment.update(overrides)
    return environment
