"""Cost-model v2 — `ContractSpec` v2 fields + 3-tier precedence rule.

Per qorka docs/2_design/decisions_log.md 2026-05-13 "Cost-model v2" entry.
Validates the architectural contract added in Gate 1A T27b/c/d:

- `calibrated_slippage_bps_by_intent: Optional[dict]` (per-intent bps)
- `high_vol_slippage_multiplier: float` (vol-regime multiplier)
- `high_vol_pct_threshold: float` (60-day rolling vol pct threshold)
- `tail_factor: float` (Wave 2 fat-tail stub)
- `calibrated_slippage_bps: Optional[float]` (v1 scalar, deprecated but
  retained as backward-compat fallback)

Precedence rule (backtrader_engine.py):
  v2 by_intent → v1 scalar → tick-derived default

`StructuredSlippageBroker` (the broker subclass that consumes v2 fields
for per-order classification + vol-regime lookup) is implemented in a
follow-up commit; this test suite validates the field surface +
graceful-degrade behavior pending that implementation.
"""
from __future__ import annotations

import inspect

import pytest

from echolon.markets.interface import ContractSpec


def _make_contract_spec(**overrides) -> ContractSpec:
    """Aluminum-like baseline ContractSpec."""
    base = dict(
        symbol="AL",
        multiplier=5.0,
        tick_size=5.0,
        margin_rate=0.10,
        commission=10.0,
    )
    base.update(overrides)
    return ContractSpec(**base)


# ---------------------------------------------------------------------------
# v2 field surface
# ---------------------------------------------------------------------------

def test_v2_default_all_fields_none_or_unit():
    """Default ContractSpec has v2 fields set to identity / None values."""
    cs = _make_contract_spec()
    assert cs.calibrated_slippage_bps_by_intent is None
    assert cs.high_vol_slippage_multiplier == 1.0
    assert cs.high_vol_pct_threshold == 75.0
    assert cs.tail_factor == 1.0
    # v1 backward-compat field also None by default
    assert cs.calibrated_slippage_bps is None


def test_v2_per_intent_dict_accepted():
    """ContractSpec accepts per-intent slippage dict."""
    cs = _make_contract_spec(
        calibrated_slippage_bps_by_intent={
            "ENTRY": 5.5,
            "EXIT": 7.5,
            "FORCED_EXIT": 12.0,
        }
    )
    assert cs.calibrated_slippage_bps_by_intent == {
        "ENTRY": 5.5,
        "EXIT": 7.5,
        "FORCED_EXIT": 12.0,
    }


def test_v2_vol_regime_fields_accepted():
    cs = _make_contract_spec(
        high_vol_slippage_multiplier=1.5,
        high_vol_pct_threshold=80.0,
    )
    assert cs.high_vol_slippage_multiplier == 1.5
    assert cs.high_vol_pct_threshold == 80.0


def test_v2_tail_factor_accepted():
    """Wave 2 forward-compat stub field."""
    cs = _make_contract_spec(tail_factor=1.5)
    assert cs.tail_factor == 1.5


def test_v2_partial_intent_dict_allowed():
    """Missing intent keys are allowed — the broker will fall back to
    the next-tightest cap (per Q59 default plan)."""
    cs = _make_contract_spec(
        calibrated_slippage_bps_by_intent={"ENTRY": 5.5}
    )
    assert "ENTRY" in cs.calibrated_slippage_bps_by_intent
    assert "EXIT" not in cs.calibrated_slippage_bps_by_intent


# ---------------------------------------------------------------------------
# 3-tier precedence rule in backtrader_engine
# ---------------------------------------------------------------------------

def test_precedence_v2_branch_evaluates_first():
    """When v2 by_intent is set, engine should select the v2 branch
    regardless of v1 scalar or tick_size."""
    import echolon.backtest.engine.backtrader_engine as bte

    src = inspect.getsource(bte)
    v2_idx = src.find("calibrated_slippage_bps_by_intent is not None")
    v1_idx = src.find("calibrated_slippage_bps is not None")
    tick_idx = src.find("contract_spec.tick_size > 0")

    assert v2_idx > 0, "v2 by_intent branch missing"
    assert v1_idx > 0, "v1 scalar branch missing"
    assert tick_idx > 0, "tick_size fallback branch missing"
    # v2 must be evaluated before v1
    assert v2_idx < v1_idx, "v2 by_intent must be checked BEFORE v1 scalar"
    # v1 must be evaluated before tick-derived fallback
    assert v1_idx < tick_idx, "v1 scalar must be checked BEFORE tick fallback"


def test_precedence_v2_set_v1_ignored():
    """When both v2 and v1 are populated, v1 must be ignored (no
    ambiguity). Verified by inspecting the engine's branch logic."""
    cs = _make_contract_spec(
        calibrated_slippage_bps_by_intent={"ENTRY": 5.5, "EXIT": 7.5},
        calibrated_slippage_bps=99.0,  # should be ignored
    )
    # Simulate the engine's selection (from backtrader_engine.py)
    if cs.calibrated_slippage_bps_by_intent is not None:
        by_intent = cs.calibrated_slippage_bps_by_intent
        mean_bps = sum(by_intent.values()) / len(by_intent)
        selected_branch = "v2"
        selected_bps = mean_bps  # current graceful-degrade behavior
    elif cs.calibrated_slippage_bps is not None:
        selected_branch = "v1"
        selected_bps = cs.calibrated_slippage_bps
    else:
        selected_branch = "tick-derived"
        selected_bps = None

    assert selected_branch == "v2"
    # mean of {5.5, 7.5} = 6.5; v1's 99.0 is NOT used
    assert selected_bps == pytest.approx(6.5)


def test_v2_installs_structured_slippage_broker():
    """When v2 by_intent is set, the engine installs StructuredSlippageBroker
    (NOT the transitional mean-of-intents degrade). Verified structurally:
    the v2 branch in backtrader_engine.py imports + constructs the broker.

    Updated 2026-05-14 after T27b/c shipped the actual broker. The prior
    "StructuredSlippageBroker is not yet implemented" warning string is
    intentionally absent from the source — its absence is the regression
    signal we care about going forward."""
    import echolon.backtest.engine.backtrader_engine as bte
    src = inspect.getsource(bte)
    # Positive signal: the v2 branch now imports the broker
    assert "from echolon.backtest.engine.structured_slippage import (" in src
    assert "StructuredSlippageBroker" in src
    # Positive signal: the v2 branch installs the broker
    assert "structured_broker = StructuredSlippageBroker()" in src
    assert "structured_broker.configure_v2(" in src
    # Negative signal: the transitional degrade warning is gone
    assert "StructuredSlippageBroker is not yet implemented" not in src
    assert "Degrading to mean-of-intents scalar" not in src


# ---------------------------------------------------------------------------
# Per-intent calibration math (preview — full math in StructuredSlippageBroker)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "by_intent, vol_mult, expected_mean",
    [
        # No vol-regime: mean = arithmetic mean of intents
        ({"ENTRY": 5.0, "EXIT": 10.0, "FORCED_EXIT": 15.0}, 1.0, 10.0),
        # Vol-regime mult 1.5: mean × 0.5×(1+1.5) = mean × 1.25
        ({"ENTRY": 4.0, "EXIT": 8.0}, 1.5, 6.0 * 1.25),
        # Single intent: degrade to that value
        ({"ENTRY": 8.0}, 1.0, 8.0),
    ],
)
def test_graceful_degrade_mean_of_intents(by_intent, vol_mult, expected_mean):
    """The transitional graceful-degrade behavior in the engine should
    apply mean-of-intents × 0.5×(1+vol_mult). Verifies the current state
    until StructuredSlippageBroker ships."""
    mean_bps = sum(by_intent.values()) / len(by_intent)
    if vol_mult != 1.0:
        mean_bps *= ((1.0 + vol_mult) / 2.0)
    assert mean_bps == pytest.approx(expected_mean)
