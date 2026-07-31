"""Unit tests for CapitalSlot — invariants of slot-isolated capital tracking."""
import pytest

from echolon.live.slot.capital_slot import CapitalSlot


def test_capital_slot_initial_equity_equals_initial_capital():
    cs = CapitalSlot(slot_id="al_s1", initial_capital=100000.0)
    assert cs.equity == 100000.0
    assert cs.peak_equity == 100000.0  # __post_init__ sets peak == initial


def test_capital_slot_realized_pnl_accumulates():
    cs = CapitalSlot(slot_id="al_s1", initial_capital=100000.0)
    cs.record_trade(realized_pnl=500.0)
    cs.record_trade(realized_pnl=-200.0)
    cs.record_trade(realized_pnl=1000.0)
    assert cs.realized_pnl == 1300.0
    assert cs.equity == 101300.0


def test_capital_slot_peak_only_increases():
    """Peak equity must be monotonic across record_trade calls; transient
    losses must NOT reset the peak."""
    cs = CapitalSlot(slot_id="al_s1", initial_capital=100000.0)
    cs.record_trade(realized_pnl=2000.0)
    assert cs.peak_equity == 102000.0
    cs.record_trade(realized_pnl=-3000.0)  # transient loss
    assert cs.peak_equity == 102000.0  # unchanged
    cs.record_trade(realized_pnl=-500.0)
    assert cs.peak_equity == 102000.0


def test_capital_slot_drawdown_pct_from_peak():
    cs = CapitalSlot(slot_id="al_s1", initial_capital=100000.0)
    cs.record_trade(realized_pnl=10000.0)  # peak now 110k
    cs.record_trade(realized_pnl=-5500.0)  # equity now 104.5k
    # drawdown = (110k - 104.5k) / 110k = 5%
    assert abs(cs.drawdown_pct - 5.0) < 0.01


def test_capital_slot_at_peak_zero_drawdown():
    cs = CapitalSlot(slot_id="al_s1", initial_capital=100000.0)
    cs.record_trade(realized_pnl=5000.0)
    assert cs.drawdown_pct == 0.0


def test_capital_slot_save_load_roundtrip():
    cs = CapitalSlot(slot_id="al_s1", initial_capital=100000.0)
    cs.record_trade(realized_pnl=1500.0)
    cs.prev_position_size = 2.0
    cs.prev_avg_price = 24600.0
    data = cs.save_dict()
    cs2 = CapitalSlot.from_dict(data)
    assert cs2.slot_id == cs.slot_id
    assert cs2.initial_capital == cs.initial_capital
    assert cs2.realized_pnl == cs.realized_pnl
    assert cs2.peak_equity == cs.peak_equity
    assert cs2.prev_position_size == cs.prev_position_size
    assert cs2.prev_avg_price == cs.prev_avg_price


def test_capital_slot_available_cash_excludes_margin():
    cs = CapitalSlot(slot_id="al_s1", initial_capital=100000.0)
    cs.margin_used = 30000.0
    assert cs.available_cash == 70000.0
