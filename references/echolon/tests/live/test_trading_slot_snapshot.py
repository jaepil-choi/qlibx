"""Unit tests for TradingSlot.build_snapshot_data (moved from
PortfolioTradingRunner._market_open_job_inner Phase 5 in 2026-05-08 refactor)."""
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from echolon.live.config.portfolio_deploy_config import SlotConfig, SlotDashboardConfig
from echolon.live.slot.trading_slot import TradingSlot


def _make_slot_with_runtime(tmp_path: Path) -> TradingSlot:
    sc = SlotConfig(
        slot_id="al_s1", strategy_id="al_test", cluster="al", version="1.0",
        instrument="aluminum", instrument_code="al", market="SHFE",
        frequency="interday", bar_size="1d", initial_capital=100000.0,
        strategy_code_dir=str(tmp_path / "strategy"), trial_params_path="",
        enabled=True, dashboard=SlotDashboardConfig(),
    )
    slot = TradingSlot(slot_config=sc, deploy_data_dir=str(tmp_path / "slots"))
    # Wire up minimal mocks for runtime objects.
    slot.engine = MagicMock()
    slot.engine.get_market_data.return_value = MagicMock(
        get_current_price=lambda: 24600.0,
        get_open=lambda: 24500.0,
        get_high=lambda: 24650.0,
        get_low=lambda: 24450.0,
        get_volume=lambda: 12000,
    )
    pos = MagicMock(size=2, avg_price=24550.0, symbol="al2606.SF", direction="LONG")
    slot.portfolio = MagicMock(
        get_position=lambda: pos,
        get_unrealized_pnl=lambda: 100.0,
    )
    slot.capital_slot = MagicMock(available_cash=99000.0, equity=100100.0, realized_pnl=50.0)
    slot.trading_contract = "al2606.SF"
    slot.todays_processed_fills = []
    slot.strategy = MagicMock(total_trades=5)
    slot.strategy.strategy_logger = MagicMock(current_bar_data={
        "entry_signal": "ENTRY_LONG",
        "entry_strength": 0.8,
        "entry_reason": "trending up",
    })
    return slot


def test_build_snapshot_data_returns_complete_dict(tmp_path):
    slot = _make_slot_with_runtime(tmp_path)
    snap = slot.build_snapshot_data()

    assert snap["market_data"]["current_price"] == 24600.0
    assert snap["position_data"]["current_position_size"] == 2
    assert snap["position_data"]["current_position_avg_price"] == 24550.0
    assert snap["account_data"]["available_cash"] == 99000.0
    assert snap["signal_data"]["signal_type"] == "ENTRY_LONG"
    assert snap["signal_data"]["signal_reason"] == "trending up"
    assert snap["last_trade_action"] is None  # no fills today
    assert snap["market_data"]["daily_high"] == 24650.0
    assert snap["market_data"]["daily_low"] == 24450.0
    assert snap["market_data"]["volume"] == 12000


def test_build_snapshot_data_handles_exit_signal(tmp_path):
    slot = _make_slot_with_runtime(tmp_path)
    slot.strategy.strategy_logger.current_bar_data = {
        "exit_should_exit": True,
        "exit_reason": "stop loss hit",
    }
    snap = slot.build_snapshot_data()
    assert snap["signal_data"]["signal_type"] == "EXIT"
    assert snap["signal_data"]["signal_strength"] == 1.0
    assert snap["signal_data"]["signal_reason"] == "stop loss hit"


def test_build_snapshot_data_includes_last_trade_action(tmp_path):
    slot = _make_slot_with_runtime(tmp_path)
    slot.todays_processed_fills = [
        {"intent": "ENTRY_LONG", "price": 24600.0, "volume": 1},
    ]
    snap = slot.build_snapshot_data()
    assert snap["last_trade_action"] is not None
    assert snap["last_trade_action"]["action"] == "ENTRY_LONG"
    assert snap["last_trade_action"]["price"] == 24600.0
    assert snap["last_trade_action"]["size"] == 1


def test_build_snapshot_data_handles_missing_strategy_logger(tmp_path):
    slot = _make_slot_with_runtime(tmp_path)
    slot.strategy.strategy_logger = None
    snap = slot.build_snapshot_data()
    # Defensive: should not raise; signal fields fall back to defaults.
    assert snap["signal_data"]["signal_type"] is None


def test_build_snapshot_data_no_position(tmp_path):
    slot = _make_slot_with_runtime(tmp_path)
    slot.portfolio.get_position = lambda: None
    snap = slot.build_snapshot_data()
    assert snap["position_data"]["current_position_size"] == 0
    assert snap["position_data"]["current_position_avg_price"] is None
    assert snap["position_contract"] == ""


def test_build_snapshot_data_no_strategy(tmp_path):
    """Defensive path: slot.strategy is None (e.g. cold-start or
    partial-init). signal_type and trade_count fall back to defaults
    without raising."""
    slot = _make_slot_with_runtime(tmp_path)
    slot.strategy = None
    snap = slot.build_snapshot_data()
    assert snap["signal_data"]["signal_type"] is None
    assert snap["performance_data"]["trade_count"] == 0


def test_build_snapshot_data_market_data_failure_logged_with_zero_defaults(tmp_path, caplog):
    """D1: when engine.get_market_data() raises, snapshot is still
    produced with zero defaults and a warning is emitted."""
    import logging
    slot = _make_slot_with_runtime(tmp_path)
    slot.engine.get_market_data.side_effect = RuntimeError("data layer dead")

    with caplog.at_level(logging.WARNING, logger="echolon.live.slot.trading_slot"):
        snap = slot.build_snapshot_data()

    assert snap["market_data"]["current_price"] == 0.0
    assert snap["market_data"]["daily_open"] == 0.0
    assert snap["market_data"]["volume"] == 0
    # Warning logged
    assert any("market_data extraction failed" in r.message for r in caplog.records)


def test_build_snapshot_data_with_none_current_bar_data(tmp_path):
    """D2: current_bar_data=None is handled by isinstance check (was
    previously an AttributeError on cbd.get(...))."""
    slot = _make_slot_with_runtime(tmp_path)
    slot.strategy.strategy_logger.current_bar_data = None

    snap = slot.build_snapshot_data()

    # No raise; signal_type falls back to defaults
    assert snap["signal_data"]["signal_type"] is None


def test_build_snapshot_data_with_none_capital_slot(tmp_path):
    """D4: capital_slot=None falls back to 0.0 across account_data
    and performance_data."""
    slot = _make_slot_with_runtime(tmp_path)
    slot.capital_slot = None

    snap = slot.build_snapshot_data()

    assert snap["account_data"]["available_cash"] == 0.0
    assert snap["account_data"]["total_account_value"] == 0.0
    assert snap["performance_data"]["total_pnl"] == 0.0
