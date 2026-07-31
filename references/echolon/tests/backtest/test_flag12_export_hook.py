"""Tests for FLAG-1 (injectable selection hook) and FLAG-2 (per-trial returns export).

FLAG-2:
  - OptimizationMetrics.daily_returns field exists and pickles cleanly
  - _extract_metrics populates it from BacktestResults.analyzers['daily_returns']
  - run_optimization_trial IPC dict carries daily_returns

FLAG-1:
  - Default pin: same fixture CSV -> same trial + same selection_reason (no regression)
  - Override: toy callable provably flips the selected trial
"""
from __future__ import annotations

import json
import pickle
from pathlib import Path
from typing import Any, Mapping
from unittest.mock import MagicMock

import pandas as pd
import pytest

FIXTURE_CSV = Path(__file__).parent.parent / "fixtures" / "trial_selector_pin.csv"


# ---------------------------------------------------------------------------
# FLAG-2: OptimizationMetrics pickling (IPC safety)
# ---------------------------------------------------------------------------

class TestOptimizationMetricsPickling:
    def test_daily_returns_survives_pickle_roundtrip(self):
        from echolon.backtest.engine.optimization_runner import OptimizationMetrics

        dr = {"2020-01-02": 0.002, "2020-01-03": -0.001, "2020-01-06": 0.003}
        m = OptimizationMetrics(
            sharpe_ratio=1.5,
            max_drawdown_pct=-5.0,
            annual_return_pct=12.0,
            total_trades=50,
            daily_returns=dr,
        )
        # Safe: data is constructed in this test — no untrusted source.
        # Purpose: verify IPC safety; ProcessPoolExecutor sends OptimizationMetrics
        # dicts between worker and controller processes via pickle, so this field
        # must survive a round-trip.
        dumped = pickle.dumps(m)
        loaded = pickle.loads(dumped)

        assert loaded.daily_returns == dr
        assert loaded.sharpe_ratio == 1.5

    def test_daily_returns_none_by_default(self):
        from echolon.backtest.engine.optimization_runner import OptimizationMetrics

        m = OptimizationMetrics(
            sharpe_ratio=1.0,
            max_drawdown_pct=-3.0,
            annual_return_pct=8.0,
            total_trades=20,
        )
        assert m.daily_returns is None


# ---------------------------------------------------------------------------
# FLAG-2: _extract_metrics carries daily_returns
# ---------------------------------------------------------------------------

class TestExtractMetrics:
    def _make_results(self, daily_returns):
        results = MagicMock()
        results.sharpe_ratio = 1.2
        results.max_drawdown = 5.0
        results.total_trades = 30
        results.analyzers = {
            'average_annual_return_pct': 10.0,
            'daily_returns': daily_returns,
        }
        return results

    def test_daily_returns_carried_from_analyzers(self):
        from echolon.backtest.engine.optimization_runner import OptimizationRunner

        dr = {"2021-01-04": 0.001, "2021-01-05": -0.0005}
        metrics = OptimizationRunner._extract_metrics(self._make_results(dr))

        assert metrics.success is True
        assert metrics.daily_returns == dr

    def test_empty_daily_returns_yields_none(self):
        from echolon.backtest.engine.optimization_runner import OptimizationRunner

        metrics = OptimizationRunner._extract_metrics(self._make_results({}))
        # empty dict -> coerced to None by `or None`
        assert metrics.daily_returns is None

    def test_absent_daily_returns_yields_none(self):
        from echolon.backtest.engine.optimization_runner import OptimizationRunner

        results = MagicMock()
        results.sharpe_ratio = 1.0
        results.max_drawdown = 4.0
        results.total_trades = 10
        results.analyzers = {'average_annual_return_pct': 8.0}  # no daily_returns key
        metrics = OptimizationRunner._extract_metrics(results)

        assert metrics.daily_returns is None


# ---------------------------------------------------------------------------
# FLAG-1: TrialSelector pin + override
# ---------------------------------------------------------------------------

class TestTrialSelectorSelectionHook:
    """Pin and flip tests for the injectable selection_score_fn."""

    def _make_selector(self, tmp_path, score_fn=None, per_trial_returns=None):
        from echolon.backtest.optimization.select_best_trial import TrialSelector

        return TrialSelector(
            trial_data_path=str(FIXTURE_CSV),
            output_dir=str(tmp_path / "output"),
            max_drawdown_threshold=15.0,
            strategy_code_dir=str(tmp_path / "code"),
            selection_score_fn=score_fn,
            per_trial_returns=per_trial_returns,
        )

    def test_default_pin_same_trial_and_reason(self, tmp_path):
        """Default (None) -> same selected trial + same selection_reason string."""
        sel = self._make_selector(tmp_path)
        result = sel.select()

        assert result is not None
        # Trial 2 wins: highest risk_adjusted_return (18.0/1.08 ~= 16.67) in cluster 0
        assert result['trial_number'] == 2
        assert result['selection_reason'] == 'Highest risk-adjusted return from most robust cluster'

    def test_override_flips_to_different_trial(self, tmp_path):
        """Toy callable using sharpe_ratio selects trial 3 instead of trial 2."""
        def score_by_sharpe(row: pd.Series, ctx: Mapping[str, Any]) -> float:
            return float(row['sharpe_ratio'])

        sel = self._make_selector(tmp_path, score_fn=score_by_sharpe)
        result = sel.select()

        assert result is not None
        # Trial 3 wins: highest sharpe_ratio (3.0) in cluster 0
        assert result['trial_number'] == 3
        assert result['trial_number'] != 2  # provably different from default
        assert result['selection_reason'] == 'Custom score from most robust cluster'

    def test_override_context_is_passed(self, tmp_path):
        """Callable receives per_trial_returns as second arg."""
        received_ctx = {}

        def capture_ctx(row: pd.Series, ctx: Mapping[str, Any]) -> float:
            received_ctx.update(ctx)
            return float(row['sharpe_ratio'])

        dummy_returns = {3: {"2021-01-04": 0.002}}
        sel = self._make_selector(tmp_path, score_fn=capture_ctx, per_trial_returns=dummy_returns)
        sel.select()

        assert received_ctx == dummy_returns


# ---------------------------------------------------------------------------
# FLAG-2: save_study_results writes per_trial_returns.json
# ---------------------------------------------------------------------------

class TestSaveStudyResults:
    @staticmethod
    def _make_optimizer():
        """Minimal OptunaOptimizer — only save_study_results is exercised."""
        from echolon.backtest.optimization.optuna_study import OptunaOptimizer
        from echolon.config.optuna_config import OptunaConfig

        ctx = MagicMock()
        ctx.market_code = 'TEST'
        ctx.instrument_name = 'test'
        adapter = MagicMock()
        strategy_class = MagicMock()
        strategy_class.__name__ = 'TestStrategy'
        cfg = OptunaConfig(n_trials=3, target='sharpe_ratio')

        return OptunaOptimizer(
            ctx=ctx,
            market_adapter=adapter,
            strategy_class=strategy_class,
            search_space_fn=lambda t: {},
            optuna_config=cfg,
        )

    def test_per_trial_returns_json_written(self, tmp_path):
        """save_study_results writes per_trial_returns.json with correct shape."""
        import optuna

        optim = self._make_optimizer()

        # Inject synthetic per_trial_returns
        optim._per_trial_returns = {
            5: {"2021-01-04": 0.002, "2021-01-05": -0.001},
            7: {"2021-01-04": 0.003},
        }

        # Build a minimal mock study
        study = MagicMock()
        study.best_trial = None  # skip best_params save
        complete_trial = MagicMock()
        complete_trial.number = 5
        complete_trial.state = optuna.trial.TrialState.COMPLETE
        complete_trial2 = MagicMock()
        complete_trial2.number = 7
        complete_trial2.state = optuna.trial.TrialState.COMPLETE
        failed_trial = MagicMock()
        failed_trial.number = 9
        failed_trial.state = optuna.trial.TrialState.FAIL
        study.trials = [complete_trial, complete_trial2, failed_trial]

        out = str(tmp_path / "results")
        optim.save_study_results(study, out, save_trials_csv=False, save_best_params=False)

        ptr_path = tmp_path / "results" / "per_trial_returns.json"
        assert ptr_path.exists(), "per_trial_returns.json should be written"

        data = json.loads(ptr_path.read_text())
        assert 'per_trial_returns' in data
        assert '5' in data['per_trial_returns']
        assert '7' in data['per_trial_returns']
        assert data['per_trial_returns']['5']['2021-01-04'] == pytest.approx(0.002)
        assert 'skipped_trials' in data
        # Trial 5 and 7 are in per_trial_returns; no completed trials are skipped
        assert data['skipped_trials'] == []

    def test_no_returns_data_writes_no_file(self, tmp_path):
        """_per_trial_returns == {} → per_trial_returns.json is NOT written.

        Honest absence over an empty artifact: a study with no returns data
        must leave nothing behind that a consumer could mistake for data.
        """
        import optuna

        optim = self._make_optimizer()
        assert optim._per_trial_returns == {}  # fresh instance, nothing collected

        study = MagicMock()
        study.best_trial = None
        complete_trial = MagicMock()
        complete_trial.number = 0
        complete_trial.state = optuna.trial.TrialState.COMPLETE
        study.trials = [complete_trial]

        out = str(tmp_path / "results")
        optim.save_study_results(study, out, save_trials_csv=False, save_best_params=False)

        ptr_path = tmp_path / "results" / "per_trial_returns.json"
        assert not ptr_path.exists(), (
            "per_trial_returns.json must not be written when no returns were collected"
        )
