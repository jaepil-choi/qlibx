"""Portfolio phase 0: two slots on the same (instrument, bar_size) share one indicator compute.

Asserts the wiring symbolically + via unit-level exercise of merge_indicator_lists.
A full end-to-end spawn of PortfolioTradingRunner requires QMT + market data and
belongs in an integration suite, not here.
"""
from pathlib import Path

from echolon.indicators.utils.merge_indicators import merge_indicator_lists

_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_phase0_portfolio_source_groups_by_instrument_and_barsize():
    """The phase 0 implementation must loop over get_slots_by_instrument_and_barsize,
    not per-slot, so two slots on the same instrument share one compute.

    Phase 0 was extracted to phase0_pipeline.py in the 2026-05-08 refactor.
    """
    src = (_REPO_ROOT / "echolon" / "live" / "orchestrator" / "phase0_pipeline.py").read_text(encoding="utf-8")
    assert "get_slots_by_instrument_and_barsize()" in src, (
        "phase0_pipeline.py must group slots by (instrument, bar_size)"
    )
    assert "merge_indicator_lists" in src, (
        "phase0_pipeline.py must call merge_indicator_lists over per-group slot configs"
    )
    # No per-slot output dir in phase 0 anymore — output goes to the group dir
    assert "group_dir" in src


def test_phase0_portfolio_output_dir_is_group_dir():
    """Shared output dir format: {instrument_code}_{bar_size}/"""
    src = (_REPO_ROOT / "echolon" / "live" / "orchestrator" / "phase0_pipeline.py").read_text(encoding="utf-8")
    assert 'f"{instrument_code}_{bar_size}"' in src


def test_trading_slot_resolves_group_dir_fallback():
    """trading_slot._get_indicators_path falls back to {instrument_code}_{bar_size}/ when
    the per-slot dir is absent — this is how slots find the merged output."""
    src = (_REPO_ROOT / "echolon" / "live" / "slot" / "trading_slot.py").read_text(encoding="utf-8")
    assert "{sc.instrument_code}_{sc.bar_size}" in src


def test_merge_two_slots_on_same_instrument_different_ranges():
    """User's scenario: slot A asks RSI [10,20]; slot B asks RSI [15,30].
    After merge, one compute covers [10,30] — both slots served from one CSV."""
    slot_a_list = {"rsi": {"timeperiod": [10, 20]}, "atr": {"timeperiod": 14}}
    slot_b_list = {"rsi": {"timeperiod": [15, 30]}, "obv": {}}

    merged = merge_indicator_lists([slot_a_list, slot_b_list])

    # RSI range widens to cover both slots
    assert merged["rsi"]["timeperiod"] == [10, 30]
    # Per-slot-unique indicators are present
    assert "atr" in merged
    assert "obv" in merged
    assert merged["atr"]["timeperiod"] == 14
    assert merged["obv"] == {}
