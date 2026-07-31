"""OptunaConfig.n_jobs controls sequential optimization mode."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock


def _optimizer(tmp_path, *, n_jobs, use_sequential=None):
    from echolon.backtest.optimization.optuna_study import OptunaOptimizer
    from echolon.config.paths_config import PathsConfig

    kwargs = {}
    if use_sequential is not None:
        kwargs["use_sequential"] = use_sequential

    return OptunaOptimizer(
        ctx=SimpleNamespace(instrument_name="aluminum"),
        market_adapter=MagicMock(),
        strategy_class=object,
        search_space_fn=lambda trial: {},
        optuna_config=SimpleNamespace(
            n_trials=1,
            target="sharpe_ratio",
            timeout=None,
            n_jobs=n_jobs,
        ),
        paths=PathsConfig(project_root=tmp_path),
        **kwargs,
    )


def test_n_jobs_one_defaults_to_sequential_mode(tmp_path):
    optimizer = _optimizer(tmp_path, n_jobs=1)
    assert optimizer.use_sequential is True


def test_n_jobs_above_one_defaults_to_parallel_mode(tmp_path):
    optimizer = _optimizer(tmp_path, n_jobs=4)
    assert optimizer.use_sequential is False


def test_explicit_use_sequential_overrides_n_jobs(tmp_path):
    optimizer = _optimizer(tmp_path, n_jobs=1, use_sequential=False)
    assert optimizer.use_sequential is False
