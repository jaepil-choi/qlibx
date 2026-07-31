"""Verify OptunaOptimizer signature accepts OptunaConfig."""
import inspect
from echolon.backtest.optimization.optuna_study import OptunaOptimizer


def test_optimizer_accepts_optuna_config():
    sig = inspect.signature(OptunaOptimizer.__init__)
    assert "optuna_config" in sig.parameters
