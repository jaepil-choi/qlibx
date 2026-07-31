"""Echolon backtest engine — Backtrader wrapper, Optuna optimization, walk-forward analysis.

Uses PEP 562 lazy loading to avoid circular imports when internal strategy/markets
modules reach into echolon.backtest.logging_utils during their own import.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from echolon.backtest.portfolio_runner import PortfolioBacktestRunner
    from echolon.backtest.runner import run_backtest, run_best_trial, run_debug_backtest
    from echolon.backtest.schemas import (
        BacktestResultsSchemaV4,
        SelectedTrialSchema,
    )

__all__ = [
    "PortfolioBacktestRunner",
    "run_backtest",
    "run_best_trial",
    "run_debug_backtest",
    "BacktestResultsSchemaV4",
    "SelectedTrialSchema",
]

_LAZY_ATTRS = {
    "PortfolioBacktestRunner": ("echolon.backtest.portfolio_runner", "PortfolioBacktestRunner"),
    "run_backtest": ("echolon.backtest.runner", "run_backtest"),
    "run_best_trial": ("echolon.backtest.runner", "run_best_trial"),
    "run_debug_backtest": ("echolon.backtest.runner", "run_debug_backtest"),
    "BacktestResultsSchemaV4": ("echolon.backtest.schemas", "BacktestResultsSchemaV4"),
    "SelectedTrialSchema": ("echolon.backtest.schemas", "SelectedTrialSchema"),
}


def __getattr__(name: str):
    if name in _LAZY_ATTRS:
        module_path, attr_name = _LAZY_ATTRS[name]
        import importlib

        module = importlib.import_module(module_path)
        value = getattr(module, attr_name)
        globals()[name] = value
        return value
    raise AttributeError(f"module 'echolon.backtest' has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(list(globals().keys()) + list(_LAZY_ATTRS.keys()))
