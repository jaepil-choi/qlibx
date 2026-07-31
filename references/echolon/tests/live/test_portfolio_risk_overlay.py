"""Unit tests for PortfolioRiskOverlay — peak tracking and drawdown breach."""
import sys
from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

from echolon.live.slot.capital_slot import CapitalSlot
from echolon.live.slot.risk_overlay import PortfolioRiskOverlay

# Stub xtquant before importing the real router; CI/dev machines need not
# have the Windows QMT package installed for this dry-run safety test.
for _mod_name in (
    "xtquant", "xtquant.xtconstant", "xtquant.xtdata",
    "xtquant.xttrader", "xtquant.xttype",
):
    sys.modules.setdefault(_mod_name, MagicMock())

from echolon.live.platforms.miniqmt.order_router import (  # noqa: E402
    OrderRouter,
    OrderRouterTripped,
)


@dataclass
class _FakeSlot:
    """Minimal stand-in for TradingSlot — only what risk_overlay touches."""
    slot_id: str
    capital_slot: CapitalSlot


def _make_slot(slot_id: str, equity: float, initial: float = 100000.0) -> _FakeSlot:
    """Build a slot whose .capital_slot.equity matches `equity`.

    CapitalSlot.equity = initial_capital + realized_pnl + unrealized_pnl,
    so we set realized_pnl = (equity - initial). We do NOT call
    record_trade() because that would also update peak_equity, and
    risk_overlay only consumes capital_slot.equity (a property), not
    capital_slot.peak_equity.
    """
    cs = CapitalSlot(slot_id=slot_id, initial_capital=initial)
    cs.realized_pnl = equity - initial
    return _FakeSlot(slot_id=slot_id, capital_slot=cs)


def test_overlay_peak_equity_starts_at_zero(tmp_path):
    ov = PortfolioRiskOverlay(max_portfolio_drawdown_pct=15.0,
                              deploy_data_dir=str(tmp_path))
    assert ov.peak_equity == 0.0


def test_overlay_peak_equity_increases_monotonically(tmp_path):
    ov = PortfolioRiskOverlay(max_portfolio_drawdown_pct=15.0,
                              deploy_data_dir=str(tmp_path))
    slots = [_make_slot("al", 100000), _make_slot("cu", 100000), _make_slot("zn", 100000)]
    ov.check_portfolio_drawdown(slots)
    assert ov.peak_equity == 300000.0
    # Push higher
    slots = [_make_slot("al", 110000), _make_slot("cu", 100000), _make_slot("zn", 100000)]
    ov.check_portfolio_drawdown(slots)
    assert ov.peak_equity == 310000.0
    # Now drop — peak must NOT decrease
    slots = [_make_slot("al", 80000), _make_slot("cu", 100000), _make_slot("zn", 100000)]
    ov.check_portfolio_drawdown(slots)
    assert ov.peak_equity == 310000.0


def test_overlay_drawdown_breach_at_threshold(tmp_path):
    ov = PortfolioRiskOverlay(max_portfolio_drawdown_pct=15.0,
                              deploy_data_dir=str(tmp_path))
    slots = [_make_slot("al", 100000), _make_slot("cu", 100000), _make_slot("zn", 100000)]
    ov.check_portfolio_drawdown(slots)  # peak = 300k
    # Drop 16%: equity = 252k -> drawdown = 16% > 15% -> breach
    slots = [_make_slot("al", 84000), _make_slot("cu", 84000), _make_slot("zn", 84000)]
    ok = ov.check_portfolio_drawdown(slots)
    assert ok is False  # breached


def test_overlay_drawdown_ok_below_threshold(tmp_path):
    ov = PortfolioRiskOverlay(max_portfolio_drawdown_pct=15.0,
                              deploy_data_dir=str(tmp_path))
    slots = [_make_slot("al", 100000), _make_slot("cu", 100000), _make_slot("zn", 100000)]
    ov.check_portfolio_drawdown(slots)  # peak = 300k
    # Drop 10%: equity = 270k -> drawdown = 10% < 15% -> OK
    slots = [_make_slot("al", 90000), _make_slot("cu", 90000), _make_slot("zn", 90000)]
    ok = ov.check_portfolio_drawdown(slots)
    assert ok is True


def test_overlay_save_load_roundtrip(tmp_path):
    ov = PortfolioRiskOverlay(max_portfolio_drawdown_pct=15.0,
                               deploy_data_dir=str(tmp_path))
    slots = [_make_slot("al", 110000), _make_slot("cu", 100000), _make_slot("zn", 100000)]
    ov.check_portfolio_drawdown(slots)  # peak = 310k
    ov.save()
    # New overlay reads persisted state
    ov2 = PortfolioRiskOverlay(max_portfolio_drawdown_pct=15.0,
                               deploy_data_dir=str(tmp_path))
    ov2.load(active_slot_ids=["al", "cu", "zn"])
    assert ov2.peak_equity == 310000.0


def test_drawdown_breach_trips_order_router_and_persists_across_restart(tmp_path):
    state_dir = tmp_path / "portfolio"
    router = OrderRouter(client=MagicMock(), state_dir=state_dir, deadline_s=30.0)
    ov = PortfolioRiskOverlay(
        max_portfolio_drawdown_pct=10.0,
        deploy_data_dir=str(state_dir),
    )
    ov.check_portfolio_drawdown([
        _make_slot("al", 100000),
        _make_slot("cu", 100000),
        _make_slot("zn", 100000),
    ])

    ok = ov.enforce_portfolio_drawdown([
        _make_slot("al", 89000),
        _make_slot("cu", 89000),
        _make_slot("zn", 89000),
    ], order_router=router)

    assert ok is False
    assert router.is_tripped
    assert router.tripped_reason == "portfolio_drawdown"
    with pytest.raises(OrderRouterTripped):
        router.submit_order("ENTRY_SHORT", "al2606.SF", 1, "al_s1")

    restarted = OrderRouter(client=MagicMock(), state_dir=state_dir, deadline_s=30.0)
    assert restarted.is_tripped
    assert restarted.tripped_reason == "portfolio_drawdown"
