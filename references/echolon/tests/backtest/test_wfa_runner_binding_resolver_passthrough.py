"""Task #11 Stage 2 (c2): WFARunner gains a generic per-window binding-
resolver pass-through — the qorka-side per-window rebinding executor's ONLY
echolon-side seam.

Mirrors ``test_wfa_runner_selection_passthrough.py`` exactly:
- ``WFARunner.__init__(..., binding_resolver_fn=None)`` — stored verbatim,
  default None (mechanism only, never a rebinding policy).
- ``_resolve_window_param_overlay`` / ``_apply_binding_overlay`` (module-
  level, pure) carry the ENTIRE per-window overlay seam — extracted so it is
  directly unit-testable without driving the full Optuna/backtrader
  collaborator chain ``run()`` needs.
- A source-pin proves the seam is invoked BEFORE Step 2 (IS-optimization)
  and that both Step 2's search_space_fn and Step 3's default_params use the
  resolved (possibly-overlaid) values.

Echolon holds NO rebinding policy here: hysteresis/sign-guard/two-vintage-
confirmation/churn/IC-ranking all live in the qorka-side resolver
(``workflow.calibration.per_window_rebind``, out of scope for this repo).
"""
from __future__ import annotations

import inspect
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# __init__: stores the hook verbatim, default None
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


def test_init_default_binding_resolver_fn_is_none(tmp_path):
    runner = _make_runner(tmp_path)
    assert runner.binding_resolver_fn is None


def test_init_stores_custom_binding_resolver_fn(tmp_path):
    def resolver(window):
        return {"ranging_long_indicator": "willr"}

    runner = _make_runner(tmp_path, binding_resolver_fn=resolver)
    assert runner.binding_resolver_fn is resolver  # exact identity, not a copy/wrapper


# ---------------------------------------------------------------------------
# _apply_binding_overlay: generic recursive key-overlay
# ---------------------------------------------------------------------------

def _mk_window(window_id=3):
    return SimpleNamespace(window_id=window_id, is_start="2018-01-01",
                            is_end="2022-12-31", oos_start="2023-01-01",
                            oos_end="2023-12-31")


def test_apply_binding_overlay_empty_bindings_is_identity_noop():
    from echolon.backtest.wfa.runner import _apply_binding_overlay

    params = {"entry_params": {"aroonosc_period": 16}}
    assert _apply_binding_overlay(params, {}) is params
    assert _apply_binding_overlay(params, None) is params


def test_apply_binding_overlay_overrides_nested_key_by_name():
    from echolon.backtest.wfa.runner import _apply_binding_overlay

    params = {
        "entry_params": {"ranging_long_indicator": "aroonosc", "aroonosc_period": 16},
        "exit_params": {"exit_atr_period": 17},
    }
    out = _apply_binding_overlay(params, {"ranging_long_indicator": "willr"})

    assert out["entry_params"]["ranging_long_indicator"] == "willr"
    assert out["entry_params"]["aroonosc_period"] == 16  # untouched
    assert out["exit_params"]["exit_atr_period"] == 17  # untouched
    # Pure: original dict is not mutated.
    assert params["entry_params"]["ranging_long_indicator"] == "aroonosc"


def test_apply_binding_overlay_missing_key_is_noop_for_that_key():
    from echolon.backtest.wfa.runner import _apply_binding_overlay

    params = {"entry_params": {"aroonosc_period": 16}}
    out = _apply_binding_overlay(params, {"no_such_slot_indicator": "willr"})
    assert out == params


def test_apply_binding_overlay_can_set_a_none_value():
    """EMPTY slot -> None (honest absence — the host app's pathway-inert
    convention), not a fabricated fill."""
    from echolon.backtest.wfa.runner import _apply_binding_overlay

    params = {"entry_params": {"ranging_long_indicator": "aroonosc"}}
    out = _apply_binding_overlay(params, {"ranging_long_indicator": None})
    assert out["entry_params"]["ranging_long_indicator"] is None


# ---------------------------------------------------------------------------
# _resolve_window_param_overlay: the full per-window seam
# ---------------------------------------------------------------------------

def test_resolve_window_param_overlay_none_resolver_is_identity():
    from echolon.backtest.wfa.runner import _resolve_window_param_overlay

    def base_search_space_fn(trial):
        return {"entry_params": {}}

    base_default_params = {"entry_params": {"x": 1}}
    fn, params = _resolve_window_param_overlay(
        _mk_window(),
        binding_resolver_fn=None,
        base_search_space_fn=base_search_space_fn,
        base_default_params=base_default_params,
    )
    assert fn is base_search_space_fn
    assert params is base_default_params


def test_resolve_window_param_overlay_empty_mapping_is_identity():
    from echolon.backtest.wfa.runner import _resolve_window_param_overlay

    def base_search_space_fn(trial):
        return {"entry_params": {}}

    base_default_params = {"entry_params": {"x": 1}}
    fn, params = _resolve_window_param_overlay(
        _mk_window(),
        binding_resolver_fn=lambda window: {},
        base_search_space_fn=base_search_space_fn,
        base_default_params=base_default_params,
    )
    assert fn is base_search_space_fn
    assert params is base_default_params


def test_resolve_window_param_overlay_wraps_search_space_fn_and_overlays_defaults():
    from echolon.backtest.wfa.runner import _resolve_window_param_overlay

    seen_windows = []

    def resolver(window):
        seen_windows.append(window.window_id)
        return {"ranging_long_indicator": "willr"}

    def base_search_space_fn(trial):
        return {"entry_params": {"ranging_long_indicator": "aroonosc", "period": 16}}

    base_default_params = {"entry_params": {"ranging_long_indicator": "aroonosc"}}

    window = _mk_window(window_id=3)
    fn, params = _resolve_window_param_overlay(
        window,
        binding_resolver_fn=resolver,
        base_search_space_fn=base_search_space_fn,
        base_default_params=base_default_params,
    )

    # resolver is invoked with the WFAWindow itself (join key = window_id).
    assert seen_windows == [3]
    # default_params overlay happens immediately.
    assert params["entry_params"]["ranging_long_indicator"] == "willr"
    assert base_default_params["entry_params"]["ranging_long_indicator"] == "aroonosc"  # not mutated
    # search_space_fn is WRAPPED — calling it applies the SAME overlay to
    # whatever the base fn returns for a given trial.
    assert fn is not base_search_space_fn
    trial_params = fn(trial=object())
    assert trial_params["entry_params"]["ranging_long_indicator"] == "willr"
    assert trial_params["entry_params"]["period"] == 16  # untouched


# ---------------------------------------------------------------------------
# run(): invokes the seam BEFORE Step 2 IS-optimization, and Step 2/3 use the
# resolved values — source-pinned (see test_wfa_runner_selection_passthrough.py
# module docstring for why exercising run() end-to-end is disproportionate
# here: it requires mocking the entire Optuna/backtrader/market-data chain).
# ---------------------------------------------------------------------------

def test_run_resolves_window_overlay_before_optimizer_construction_source_pin():
    from echolon.backtest.wfa.runner import WFARunner

    source = inspect.getsource(WFARunner.run)
    resolve_idx = source.index("_resolve_window_param_overlay(")
    optimizer_idx = source.index("OptunaOptimizer(")
    build_selector_idx = source.index("self._build_selector(")

    assert resolve_idx < optimizer_idx, (
        "the binding overlay must be resolved BEFORE Step 2 constructs the "
        "OptunaOptimizer, so window k's IS-fit already sees window k's "
        "bindings (per-window-rebinding-blueprint.md c2)."
    )
    assert resolve_idx < build_selector_idx

    assert "search_space_fn=window_search_space_fn" in source
    assert "default_params=window_default_params" in source
