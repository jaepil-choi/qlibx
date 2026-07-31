"""Cross-slot isolation — one slot's failures must not contaminate others."""
import json
from pathlib import Path

import pytest

from echolon.live.config.portfolio_deploy_config import (
    SlotConfig, SlotDashboardConfig,
)
from echolon.live.slot.trading_slot import TradingSlot


def _make_slot(tmp_path: Path, sid: str, instrument: str = "aluminum",
               instrument_code: str = "al") -> TradingSlot:
    sc = SlotConfig(
        slot_id=sid, strategy_id="t", cluster="c", version="1.0",
        instrument=instrument, instrument_code=instrument_code, market="SHFE",
        frequency="interday", bar_size="1d", initial_capital=100000.0,
        strategy_code_dir=str(tmp_path / sid / "strategy"), trial_params_path="",
        enabled=True, dashboard=SlotDashboardConfig(),
    )
    slot = TradingSlot(slot_config=sc, deploy_data_dir=str(tmp_path / "slots"))
    state_dir = tmp_path / "slots" / sid
    state_dir.mkdir(parents=True, exist_ok=True)
    slot._state_path = str(state_dir / "strategy_state.json")
    return slot


def test_per_slot_state_files_are_distinct_paths(tmp_path):
    """Each slot's strategy_state.json lives under its own slot_id dir."""
    slots = [
        _make_slot(tmp_path, "al_s1", "aluminum", "al"),
        _make_slot(tmp_path, "cu_s1", "copper", "cu"),
        _make_slot(tmp_path, "zn_s1", "zinc", "zn"),
    ]
    paths = {s._state_path for s in slots}
    assert len(paths) == 3, "Each slot must have a unique state path"
    # Each path is anchored to its slot_id directory.
    for s in slots:
        assert s.slot_id in s._state_path


def test_corrupt_one_slots_state_does_not_block_others(tmp_path):
    """If al_s1's strategy_state.json is malformed, pending-exit helpers
    on cu_s1 and zn_s1 must still work."""
    al = _make_slot(tmp_path, "al_s1")
    cu = _make_slot(tmp_path, "cu_s1")
    zn = _make_slot(tmp_path, "zn_s1")

    # Write valid state for cu and zn
    Path(cu._state_path).write_text("{}", encoding="utf-8")
    Path(zn._state_path).write_text("{}", encoding="utf-8")
    # Corrupt al's state
    Path(al._state_path).write_text("{ this is not valid json", encoding="utf-8")

    # cu and zn pending-exit operations must succeed despite al being corrupt
    cu.set_pending_exit_intent(intent="EXIT_LONG", original_size=1)
    zn.set_pending_exit_intent(intent="EXIT_SHORT", original_size=2)

    cu_state = json.loads(Path(cu._state_path).read_text(encoding="utf-8"))
    zn_state = json.loads(Path(zn._state_path).read_text(encoding="utf-8"))
    assert cu_state["pending_exit_intent"]["intent"] == "EXIT_LONG"
    assert zn_state["pending_exit_intent"]["intent"] == "EXIT_SHORT"


def test_capital_slot_state_isolated_per_slot():
    """Each CapitalSlot tracks its own realized_pnl independently."""
    from echolon.live.slot.capital_slot import CapitalSlot

    al = CapitalSlot(slot_id="al_s1", initial_capital=100000.0)
    cu = CapitalSlot(slot_id="cu_s1", initial_capital=200000.0)

    al.record_trade(realized_pnl=1000.0)
    cu.record_trade(realized_pnl=-500.0)

    assert al.realized_pnl == 1000.0
    assert cu.realized_pnl == -500.0
    assert al.equity == 101000.0
    assert cu.equity == 199500.0
