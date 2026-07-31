"""Contract tests for io/data_logger — CSV column shape + atomicity invariants."""
import csv
from pathlib import Path

import pytest

from echolon.live.io.data_logger import (
    save_trading_data_snapshot, save_trade_execution,
)


def _empty_snapshot_kwargs(tmp_path):
    """Build the minimum required snapshot kwargs."""
    return {
        "trading_data_dir": str(tmp_path),
        "market_data": {
            "current_price": 24600.0, "daily_open": 24500.0,
            "daily_high": 24650.0, "daily_low": 24450.0, "volume": 1000,
        },
        "signal_data": {
            "signal_type": "ENTRY_LONG", "signal_strength": 0.8,
            "signal_confidence": 0.0, "signal_reason": "test",
        },
        "position_data": {
            "current_position_size": 1, "current_position_avg_price": 24600.0,
            "unrealized_pnl": 0.0,
        },
        "account_data": {"available_cash": 99000.0, "total_account_value": 100000.0},
        "performance_data": {
            "daily_pnl": 0.0, "total_pnl": 0.0, "win_rate": 0.0, "trade_count": 0,
        },
        "symbol": "aluminum",
        "action_contract": "al2606.SF", "position_contract": "al2606.SF",
        "position_direction": "LONG",
        "last_trade_action": {"action": "ENTRY_LONG", "price": 24600.0, "size": 1},
    }


def test_save_trading_data_snapshot_creates_csv(tmp_path):
    save_trading_data_snapshot(**_empty_snapshot_kwargs(tmp_path))
    csv_files = list(Path(tmp_path).glob("*.csv"))
    assert len(csv_files) == 1, f"Expected 1 CSV; found {csv_files}"
    # Filename convention from data_logger.
    assert csv_files[0].name == "trading_data_aluminum.csv"


def test_save_trading_data_snapshot_no_tmp_files_after_success(tmp_path):
    """Atomic write: no .tmp leakage after a clean save."""
    save_trading_data_snapshot(**_empty_snapshot_kwargs(tmp_path))
    leftover = list(Path(tmp_path).glob("*.tmp"))
    assert leftover == []


def test_save_trading_data_snapshot_appends_on_existing_file(tmp_path):
    """Two cycles -> two rows in the CSV."""
    save_trading_data_snapshot(**_empty_snapshot_kwargs(tmp_path))
    save_trading_data_snapshot(**_empty_snapshot_kwargs(tmp_path))
    csv_files = list(Path(tmp_path).glob("*.csv"))
    assert len(csv_files) == 1
    with open(csv_files[0], "r", encoding="utf-8") as f:
        lines = list(csv.DictReader(f))
    assert len(lines) == 2


def test_save_trading_data_snapshot_columns_include_contract_fields(tmp_path):
    """Frontend depends on action_contract/position_contract/position_direction
    columns — lock them in."""
    save_trading_data_snapshot(**_empty_snapshot_kwargs(tmp_path))
    csv_files = list(Path(tmp_path).glob("*.csv"))
    with open(csv_files[0], "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        cols = set(reader.fieldnames or [])
    required = {
        "timestamp", "symbol",
        "current_price", "daily_open", "daily_high", "daily_low", "volume",
        "signal_type", "signal_strength",
        "current_position_size", "current_position_avg_price", "unrealized_pnl",
        "available_cash", "total_account_value",
        "action_contract", "position_contract", "position_direction",
        "daily_pnl", "total_pnl", "win_rate", "trade_count",
    }
    missing = required - cols
    assert not missing, f"Missing required columns: {missing}; got {cols}"


def test_save_trade_execution_creates_csv(tmp_path):
    save_trade_execution(
        trading_data_dir=str(tmp_path),
        order_info={
            "order_id": "ord-1", "direction": "ENTRY_LONG", "order_type": "MARKET",
            "submitted_price": 24600.0, "submitted_size": 1,
        },
        execution_details={
            "executed_price": 24605.0, "executed_size": 1,
            "commission": 0.5, "commission_source": "broker", "status": "FILLED",
        },
        position_impact={
            "position_before": 0, "position_after": 1,
            "avg_price_before": 0.0, "avg_price_after": 24605.0,
        },
        pnl_impact={"realized_pnl": 0.0, "unrealized_pnl": 0.0},
        symbol="aluminum",
    )
    csv_files = list(Path(tmp_path).glob("trade_executions_*.csv"))
    assert len(csv_files) == 1
    with open(csv_files[0], "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["direction"] == "ENTRY_LONG"
    assert float(rows[0]["executed_price"]) == 24605.0
    assert rows[0]["commission_source"] == "broker"


def test_save_trade_execution_requires_commission_source_for_filled_rows(tmp_path):
    with pytest.raises(ValueError, match="commission_source"):
        save_trade_execution(
            trading_data_dir=str(tmp_path),
            order_info={
                "order_id": "ord-1",
                "direction": "ENTRY_LONG",
                "order_type": "MARKET",
                "submitted_price": 24600.0,
                "submitted_size": 1,
            },
            execution_details={
                "executed_price": 24605.0,
                "executed_size": 1,
                "commission": 0.5,
                "status": "FILLED",
            },
            position_impact={
                "position_before": 0,
                "position_after": 1,
                "avg_price_before": 0.0,
                "avg_price_after": 24605.0,
            },
            pnl_impact={"realized_pnl": 0.0, "unrealized_pnl": 0.0},
            symbol="aluminum",
        )
