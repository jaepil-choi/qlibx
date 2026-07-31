"""Task ED: WFARunner gains a generic pass-through for TrialSelector's FLAG-1
injectable selection hook (``selection_score_fn`` + ``per_trial_returns``).

TrialSelector already ships the hook (FLAG-1, see test_flag12_export_hook.py);
WFARunner constructed one per window but never forwarded the hook, so
WFA-path callers had no way to reach it. This adds:

- ``WFARunner.__init__(..., selection_score_fn=None)`` — stored verbatim,
  default None (mechanism only, never a policy).
- ``WFARunner._build_selector(..., per_trial_returns=None)`` — forwards both
  ``self.selection_score_fn`` and the caller-supplied ``per_trial_returns``
  to the constructed TrialSelector.
- ``run()`` forwards the live per-window ``OptunaOptimizer._per_trial_returns``
  (in-memory; the optimizer instance is still in scope when the selector is
  built, so there is no need to reload the per_trial_returns.json
  ``save_study_results`` just wrote) — pinned via source inspection below
  since exercising it through ``run()`` end-to-end would require mocking the
  entire Optuna/backtrader/market-data collaborator chain (no existing test
  in this suite does that; see test_wfa_completeness.py and
  test_param_resolution.py::test_wfa_selector_writes_where_run_best_trial_reads
  for the established lighter-weight seam-testing pattern this file follows).
"""
from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping
from unittest.mock import MagicMock

import pytest

FIXTURE_CSV = Path(__file__).parent.parent / "fixtures" / "trial_selector_pin.csv"


# ---------------------------------------------------------------------------
# __init__: stores the hook verbatim
# ---------------------------------------------------------------------------

def _make_runner(tmp_path, **kwargs):
    from echolon.backtest.wfa.runner import WFARunner
    from echolon.config.paths_config import PathsConfig

    return WFARunner(
        ctx=MagicMock(),
        config=MagicMock(),
        optuna_config=MagicMock(),
        backtest_config=MagicMock(),
        paths=PathsConfig(project_root=tmp_path),
        **kwargs,
    )


def test_init_default_selection_score_fn_is_none(tmp_path):
    runner = _make_runner(tmp_path)
    assert runner.selection_score_fn is None


def test_init_stores_custom_selection_score_fn(tmp_path):
    def score_fn(row, ctx):
        return 0.0

    runner = _make_runner(tmp_path, selection_score_fn=score_fn)
    assert runner.selection_score_fn is score_fn  # exact identity, not a copy/wrapper


# ---------------------------------------------------------------------------
# _build_selector: forwards both kwargs to TrialSelector (kwargs pinned via a
# capturing fake, matching the existing bare-__new__ seam-testing pattern in
# tests/_internal/test_param_resolution.py::test_wfa_selector_writes_where_run_best_trial_reads)
# ---------------------------------------------------------------------------

def _bare_runner(tmp_path, selection_score_fn=None):
    from echolon.backtest.wfa.runner import WFARunner

    runner = WFARunner.__new__(WFARunner)  # bypass heavy __init__; test the seam
    runner._paths = SimpleNamespace(strategy_code_dir=tmp_path / "code")
    runner.config = SimpleNamespace(max_drawdown_threshold=15.0)
    runner.selection_score_fn = selection_score_fn
    return runner


class _CapturingTrialSelector:
    """Stand-in for TrialSelector that records constructor kwargs instead of
    touching disk / running clustering — isolates the pass-through wiring
    from TrialSelector's own (separately tested) behavior."""

    last_kwargs: dict = {}

    def __init__(self, **kwargs):
        type(self).last_kwargs = kwargs


def test_build_selector_default_forwards_none_pinned_kwargs(tmp_path, monkeypatch):
    """Default (no hook) -> selection_score_fn=None, per_trial_returns=None
    reach TrialSelector, and every other kwarg is unchanged from the
    pre-Task-ED call (byte-identical construction)."""
    monkeypatch.setattr(
        "echolon.backtest.optimization.select_best_trial.TrialSelector",
        _CapturingTrialSelector,
    )
    runner = _bare_runner(tmp_path, selection_score_fn=None)

    runner._build_selector(
        trials_csv_path=FIXTURE_CSV,
        window_dir=tmp_path / "window",
        default_params={"foo": 1},
        apply_shared_params_fn=None,
        param_classifications={"bar": "baz"},
        search_space_fn=None,
    )

    kwargs = _CapturingTrialSelector.last_kwargs
    assert kwargs["selection_score_fn"] is None
    assert kwargs["per_trial_returns"] is None
    # unrelated kwargs untouched by this change
    assert kwargs["trial_data_path"] == str(FIXTURE_CSV)
    assert kwargs["output_dir"] == str(tmp_path / "window")
    assert kwargs["max_drawdown_threshold"] == 15.0
    assert kwargs["default_params"] == {"foo": 1}
    assert kwargs["param_classifications"] == {"bar": "baz"}
    assert kwargs["strategy_code_dir"] == tmp_path / "code"


def test_build_selector_forwards_custom_hook_and_context(tmp_path, monkeypatch):
    """Hook + context supplied -> both reach TrialSelector unmodified."""
    monkeypatch.setattr(
        "echolon.backtest.optimization.select_best_trial.TrialSelector",
        _CapturingTrialSelector,
    )

    def score_fn(row: Any, ctx: Mapping[str, Any]) -> float:
        return float(row["sharpe_ratio"])

    dummy_returns = {3: {"2021-01-04": 0.002}}
    runner = _bare_runner(tmp_path, selection_score_fn=score_fn)

    runner._build_selector(
        trials_csv_path=FIXTURE_CSV,
        window_dir=tmp_path / "window",
        default_params={},
        apply_shared_params_fn=None,
        param_classifications=None,
        search_space_fn=None,
        per_trial_returns=dummy_returns,
    )

    kwargs = _CapturingTrialSelector.last_kwargs
    assert kwargs["selection_score_fn"] is score_fn
    assert kwargs["per_trial_returns"] == dummy_returns


# ---------------------------------------------------------------------------
# End-to-end through the REAL TrialSelector (no monkeypatch): proves the
# pass-through actually changes (or doesn't change) selection output, not
# just constructor kwargs. Mirrors FLAG-1's own pin/override pair in
# test_flag12_export_hook.py::TestTrialSelectorSelectionHook, reached this
# time via WFARunner._build_selector.
# ---------------------------------------------------------------------------

def test_build_selector_default_none_matches_flag1_baseline_e2e(tmp_path):
    runner = _bare_runner(tmp_path, selection_score_fn=None)
    selector = runner._build_selector(
        trials_csv_path=FIXTURE_CSV,
        window_dir=tmp_path / "window",
        default_params={},
        apply_shared_params_fn=None,
        param_classifications=None,
        search_space_fn=None,
    )
    result = selector.select()

    assert result is not None
    assert result["trial_number"] == 2
    assert result["selection_reason"] == "Highest risk-adjusted return from most robust cluster"


def test_build_selector_custom_hook_flips_trial_e2e(tmp_path):
    def score_by_sharpe(row: Any, ctx: Mapping[str, Any]) -> float:
        return float(row["sharpe_ratio"])

    runner = _bare_runner(tmp_path, selection_score_fn=score_by_sharpe)
    selector = runner._build_selector(
        trials_csv_path=FIXTURE_CSV,
        window_dir=tmp_path / "window",
        default_params={},
        apply_shared_params_fn=None,
        param_classifications=None,
        search_space_fn=None,
    )
    result = selector.select()

    assert result is not None
    assert result["trial_number"] == 3
    assert result["trial_number"] != 2  # provably different from the default path
    assert result["selection_reason"] == "Custom score from most robust cluster"


# ---------------------------------------------------------------------------
# run(): forwards the live per-window OptunaOptimizer._per_trial_returns.
# Source-pinned (see module docstring for why this seam isn't reachable
# without disproportionate end-to-end mocking).
# ---------------------------------------------------------------------------

def test_run_forwards_optimizer_per_trial_returns_source_pin():
    from echolon.backtest.wfa.runner import WFARunner

    source = inspect.getsource(WFARunner.run)
    assert "per_trial_returns=optimizer._per_trial_returns" in source
