"""Public use-case facade for the qlib-extended distribution."""

from pathlib import Path

from .attribution import build_signed_attribution
from .config import ConfigurationError
from .enhanced_attribution import build_enhanced_index_attribution
from .ensemble import build_ensemble
from .reporting import create_report
from .runner import run_strategy_batch
from .store import RunCatalog


def open_run_catalog(path: str | Path) -> RunCatalog:
    return RunCatalog.open(path)


__all__ = [
    "ConfigurationError",
    "build_enhanced_index_attribution",
    "build_ensemble",
    "build_signed_attribution",
    "create_report",
    "open_run_catalog",
    "run_strategy_batch",
]
