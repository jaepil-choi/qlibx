"""Parallel optimization workers use spawn plus explicit shared-data init."""
from __future__ import annotations

import inspect
import pickle
from concurrent.futures import TimeoutError as FuturesTimeoutError
from types import SimpleNamespace

import pytest


def test_parallel_optimizer_uses_spawn_with_shared_data_initializer():
    from echolon.backtest.optimization.optuna_study import OptunaOptimizer

    source = inspect.getsource(OptunaOptimizer._run_parallel)
    assert 'multiprocessing.get_context("spawn")' in source
    assert "initializer=_initialize_optimization_worker" in source
    assert "initargs=(shared_data,)" in source
    assert 'multiprocessing.get_context("fork")' not in source


def test_spawn_shared_data_payload_is_picklable_with_context_lambdas():
    from echolon.backtest.optimization.optuna_study import _spawn_shared_data_payload
    from echolon.config.markets.factory import MarketFactory
    from echolon.engine.factory import EngineFactory

    ctx = MarketFactory.create(
        market="SHFE",
        instrument="al",
        frequency="interday",
        bar_size="1d",
    )
    adapter = EngineFactory.create_market_adapter(ctx=ctx)

    payload = _spawn_shared_data_payload({
        "ctx": ctx,
        "market_adapter": adapter,
        "indicators": None,
        "indicator_metadata": {},
        "segmentation_data": None,
        "indicators_dir": "/tmp/indicators/aluminum",
        "indicators_backtest_dir": "/tmp/indicators",
        "strategy_code_dir": "/tmp/code",
        "market_data_dir": "/tmp/market_data",
        "optimization_config": None,
    })

    pickle.dumps(payload)
    assert payload["ctx"] is None
    assert payload["market_adapter"] is None
    assert payload["ctx_spec"]["instrument"] == "al"


def test_parallel_batch_watchdog_raises_and_cancels_outstanding_future(monkeypatch):
    import echolon.backtest.optimization.optuna_study as optuna_mod
    from echolon.backtest.optimization.optuna_study import OptunaOptimizer

    class _Future:
        cancelled = False

        def cancel(self):
            self.cancelled = True

    future = _Future()

    class _Executor:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def submit(self, *args):
            return future

    def _as_completed(futures, timeout=None):
        assert timeout == 0.01
        raise FuturesTimeoutError("hung")

    monkeypatch.setattr(optuna_mod, "ProcessPoolExecutor", _Executor)
    monkeypatch.setattr(optuna_mod, "as_completed", _as_completed)
    monkeypatch.setattr(optuna_mod, "_spawn_shared_data_payload", lambda shared: {})

    optimizer = OptunaOptimizer.__new__(OptunaOptimizer)
    optimizer.n_trials = 1
    optimizer.timeout = 0.01
    optimizer.search_space_fn = lambda trial: {}
    optimizer.optimization_target = "sharpe_ratio"
    optimizer._get_optimal_worker_configuration = lambda: {"max_workers": 1}

    study = SimpleNamespace(
        ask=lambda: SimpleNamespace(number=0),
        tell=lambda *args, **kwargs: None,
    )

    with pytest.raises(TimeoutError, match="Optimization batch timed out"):
        optimizer._run_parallel(study)

    assert future.cancelled is True


def test_first_trial_precondition_failure_raises_liveness_error(monkeypatch):
    import echolon.backtest.optimization.optuna_study as optuna_mod
    from echolon.backtest.optimization.optuna_study import OptunaOptimizer

    class _Future:
        def result(self):
            return {
                "success": False,
                "failure": {
                    "error_type": "PreconditionError",
                    "error_code": None,
                    "message": "Shared data not initialized",
                    "traceback": "",
                    "context": {},
                    "trial_params": {},
                    "docs_url": None,
                },
                "critical_error": False,
            }

    future = _Future()

    class _Executor:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def submit(self, *args):
            return future

    monkeypatch.setattr(optuna_mod, "ProcessPoolExecutor", _Executor)
    monkeypatch.setattr(optuna_mod, "as_completed", lambda futures, timeout=None: list(futures))
    monkeypatch.setattr(optuna_mod, "_spawn_shared_data_payload", lambda shared: {})

    optimizer = OptunaOptimizer.__new__(OptunaOptimizer)
    optimizer.n_trials = 1
    optimizer.timeout = 1.0
    optimizer.search_space_fn = lambda trial: {}
    optimizer.optimization_target = "sharpe_ratio"
    optimizer._get_optimal_worker_configuration = lambda: {"max_workers": 1}
    optimizer._failure_groups = {}

    study = SimpleNamespace(
        ask=lambda: SimpleNamespace(number=0),
        tell=lambda *args, **kwargs: None,
    )

    with pytest.raises(RuntimeError, match="first trial liveness"):
        optimizer._run_parallel(study)


def test_first_trial_strategy_failure_does_not_raise_liveness_error(monkeypatch):
    import echolon.backtest.optimization.optuna_study as optuna_mod
    from echolon.backtest.optimization.optuna_study import OptunaOptimizer

    class _Future:
        def result(self):
            return {
                "success": False,
                "failure": {
                    "error_type": "ValueError",
                    "error_code": None,
                    "message": "bad parameter value",
                    "traceback": "",
                    "context": {},
                    "trial_params": {},
                    "docs_url": None,
                },
                "critical_error": False,
            }

    class _Executor:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def submit(self, *args):
            return _Future()

    told = []
    monkeypatch.setattr(optuna_mod, "ProcessPoolExecutor", _Executor)
    monkeypatch.setattr(optuna_mod, "as_completed", lambda futures, timeout=None: list(futures))
    monkeypatch.setattr(optuna_mod, "_spawn_shared_data_payload", lambda shared: {})

    optimizer = OptunaOptimizer.__new__(OptunaOptimizer)
    optimizer.n_trials = 1
    optimizer.timeout = 1.0
    optimizer.search_space_fn = lambda trial: {}
    optimizer.optimization_target = "sharpe_ratio"
    optimizer._get_optimal_worker_configuration = lambda: {"max_workers": 1}
    optimizer._failure_groups = {}

    study = SimpleNamespace(
        ask=lambda: SimpleNamespace(number=0),
        tell=lambda *args, **kwargs: told.append((args, kwargs)),
    )

    optimizer._run_parallel(study)

    assert told
