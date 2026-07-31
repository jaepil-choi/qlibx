"""Tests for ABANDONED-EXIT recovery (Amendment B, design §22.5).

Covers the full flow: pending_exit_intent set on first EXIT submit,
cleared on full fill, blocks new entry on next cycle, escalates to
kill-at-band-edge after 2 cycles pending, writes operator alert.
"""
import json
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

# Stub xtquant
for _mod_name in (
    "xtquant", "xtquant.xtconstant", "xtquant.xtdata",
    "xtquant.xttrader", "xtquant.xttype",
):
    sys.modules.setdefault(_mod_name, MagicMock())

import pytest  # noqa: E402

from echolon.strategy.state_manager import (  # noqa: E402
    StateManager, PendingExitIntent,
)


# ---------------------------------------------------------------------------
# Test 22.5.1 — pending_exit_intent set on first EXIT submit
# ---------------------------------------------------------------------------


def test_pending_exit_intent_set_on_first_exit_submit(tmp_path):
    """portfolio.py's _set_pending_exit_intent records an intent before
    the first router.submit_order call for an EXIT-class order."""
    from echolon.live.orchestrator.portfolio import PortfolioTradingRunner
    from echolon.live.config.portfolio_deploy_config import PortfolioDeployConfig
    # Construct a minimal config with one slot. We bypass the runner's
    # full __init__ by calling _set_pending_exit_intent directly on a
    # mock slot fixture.

    from echolon.live.slot.trading_slot import TradingSlot
    state_path = tmp_path / "strategy_state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    fake_slot = TradingSlot.__new__(TradingSlot)
    fake_slot._state_path = str(state_path)
    fake_slot.slot_config = MagicMock(slot_id="al_s1")

    runner = PortfolioTradingRunner.__new__(PortfolioTradingRunner)
    runner.log = MagicMock()
    runner._set_pending_exit_intent(
        slot=fake_slot, intent="EXIT_LONG", original_size=2,
    )

    sm = StateManager(state_path=str(state_path))
    state = sm.load_state()
    assert state.pending_exit_intent is not None
    assert state.pending_exit_intent.intent == "EXIT_LONG"
    assert state.pending_exit_intent.original_size == 2
    assert state.pending_exit_intent.remaining_size == 2
    assert state.pending_exit_intent.cycles_pending == 1


# ---------------------------------------------------------------------------
# Test 22.5.2 — pending_exit cleared on full fill
# ---------------------------------------------------------------------------


def test_pending_exit_cleared_on_full_fill(tmp_path):
    """portfolio.py's _clear_pending_exit_intent removes the intent."""
    from echolon.live.orchestrator.portfolio import PortfolioTradingRunner

    state_path = tmp_path / "strategy_state.json"
    sm = StateManager(state_path=str(state_path))
    sm.load_state()
    sm.set_pending_exit_intent(PendingExitIntent(
        intent="EXIT_LONG", original_size=1, remaining_size=1,
        attempts_so_far=0,
        original_decision_time="2026-05-07T21:00:00",
        last_attempt_time="2026-05-07T21:00:00",
    ))
    sm.save_state()

    from echolon.live.slot.trading_slot import TradingSlot
    fake_slot = TradingSlot.__new__(TradingSlot)
    fake_slot._state_path = str(state_path)
    fake_slot.slot_config = MagicMock(slot_id="al_s1")

    runner = PortfolioTradingRunner.__new__(PortfolioTradingRunner)
    runner.log = MagicMock()
    runner.portfolio_dir = str(tmp_path / "portfolio")
    runner._clear_pending_exit_intent(fake_slot)

    sm2 = StateManager(state_path=str(state_path))
    state = sm2.load_state()
    assert state.pending_exit_intent is None


# ---------------------------------------------------------------------------
# Test 22.5.3 — pending_exit blocks new entry on next cycle
# ---------------------------------------------------------------------------


def test_pending_exit_blocks_new_entry_on_next_cycle(tmp_path):
    """TradingSlot.execute_bar with non-None pending_exit_intent
    invokes _resume_pending_exit and SKIPS strategy.on_bar()."""
    from echolon.live.slot.trading_slot import TradingSlot

    # Set up state with pending intent.
    state_path = tmp_path / "strategy_state.json"
    sm = StateManager(state_path=str(state_path))
    sm.load_state()
    sm.set_pending_exit_intent(PendingExitIntent(
        intent="EXIT_LONG", original_size=1, remaining_size=1,
        attempts_so_far=1,
        original_decision_time="2026-05-07T21:00:00",
        last_attempt_time="2026-05-07T21:00:00",
    ))
    sm.save_state()

    # Construct a partial TradingSlot.
    slot = TradingSlot.__new__(TradingSlot)
    slot._state_path = str(state_path)
    slot.slot_config = MagicMock(slot_id="al_s1")
    slot.engine = MagicMock()
    slot.strategy = MagicMock()
    slot.portfolio = MagicMock()
    slot.trading_contract = "al2606.SF"

    # Mock get_market_data().get_current_price()
    market_data = MagicMock()
    market_data.get_current_price.return_value = 24700.0
    slot.engine.get_market_data.return_value = market_data
    slot.engine.get_order_manager.return_value = MagicMock()

    # Execute bar — should invoke _resume_pending_exit, not strategy.on_bar()
    slot.execute_bar()

    # strategy.on_bar should NOT have been called
    slot.strategy.on_bar.assert_not_called()
    # order_manager.submit_exit_order SHOULD have been called
    slot.engine.get_order_manager.return_value.submit_exit_order.assert_called_once()


# ---------------------------------------------------------------------------
# Test 22.5.4 — kill-at-band-edge fires after cycles_pending reaches 3
# ---------------------------------------------------------------------------


def test_kill_at_band_edge_after_cycles_pending_3(tmp_path):
    """When pending.cycles_pending >= 3, _resume_pending_exit calls
    submit_exit_order with the kill-at-band-edge price (LIMIT, not None)."""
    from echolon.live.slot.trading_slot import TradingSlot

    state_path = tmp_path / "strategy_state.json"
    sm = StateManager(state_path=str(state_path))
    sm.load_state()
    sm.set_pending_exit_intent(PendingExitIntent(
        intent="EXIT_LONG", original_size=1, remaining_size=1,
        attempts_so_far=8,
        original_decision_time="2026-05-05T21:00:00",
        last_attempt_time="2026-05-07T20:59:00",
        cycles_pending=2,  # next cycle will increment to 3
    ))
    sm.save_state()

    slot = TradingSlot.__new__(TradingSlot)
    slot._state_path = str(state_path)
    slot.slot_config = MagicMock(slot_id="al_s1")
    slot.engine = MagicMock()
    slot.strategy = MagicMock()
    slot.portfolio = MagicMock()
    slot.trading_contract = "al2606.SF"

    md = MagicMock()
    md.get_current_price.return_value = 24700.0
    slot.engine.get_market_data.return_value = md
    om = MagicMock()
    slot.engine.get_order_manager.return_value = om

    # Patch kill_at_band_edge_price to return a known kill price
    with patch(
        "echolon.live.platforms.miniqmt.order_router.kill_at_band_edge_price",
        return_value=22950.0,  # below settlement (selling kill)
    ):
        slot.execute_bar()

    # submit_exit_order MUST have been called with explicit price=22950
    om.submit_exit_order.assert_called_once()
    call = om.submit_exit_order.call_args
    # kwargs or args
    if "price" in call.kwargs:
        assert call.kwargs["price"] == 22950.0
    else:
        assert call.args[1] == 22950.0


# ---------------------------------------------------------------------------
# Test 22.5.5 — alert file written on cycles_pending >= 2
# ---------------------------------------------------------------------------


def test_alert_file_written_on_cycles_pending_2(tmp_path):
    """When cycles_pending reaches 2, pending_exit_alerts.json is
    upserted in workspace/deploy/portfolio/."""
    from echolon.live.slot.trading_slot import TradingSlot

    # Set up the realistic directory layout the upsert helper expects:
    # state_path = .../slots/al_s1/strategy_state.json
    # alert_path = .../portfolio/pending_exit_alerts.json
    deploy_dir = tmp_path / "deploy"
    slots_dir = deploy_dir / "slots" / "al_s1"
    slots_dir.mkdir(parents=True, exist_ok=True)
    portfolio_dir = deploy_dir / "portfolio"

    state_path = slots_dir / "strategy_state.json"
    sm = StateManager(state_path=str(state_path))
    sm.load_state()
    sm.set_pending_exit_intent(PendingExitIntent(
        intent="EXIT_LONG", original_size=1, remaining_size=1,
        attempts_so_far=2,
        original_decision_time="2026-05-06T21:00:00",
        last_attempt_time="2026-05-07T20:59:00",
        cycles_pending=1,  # next call increments to 2
    ))
    sm.save_state()

    slot = TradingSlot.__new__(TradingSlot)
    slot._state_path = str(state_path)
    slot.slot_config = MagicMock(slot_id="al_s1")
    slot.engine = MagicMock()
    slot.strategy = MagicMock()
    slot.portfolio = MagicMock()
    slot.trading_contract = "al2606.SF"

    md = MagicMock()
    md.get_current_price.return_value = 24700.0
    slot.engine.get_market_data.return_value = md
    om = MagicMock()
    slot.engine.get_order_manager.return_value = om

    slot.execute_bar()

    alert_path = portfolio_dir / "pending_exit_alerts.json"
    assert alert_path.exists(), "Alert file MUST be written when cycles_pending >= 2"
    with open(alert_path) as f:
        alerts = json.load(f)
    assert len(alerts) == 1
    assert alerts[0]["slot_id"] == "al_s1"
    assert alerts[0]["intent"] == "EXIT_LONG"
    assert alerts[0]["cycles_pending"] == 2
    assert alerts[0]["remaining_size"] == 1
