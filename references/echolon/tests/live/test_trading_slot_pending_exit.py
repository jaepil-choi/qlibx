"""Unit tests for TradingSlot pending-exit-intent helpers (moved from
PortfolioTradingRunner in 2026-05-08 refactor).

Slot methods raise on error (matching original's behavior of having the
runner-side wrapper catch + log via self.log)."""
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from echolon.live.config.portfolio_deploy_config import SlotConfig, SlotDashboardConfig
from echolon.live.slot.trading_slot import TradingSlot


def _make_slot(tmp_path: Path) -> TradingSlot:
    sc = SlotConfig(
        slot_id="al_s1", strategy_id="al_test", cluster="al", version="1.0",
        instrument="aluminum", instrument_code="al", market="SHFE",
        frequency="interday", bar_size="1d", initial_capital=100000.0,
        strategy_code_dir=str(tmp_path / "strategy"), trial_params_path="",
        enabled=True, dashboard=SlotDashboardConfig(),
    )
    slot = TradingSlot(slot_config=sc, deploy_data_dir=str(tmp_path / "slots"))
    state_dir = tmp_path / "slots" / "al_s1"
    state_dir.mkdir(parents=True, exist_ok=True)
    slot._state_path = str(state_dir / "strategy_state.json")
    (state_dir / "strategy_state.json").write_text("{}", encoding="utf-8")
    return slot


def test_set_pending_exit_intent_writes_state(tmp_path):
    slot = _make_slot(tmp_path)
    slot.set_pending_exit_intent(intent="EXIT_LONG", original_size=3)

    data = json.loads(Path(slot._state_path).read_text(encoding="utf-8"))
    pending = data.get("pending_exit_intent")
    assert pending is not None
    assert pending["intent"] == "EXIT_LONG"
    assert pending["original_size"] == 3
    assert pending["remaining_size"] == 3
    assert pending["cycles_pending"] == 1


def test_set_pending_exit_intent_idempotent_when_same_intent(tmp_path):
    slot = _make_slot(tmp_path)
    slot.set_pending_exit_intent(intent="EXIT_LONG", original_size=3)
    slot.set_pending_exit_intent(intent="EXIT_LONG", original_size=3)

    data = json.loads(Path(slot._state_path).read_text(encoding="utf-8"))
    pending = data["pending_exit_intent"]
    assert pending["original_size"] == 3
    assert pending["cycles_pending"] == 1


def test_set_pending_exit_intent_overwrites_on_different_intent(tmp_path):
    """When a new intent is recorded over an existing different one, the
    counters reset (cycles_pending=1, attempts_so_far=0). Documents the
    non-obvious replacement behavior — a trapped EXIT_LONG that transitions
    to FORCED_EXIT must reset the escalation counter."""
    slot = _make_slot(tmp_path)
    slot.set_pending_exit_intent(intent="EXIT_LONG", original_size=3)
    slot.update_pending_exit_remaining(remaining=1)  # bump attempts_so_far

    slot.set_pending_exit_intent(intent="FORCED_EXIT", original_size=2)

    data = json.loads(Path(slot._state_path).read_text(encoding="utf-8"))
    pending = data["pending_exit_intent"]
    assert pending["intent"] == "FORCED_EXIT"
    assert pending["original_size"] == 2
    assert pending["cycles_pending"] == 1   # reset, not inherited
    assert pending["attempts_so_far"] == 0  # reset, not inherited


def test_clear_pending_exit_intent_removes_state(tmp_path):
    slot = _make_slot(tmp_path)
    slot.set_pending_exit_intent(intent="EXIT_LONG", original_size=3)
    slot.clear_pending_exit_intent()

    data = json.loads(Path(slot._state_path).read_text(encoding="utf-8"))
    assert data.get("pending_exit_intent") in (None, {})


def test_update_pending_exit_remaining_decrements(tmp_path):
    slot = _make_slot(tmp_path)
    slot.set_pending_exit_intent(intent="EXIT_LONG", original_size=3)
    slot.update_pending_exit_remaining(remaining=1)

    data = json.loads(Path(slot._state_path).read_text(encoding="utf-8"))
    pending = data["pending_exit_intent"]
    assert pending["remaining_size"] == 1
    assert pending["attempts_so_far"] == 1


def test_helpers_noop_when_state_path_unset(tmp_path):
    slot = _make_slot(tmp_path)
    slot._state_path = None
    slot.set_pending_exit_intent(intent="EXIT_LONG", original_size=1)
    slot.update_pending_exit_remaining(remaining=0)
    slot.clear_pending_exit_intent()


def test_update_pending_exit_remaining_noop_when_no_pending(tmp_path):
    slot = _make_slot(tmp_path)
    slot.update_pending_exit_remaining(remaining=0)
    data = json.loads(Path(slot._state_path).read_text(encoding="utf-8"))
    assert data.get("pending_exit_intent") in (None, {})
