"""Small, responsibility-based public entry point for qlibx.

Submodules resolve on first attribute access. Importing them eagerly made ``import
qlibx`` pull DuckDB, PyArrow, cvxpy and the Qlib runtime before a caller had named a
single capability -- and made a presentation-only import pay for the execution engine.
The public names are unchanged: ``qlibx.alpha`` and ``from qlibx import alpha`` both
work, they just load what they name.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

from qlibx.errors import QlibxError
from qlibx.project import Project

if TYPE_CHECKING:  # pragma: no cover - import-time typing only
    # Redundant aliases mark these as re-exports: type checkers and editors resolve
    # `qlibx.alpha` statically while the runtime still loads it on first access.
    from qlibx import agent as agent
    from qlibx import alpha as alpha
    from qlibx import artifacts as artifacts
    from qlibx import data as data
    from qlibx import ensemble as ensemble
    from qlibx import execution as execution
    from qlibx import extensions as extensions
    from qlibx import portfolio as portfolio
    from qlibx import reporting as reporting
    from qlibx import requirements as requirements
    from qlibx import research as research
    from qlibx import storage as storage
    from qlibx import strategy as strategy
    from qlibx import strategy_manifest as strategy_manifest

# Every submodule reachable from the facade. The layering test reads this map, so a new
# public submodule has to be named here rather than appearing by accident.
_SUBMODULES = frozenset(
    {
        "agent",
        "alpha",
        "artifacts",
        "data",
        "ensemble",
        "execution",
        "extensions",
        "portfolio",
        "reporting",
        "requirements",
        "research",
        "storage",
        "strategy",
        "strategy_manifest",
    }
)

__all__ = ["Project", "QlibxError", *sorted(_SUBMODULES)]

__version__ = "0.1.0"


def __getattr__(name: str) -> Any:
    if name in _SUBMODULES:
        return import_module(f"{__name__}.{name}")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted({*globals(), *__all__})
