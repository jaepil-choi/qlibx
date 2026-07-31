"""Cost-model v2 — per-intent + vol-regime slippage primitives.

Per qorka Wave 1A plan T27b/c. Validates the OrderIntent classifier +
compute_slippage_bps lookup that StructuredSlippageBroker uses
internally. The broker's backtrader-side fill-path integration is
exercised end-to-end via the engine's existing v2 path test; this
suite isolates the pure-Python primitives so a regression in the
classification logic surfaces independently of broker plumbing.
"""
from __future__ import annotations

import pytest

from echolon.backtest.engine.structured_slippage import (
    OrderIntent,
    StructuredSlippageBroker,
    classify_order_intent,
    compute_slippage_bps,
)


# ---------------------------------------------------------------------------
# OrderIntent — closed enum
# ---------------------------------------------------------------------------

def test_order_intent_enum_has_four_canonical_classes():
    assert {m.value for m in OrderIntent} == {
        "entry", "exit", "forced_exit", "other"
    }


# ---------------------------------------------------------------------------
# classify_order_intent — position-state-based classification
# ---------------------------------------------------------------------------

def test_buy_from_flat_is_entry():
    assert classify_order_intent(order_size=10, position_before=0) == OrderIntent.ENTRY


def test_sell_from_flat_is_entry():
    """Short opens are also ENTRY — opening trades regardless of direction."""
    assert classify_order_intent(order_size=-10, position_before=0) == OrderIntent.ENTRY


def test_buy_to_zero_from_short_is_exit():
    """Short position (-10) + buy 10 → flat. Closing trade → EXIT."""
    assert classify_order_intent(order_size=10, position_before=-10) == OrderIntent.EXIT


def test_sell_to_zero_from_long_is_exit():
    """Long position (10) + sell 10 → flat. Closing trade → EXIT."""
    assert classify_order_intent(order_size=-10, position_before=10) == OrderIntent.EXIT


def test_full_close_with_forced_flag_is_forced_exit():
    """Same close transition but with is_forced_exit=True → FORCED_EXIT."""
    assert classify_order_intent(
        order_size=-10, position_before=10, is_forced_exit=True
    ) == OrderIntent.FORCED_EXIT


def test_scale_in_same_direction_is_other():
    """Long 10 + buy 5 → long 15. Position increasing → OTHER (not ENTRY)."""
    assert classify_order_intent(order_size=5, position_before=10) == OrderIntent.OTHER


def test_partial_close_is_other():
    """Long 10 + sell 5 → long 5. Position reduced but not closed → OTHER."""
    assert classify_order_intent(order_size=-5, position_before=10) == OrderIntent.OTHER


def test_zero_size_order_is_other():
    """Defensive: a 0-size order shouldn't reach this function but if it does,
    return OTHER rather than raising — broker downstream rejects 0-size."""
    assert classify_order_intent(order_size=0, position_before=10) == OrderIntent.OTHER


def test_forced_exit_only_fires_on_actual_close():
    """is_forced_exit=True on a scale-in shouldn't yield FORCED_EXIT —
    the flag only matters for closing trades. Result is OTHER per the
    scale-in rule."""
    assert classify_order_intent(
        order_size=5, position_before=10, is_forced_exit=True
    ) == OrderIntent.OTHER


def test_forced_exit_on_open_yields_entry():
    """is_forced_exit=True on an opening trade — opening can't be a
    forced-exit. Defensive: return ENTRY rather than FORCED_EXIT."""
    assert classify_order_intent(
        order_size=10, position_before=0, is_forced_exit=True
    ) == OrderIntent.ENTRY


# ---------------------------------------------------------------------------
# compute_slippage_bps — three intent classes produce three distinct fills
# ---------------------------------------------------------------------------

@pytest.fixture
def calibrated_by_intent():
    """Representative SHFE calibration: forced-exit costs ~2× entry."""
    return {
        "entry": 3.0,
        "exit": 3.5,
        "forced_exit": 6.5,
        "other": 4.0,
    }


def test_three_intents_produce_three_distinct_bps(calibrated_by_intent):
    """Acceptance criterion (T27b): 3 intent classes → 3 distinct fill bps."""
    entry_bps = compute_slippage_bps(OrderIntent.ENTRY, calibrated_by_intent)
    exit_bps = compute_slippage_bps(OrderIntent.EXIT, calibrated_by_intent)
    forced_bps = compute_slippage_bps(OrderIntent.FORCED_EXIT, calibrated_by_intent)
    assert len({entry_bps, exit_bps, forced_bps}) == 3
    assert entry_bps == 3.0
    assert exit_bps == 3.5
    assert forced_bps == 6.5


def test_missing_intent_falls_back_to_entry(calibrated_by_intent):
    """If the dict is missing an intent, fall back to ENTRY bps rather
    than crashing the broker."""
    incomplete = {"entry": 3.0, "exit": 3.5}  # forced_exit + other absent
    forced_bps = compute_slippage_bps(OrderIntent.FORCED_EXIT, incomplete)
    assert forced_bps == 3.0  # = entry fallback


def test_missing_entry_too_falls_back_to_mean(calibrated_by_intent):
    """If both intent AND entry are absent, fall back to mean of present
    values — graceful degrade."""
    only_exit_and_other = {"exit": 4.0, "other": 6.0}
    result = compute_slippage_bps(OrderIntent.FORCED_EXIT, only_exit_and_other)
    assert result == 5.0  # = (4 + 6) / 2


def test_empty_by_intent_returns_zero():
    """Defensive: empty dict → 0 (broker upstream guards against this)."""
    assert compute_slippage_bps(OrderIntent.ENTRY, {}) == 0.0


# ---------------------------------------------------------------------------
# Vol-regime multiplier (T27c)
# ---------------------------------------------------------------------------

def test_high_vol_multiplier_applies_above_threshold(calibrated_by_intent):
    """vol_pct > threshold AND multiplier != 1 → bps × multiplier."""
    high_vol_bps = compute_slippage_bps(
        OrderIntent.ENTRY,
        calibrated_by_intent,
        vol_pct=85.0,
        vol_threshold=75.0,
        high_vol_multiplier=2.0,
    )
    assert high_vol_bps == 6.0  # 3.0 × 2.0


def test_high_vol_multiplier_skipped_at_or_below_threshold(calibrated_by_intent):
    """vol_pct == threshold (75.0) does NOT trigger multiplier (strict >)."""
    boundary_bps = compute_slippage_bps(
        OrderIntent.ENTRY,
        calibrated_by_intent,
        vol_pct=75.0,
        vol_threshold=75.0,
        high_vol_multiplier=2.0,
    )
    assert boundary_bps == 3.0


def test_high_vol_multiplier_skipped_below_threshold(calibrated_by_intent):
    below_bps = compute_slippage_bps(
        OrderIntent.ENTRY,
        calibrated_by_intent,
        vol_pct=50.0,
        vol_threshold=75.0,
        high_vol_multiplier=2.0,
    )
    assert below_bps == 3.0


def test_multiplier_one_is_no_op_even_in_high_vol(calibrated_by_intent):
    """high_vol_multiplier=1.0 is a documented no-op — vol-regime layer
    inactive (default behavior)."""
    no_op_bps = compute_slippage_bps(
        OrderIntent.ENTRY,
        calibrated_by_intent,
        vol_pct=95.0,
        high_vol_multiplier=1.0,
    )
    assert no_op_bps == 3.0


def test_vol_pct_none_skips_vol_regime_check(calibrated_by_intent):
    """vol_pct=None means vol-regime check is skipped entirely (e.g.,
    during 60-day warmup). Should return base bps."""
    bps = compute_slippage_bps(
        OrderIntent.FORCED_EXIT,
        calibrated_by_intent,
        vol_pct=None,
        high_vol_multiplier=2.0,
    )
    assert bps == 6.5


# ---------------------------------------------------------------------------
# StructuredSlippageBroker — construction + configuration
# ---------------------------------------------------------------------------

def test_broker_constructs_with_defaults():
    """Default-constructed broker has empty calibration + no-op vol mult."""
    broker = StructuredSlippageBroker()
    assert broker._by_intent == {}
    assert broker._high_vol_multiplier == 1.0


def test_broker_configure_v2_stores_calibration(calibrated_by_intent):
    broker = StructuredSlippageBroker()
    broker.configure_v2(
        by_intent=calibrated_by_intent,
        high_vol_threshold=80.0,
        high_vol_multiplier=1.5,
    )
    assert broker._by_intent == calibrated_by_intent
    assert broker._high_vol_threshold == 80.0
    assert broker._high_vol_multiplier == 1.5


def test_broker_mark_next_order_forced_is_one_shot():
    """The forced-exit marker fires once and resets, so a stale flag can't
    mis-classify a later non-forced trade."""
    broker = StructuredSlippageBroker()
    broker.configure_v2(by_intent={"entry": 3.0, "forced_exit": 6.5})

    broker.mark_next_order_forced()
    assert broker._pending_forced_exit is True

    # Construct a synthetic order to consume the flag
    class _FakeData:
        pass
    class _FakeOrder:
        size = -10
        data = _FakeData()

    # Pre-fill position by stubbing the broker's getposition
    class _FakePosition:
        size = 10
    broker.getposition = lambda d: _FakePosition()

    pct1 = broker._resolve_slippage_pct_for_order(_FakeOrder())
    # FORCED_EXIT bps = 6.5 → 0.00065 pct
    assert pct1 == pytest.approx(0.00065)

    # Second resolve should now be EXIT (forced flag consumed)
    pct2 = broker._resolve_slippage_pct_for_order(_FakeOrder())
    # EXIT not in calibration → falls back to entry (3.0 bps) per spec
    assert pct2 == pytest.approx(0.00030)


def test_broker_vol_pct_provider_failure_does_not_crash():
    """If the vol-pct provider raises, the broker degrades to no
    vol-regime check rather than propagating the exception. A crashing
    provider mid-backtest would otherwise tank the entire run."""
    broker = StructuredSlippageBroker()
    broker.configure_v2(
        by_intent={"entry": 3.0},
        high_vol_multiplier=2.0,
    )
    broker.set_vol_pct_provider(lambda: 1 / 0)  # type: ignore[arg-type]

    class _FakePosition:
        size = 0
    class _FakeData:
        pass
    class _FakeOrder:
        size = 10
        data = _FakeData()
    broker.getposition = lambda d: _FakePosition()

    # Should not raise; returns base bps (vol-regime skipped)
    pct = broker._resolve_slippage_pct_for_order(_FakeOrder())
    assert pct == pytest.approx(0.00030)
