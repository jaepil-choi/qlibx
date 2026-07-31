"""Echolon public entry points accept a ``paths=`` kwarg.

Every function a host project calls to drive data pipeline / indicators /
backtest / live orchestration accepts ``paths: PathsConfig``. Explicit
injection is the only supported pattern.
"""
import inspect

import pytest


def _signature_accepts_paths(fn) -> bool:
    """Return True iff the callable has a 'paths' parameter."""
    try:
        sig = inspect.signature(fn)
    except (ValueError, TypeError):
        return False
    return "paths" in sig.parameters


def test_run_data_pipeline_accepts_paths():
    from echolon.data.backtest_data import run_data_pipeline
    assert _signature_accepts_paths(run_data_pipeline)


def test_run_live_data_update_accepts_paths():
    from echolon.data.live_data import run_live_data_update
    assert _signature_accepts_paths(run_live_data_update)


def test_run_indicator_calculation_accepts_paths():
    from echolon.indicators.run import run_indicator_calculation
    assert _signature_accepts_paths(run_indicator_calculation)


def test_run_backtest_accepts_paths():
    from echolon.backtest.runner import run_backtest
    assert _signature_accepts_paths(run_backtest)


def test_run_debug_backtest_accepts_paths():
    from echolon.backtest.runner import run_debug_backtest
    assert _signature_accepts_paths(run_debug_backtest)


def test_run_best_trial_accepts_paths():
    from echolon.backtest.runner import run_best_trial
    assert _signature_accepts_paths(run_best_trial)


def test_wfa_runner_init_accepts_paths():
    from echolon.backtest.wfa.runner import WFARunner
    assert _signature_accepts_paths(WFARunner.__init__)


def test_optuna_optimizer_init_accepts_paths():
    from echolon.backtest.optimization.optuna_study import OptunaOptimizer
    assert _signature_accepts_paths(OptunaOptimizer.__init__)


# Regime classifier optimizers are not part of echolon's public API. Host
# code registers its own via ``register_regime_optimizer(...)``; the
# optimize() entry point conforms to whatever signature that host picks.
#
# MarketFactory.create() takes explicit market/instrument/frequency values —
# host apps load their own session state. No ``paths=`` surface to test here.
