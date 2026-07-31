"""
Trading Data Logger
===================

Logs trading snapshots and trade executions to CSV files.
Ported from QTS_deploy/miniqmt/trading_data_logging.py.

Provides:
- TradingDataRecord: Dataclass for trading snapshots
- TradeExecution: Dataclass for individual trade records
- save_trading_data_snapshot(): Save market/position/account snapshot
- save_trade_execution(): Save individual trade execution
- load_trading_data_history(): Load historical snapshots
- load_trade_executions_history(): Load historical executions
"""

import os
import pandas as pd
import logging
import threading
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from dataclasses import dataclass, asdict

from ..config.logging_config import get_deploy_logger

logger = get_deploy_logger(__name__)

# Thread lock for file operations
_file_lock = threading.Lock()


@dataclass
class TradingDataRecord:
    """Trading data record structure for logging."""
    timestamp: str
    symbol: str

    # Market data
    current_price: float
    daily_open: float
    daily_high: float
    daily_low: float
    volume: int

    # Strategy signals (latest)
    signal_type: Optional[str] = None  # 'BUY', 'SELL', 'HOLD', 'EXIT'
    signal_strength: float = 0.0
    signal_confidence: float = 0.0
    signal_reason: Optional[str] = None
    # Per-pathway identifier for paradigms that decompose signal generation
    # into named pathways (e.g., TRS's P1..P8 regime-routed pathways). Set
    # by paradigm-specific signal-emission code at order placement time;
    # consumed by qorka's A9 §4.11 live-replay diagnostic to compute
    # per-pathway hit-rate drift (live vs backtest signal-fired-correctly
    # rate per pathway). `None` for paradigms without pathway structure.
    # Per Q51 (qorka decisions_log.md 2026-05-12).
    pathway_id: Optional[str] = None

    # Trading actions
    last_action: Optional[str] = None  # 'BOUGHT', 'SOLD', 'CLOSED'
    last_action_price: Optional[float] = None
    last_action_size: Optional[int] = None
    last_action_time: Optional[str] = None

    # Position and account info
    current_position_size: int = 0
    current_position_avg_price: Optional[float] = None
    unrealized_pnl: float = 0.0
    available_cash: float = 0.0
    total_account_value: float = 0.0

    # Contract & direction tracking
    action_contract: Optional[str] = None    # contract the trade action executed on (empty if no action)
    position_contract: Optional[str] = None  # contract of held position after cycle (empty if flat)
    position_direction: Optional[str] = None # LONG, SHORT, or empty if flat

    # Performance metrics
    daily_pnl: float = 0.0
    total_pnl: float = 0.0
    win_rate: float = 0.0
    trade_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for CSV saving."""
        return asdict(self)


@dataclass
class TradeExecution:
    """Trade execution record for detailed trade logging."""
    timestamp: str
    symbol: str
    order_id: str
    direction: str  # 'ENTRY_LONG', 'EXIT_LONG', etc.
    order_type: str  # 'MARKET', 'LIMIT'
    status: str = 'FILLED'
    schema: str = 'trade_execution/v1'

    # Submission details
    submitted_price: float = 0.0
    submitted_size: int = 0

    # Execution details (from callback)
    executed_price: float = 0.0
    executed_size: int = 0
    commission: float = 0.0
    commission_source: Optional[str] = None

    # Position impact
    position_before: int = 0
    position_after: int = 0
    avg_price_before: Optional[float] = None
    avg_price_after: Optional[float] = None

    # P&L impact
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for CSV saving."""
        return asdict(self)


# =========================================================================
# File Path Helpers
# =========================================================================

def _get_trading_data_file_path(trading_data_dir: str, symbol: str) -> str:
    """Get the file path for trading data CSV."""
    filename = f"trading_data_{symbol.replace('.', '_')}.csv"
    return os.path.join(trading_data_dir, filename)


def _get_trade_executions_file_path(trading_data_dir: str, symbol: str) -> str:
    """Get the file path for trade executions CSV."""
    filename = f"trade_executions_{symbol.replace('.', '_')}.csv"
    return os.path.join(trading_data_dir, filename)


# =========================================================================
# Internal CSV Helpers
# =========================================================================

def _append_to_csv(file_path: str, data_dict: Dict[str, Any]) -> None:
    """
    Append a single record to CSV file with auto-trim to 2000 records.

    Args:
        file_path: Path to the CSV file
        data_dict: Record data as dictionary
    """
    df_new = pd.DataFrame([data_dict])

    if os.path.exists(file_path):
        df_existing = pd.read_csv(file_path)
        df_combined = pd.concat([df_existing, df_new], ignore_index=True)
    else:
        df_combined = df_new

    # Keep only last 2000 records to prevent file from growing too large
    if len(df_combined) > 2000:
        df_combined = df_combined.tail(2000)
        logger.info(f"Trimmed trading data history to last 2000 records: {file_path}")

    df_combined.to_csv(file_path, index=False)


# =========================================================================
# Public API
# =========================================================================

def save_trading_data_snapshot(
    trading_data_dir: str,
    market_data: Dict[str, Any],
    signal_data: Dict[str, Any],
    position_data: Dict[str, Any],
    account_data: Dict[str, Any],
    performance_data: Dict[str, Any],
    symbol: str,
    action_contract: Optional[str] = None,
    position_contract: Optional[str] = None,
    position_direction: Optional[str] = None,
    last_trade_action: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    Save comprehensive trading data snapshot to CSV.

    Args:
        trading_data_dir: Directory to store trading data CSV files
        market_data: Current market data (price, volume, etc.)
        signal_data: Latest strategy signal information
        position_data: Current position information
        account_data: Account balance and cash information
        performance_data: Performance metrics (P&L, win rate, etc.)
        symbol: Trading instrument name (e.g., "aluminum")
        action_contract: Contract the trade action executed on (empty if no action)
        position_contract: Contract of held position after cycle (empty if flat)
        position_direction: LONG, SHORT, or empty if flat
        last_trade_action: Last trade execution details

    Returns:
        True if successful, False otherwise
    """
    try:
        os.makedirs(trading_data_dir, exist_ok=True)

        trading_record = TradingDataRecord(
            timestamp=datetime.now().isoformat(),
            symbol=symbol,
            action_contract=action_contract,
            position_contract=position_contract,
            position_direction=position_direction,
            # Market data
            current_price=market_data.get('current_price', 0.0),
            daily_open=market_data.get('daily_open', 0.0),
            daily_high=market_data.get('daily_high', 0.0),
            daily_low=market_data.get('daily_low', 0.0),
            volume=market_data.get('volume', 0),
            # Strategy signals
            signal_type=signal_data.get('signal_type'),
            signal_strength=signal_data.get('signal_strength', 0.0),
            signal_confidence=signal_data.get('signal_confidence', 0.0),
            signal_reason=signal_data.get('signal_reason'),
            pathway_id=signal_data.get('pathway_id'),  # per Q51 — None for non-pathway paradigms
            # Trading actions
            last_action=last_trade_action.get('action') if last_trade_action else 'NO_ACTION',
            last_action_price=last_trade_action.get('price') if last_trade_action else 0.0,
            last_action_size=last_trade_action.get('size') if last_trade_action else 0,
            last_action_time=last_trade_action.get('timestamp') if last_trade_action else None,
            # Position and account
            current_position_size=position_data.get('current_position_size', 0),
            current_position_avg_price=position_data.get('current_position_avg_price'),
            unrealized_pnl=position_data.get('unrealized_pnl', 0.0),
            available_cash=account_data.get('available_cash', 0.0),
            total_account_value=account_data.get('total_account_value', 0.0),
            # Performance metrics
            daily_pnl=performance_data.get('daily_pnl', 0.0),
            total_pnl=performance_data.get('total_pnl', 0.0),
            win_rate=performance_data.get('win_rate', 0.0),
            trade_count=performance_data.get('trade_count', 0),
        )

        with _file_lock:
            file_path = _get_trading_data_file_path(trading_data_dir, symbol)
            _append_to_csv(file_path, trading_record.to_dict())

        logger.info(f"Trading data saved for {symbol}")
        return True

    except Exception as e:
        logger.error(f"Error saving trading data snapshot: {e}")
        return False


def save_trade_execution(
    trading_data_dir: str,
    order_info: Dict[str, Any],
    execution_details: Dict[str, Any],
    position_impact: Dict[str, Any],
    pnl_impact: Dict[str, Any],
    symbol: str,
) -> bool:
    """
    Save individual trade execution to CSV.

    Args:
        trading_data_dir: Directory to store trading data CSV files
        order_info: Order details (ID, direction, type, etc.)
        execution_details: Execution details (price, size, commission)
        position_impact: Position changes (before/after)
        pnl_impact: P&L impact (realized, unrealized)
        symbol: Trading symbol

    Returns:
        True if successful, False otherwise
    """
    status = execution_details.get('status', 'FILLED')
    commission_source = execution_details.get('commission_source')
    if status == 'FILLED' and commission_source not in {'broker', 'computed'}:
        raise ValueError(
            "commission_source must be 'broker' or 'computed' for FILLED executions"
        )

    try:
        os.makedirs(trading_data_dir, exist_ok=True)
        trade_record = TradeExecution(
            timestamp=datetime.now().isoformat(),
            symbol=symbol,
            order_id=order_info.get('order_id', ''),
            direction=order_info.get('direction', ''),
            order_type=order_info.get('order_type', 'MARKET'),
            status=execution_details.get('status', 'FILLED'),
            # Submission details
            submitted_price=order_info.get('submitted_price', 0.0),
            submitted_size=order_info.get('submitted_size', 0),
            # Execution details
            executed_price=execution_details.get('executed_price', 0.0),
            executed_size=execution_details.get('executed_size', 0),
            commission=execution_details.get('commission', 0.0),
            commission_source=commission_source,
            # Position impact
            position_before=position_impact.get('position_before', 0),
            position_after=position_impact.get('position_after', 0),
            avg_price_before=position_impact.get('avg_price_before'),
            avg_price_after=position_impact.get('avg_price_after'),
            # P&L impact
            realized_pnl=pnl_impact.get('realized_pnl', 0.0),
            unrealized_pnl=pnl_impact.get('unrealized_pnl', 0.0),
        )

        with _file_lock:
            file_path = _get_trade_executions_file_path(trading_data_dir, symbol)
            _append_to_csv(file_path, trade_record.to_dict())

        logger.info(
            f"Trade execution saved: {trade_record.direction} "
            f"{trade_record.executed_size} @ {trade_record.executed_price}"
        )
        return True

    except Exception as e:
        logger.error(f"Error saving trade execution: {e}")
        return False


def load_trading_data_history(
    trading_data_dir: str,
    symbol: str,
    days_back: int = 7,
) -> Optional[pd.DataFrame]:
    """
    Load trading data history for analysis.

    Args:
        trading_data_dir: Directory containing trading data CSV files
        symbol: Trading symbol
        days_back: Number of days to look back

    Returns:
        DataFrame of trading data history, or None if not found
    """
    try:
        file_path = _get_trading_data_file_path(trading_data_dir, symbol)

        if not os.path.exists(file_path):
            logger.warning(f"Trading data file not found: {file_path}")
            return None

        df = pd.read_csv(file_path)

        if 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            cutoff_date = datetime.now() - timedelta(days=days_back)
            df = df[df['timestamp'] >= cutoff_date]
            df = df.sort_values('timestamp', ascending=False)

        logger.info(f"Loaded {len(df)} trading data records for {symbol} (last {days_back} days)")
        return df

    except Exception as e:
        logger.error(f"Error loading trading data history: {e}")
        return None


def load_trade_executions_history(
    trading_data_dir: str,
    symbol: str,
    days_back: int = 30,
) -> Optional[pd.DataFrame]:
    """
    Load trade execution history for analysis.

    Args:
        trading_data_dir: Directory containing trading data CSV files
        symbol: Trading symbol
        days_back: Number of days to look back

    Returns:
        DataFrame of trade execution history, or None if not found
    """
    try:
        file_path = _get_trade_executions_file_path(trading_data_dir, symbol)

        if not os.path.exists(file_path):
            logger.warning(f"Trade executions file not found: {file_path}")
            return None

        df = pd.read_csv(file_path)

        if 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            cutoff_date = datetime.now() - timedelta(days=days_back)
            df = df[df['timestamp'] >= cutoff_date]
            df = df.sort_values('timestamp', ascending=False)

        logger.info(f"Loaded {len(df)} trade executions for {symbol} (last {days_back} days)")
        return df

    except Exception as e:
        logger.error(f"Error loading trade executions history: {e}")
        return None
