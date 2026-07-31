"""B3 (RCA 2026-06-21): an INCOMPLETE WFA must hard-signal, not silently
proceed to the final full-period backtest with the last-completed window's
STALE params + a DRS scored on a shrunken window set (No-Misleading-Fallback).

`WFARunner.run` previously raised WFA-001 only when ALL windows produced zero
valid trials; when SOME (but not all) windows' TrialSelector found no robust
trial, those windows were silently skipped (Step 3 `continue`) and the runner
proceeded — Step 7's final backtest then reused whichever earlier window last
wrote selected_robust_trial.json, over the full period, and the gates scored on
the shrunken completed-window set. `_assert_wfa_complete` closes that middle
case with WFA-002.
"""
from types import SimpleNamespace

import pytest

from echolon.backtest.wfa.runner import _assert_wfa_complete
from echolon.errors import EchelonError


def _win(window_id, completed):
    return SimpleNamespace(
        window_id=window_id,
        oos_results={"sharpe_ratio_annual": 1.0} if completed else None,
    )


def test_all_windows_completed_returns_completed_list():
    windows = [_win(i, True) for i in range(1, 6)]
    completed = _assert_wfa_complete(windows, wfa_dir="/tmp/wfa")
    assert [w.window_id for w in completed] == [1, 2, 3, 4, 5]


def test_partial_completion_raises_wfa002_naming_failed_windows():
    # windows 1-2 completed; windows 3/4/5 produced no robust trial (the v17.4 case)
    windows = [
        _win(1, True), _win(2, True),
        _win(3, False), _win(4, False), _win(5, False),
    ]
    with pytest.raises(EchelonError) as exc:
        _assert_wfa_complete(windows, wfa_dir="/tmp/wfa")
    err = exc.value
    assert err.code == "WFA-002"
    assert err.context["n_completed"] == 2
    assert err.context["n_total"] == 5
    assert err.context["failed_windows"] == [3, 4, 5]


def test_zero_completion_still_raises_wfa001():
    windows = [_win(i, False) for i in range(1, 6)]
    with pytest.raises(EchelonError) as exc:
        _assert_wfa_complete(windows, wfa_dir="/tmp/wfa")
    assert exc.value.code == "WFA-001"
