"""Public use-case facade for the qlib-extended distribution.

Attribute access is resolved lazily. Importing any single member used to pull the whole
subtree -- including the Qlib runtime -- so a caller that only wanted the stored-run
catalog paid for the execution engine it never touched.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - import-time typing only
    from .store import RunCatalog

_EXPORTS: dict[str, str] = {
    "ConfigurationError": "config",
    "RunCatalog": "store",
    "build_enhanced_index_attribution": "enhanced_attribution",
    "build_ensemble": "ensemble",
    "build_signed_attribution": "attribution",
    "create_report": "reporting",
    "run_strategy_batch": "runner",
}


def __getattr__(name: str) -> Any:
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    return getattr(import_module(f".{module_name}", __name__), name)


def __dir__() -> list[str]:
    return sorted({*globals(), *_EXPORTS})


def open_run_catalog(path: str | Path) -> RunCatalog:
    from .store import RunCatalog

    return RunCatalog.open(path)


__all__ = [
    "ConfigurationError",
    "RunCatalog",
    "build_enhanced_index_attribution",
    "build_ensemble",
    "build_signed_attribution",
    "create_report",
    "open_run_catalog",
    "run_strategy_batch",
]
