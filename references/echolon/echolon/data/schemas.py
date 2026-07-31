"""
Standard Market Data Schema
===========================

Defines the canonical schema for data flowing between data and indicators modules.
This is the CONTRACT between modules - any change here requires coordination.

Supports:
- Multiple markets: SHFE, crypto (Binance), CME, etc.
- Multiple frequencies: daily (interday), minute (intraday)
- Multiple asset types: futures, perpetuals, spot

Data Flow:
    data (extractors/transformers)
        -> StandardSchema (this file)
        -> indicators (calculators/engine)
        -> backtest/live

Schema Tiers:
    TIER 1 - CORE: Always required for any market/frequency
    TIER 2 - FREQUENCY: Required based on data frequency
    TIER 3 - MARKET: Required based on market type
    TIER 4 - OPTIONAL: Nice to have, may be missing
"""

from enum import Enum
from typing import List, Dict
import pandas as pd

# =============================================================================
# Enums for Market and Frequency Types
# =============================================================================

class MarketType(Enum):
    """Supported market types."""
    SHFE = "shfe"           # Shanghai Futures Exchange
    CRYPTO = "crypto"       # Cryptocurrency (Binance, etc.)
    CME = "cme"             # CME Group (US futures)
    GENERIC = "generic"     # Generic/unknown market


class FrequencyType(Enum):
    """Supported data frequencies."""
    DAILY = "daily"         # Interday (1 bar per day)
    MINUTE = "minute"       # Intraday (1-min to 1-hour bars)


# =============================================================================
# Column Definitions by Tier
# =============================================================================

# TIER 1: Core columns required for ALL data
CORE_COLUMNS: Dict[str, str] = {
    'date': 'datetime64[ns]',       # Trading date (normalized to midnight)
    'open': 'float64',              # Opening price
    'high': 'float64',              # High price
    'low': 'float64',               # Low price
    'close': 'float64',             # Closing price
    'volume': 'float64',            # Trading volume (float for crypto fractional)
}

# TIER 2: Frequency-specific columns
INTRADAY_COLUMNS: Dict[str, str] = {
    'datetime': 'datetime64[ns]',   # Full timestamp (date + time)
    'trading_date': 'object',       # Trading date as YYYYMMDD string (for grouping)
}

# Session columns for markets with trading sessions (SHFE, CME)
SESSION_COLUMNS: Dict[str, str] = {
    'session_phase': 'object',      # Session phase (night, morning, afternoon, etc.)
    'is_tradeable': 'bool',         # Whether trading is allowed in this bar
}

# TIER 3: Market-specific columns
FUTURES_COLUMNS: Dict[str, str] = {
    'contract': 'object',           # Contract identifier (e.g., 'al2403', 'ESH24')
    'contract_expiry': 'int64',     # Expiry date as YYYYMMDD integer
    'open_interest': 'float64',     # Open interest
    'settlement': 'float64',        # Settlement price
    'prev_close': 'float64',        # Previous close
    'prev_settlement': 'float64',   # Previous settlement
    'turnover': 'float64',          # Trading turnover (value)
}

CRYPTO_COLUMNS: Dict[str, str] = {
    'symbol': 'object',             # Trading pair (e.g., 'BTCUSDT')
    'quote_volume': 'float64',      # Volume in quote currency
    'trades': 'int64',              # Number of trades
    'taker_buy_volume': 'float64',  # Taker buy volume
}

# TIER 4: Optional/derived columns
DERIVED_COLUMNS: Dict[str, str] = {
    'returns': 'float64',           # Log returns: log(close/prev_close)
    'range': 'float64',             # High - Low
    'body': 'float64',              # abs(close - open)
    'upper_shadow': 'float64',      # High - max(open, close)
    'lower_shadow': 'float64',      # min(open, close) - Low
}


# =============================================================================
# Legacy Compatibility (originally in ohlcv.py)
# =============================================================================

OHLCV_COLUMNS = list(CORE_COLUMNS.keys())
COLUMN_TYPES = {**CORE_COLUMNS, **FUTURES_COLUMNS}

# Backwards-compatible list form of FUTURES_COLUMNS
FUTURES_COLUMNS_LIST = list(FUTURES_COLUMNS.keys())


class OHLCVSchema:
    """
    Legacy OHLCV schema for backwards compatibility.
    """
    REQUIRED = list(CORE_COLUMNS.keys())
    OPTIONAL = list(FUTURES_COLUMNS.keys())
    TYPES = COLUMN_TYPES

    @classmethod
    def validate(cls, df: pd.DataFrame) -> bool:
        """Validate DataFrame has required columns."""
        missing = set(cls.REQUIRED) - set(df.columns)
        return len(missing) == 0

    @classmethod
    def get_missing_columns(cls, df: pd.DataFrame) -> List[str]:
        """Get list of missing required columns."""
        return list(set(cls.REQUIRED) - set(df.columns))


__all__ = [
    # Enums
    'MarketType',
    'FrequencyType',
    # Column definitions
    'CORE_COLUMNS',
    'INTRADAY_COLUMNS',
    'SESSION_COLUMNS',
    'FUTURES_COLUMNS',
    'FUTURES_COLUMNS_LIST',
    'CRYPTO_COLUMNS',
    'DERIVED_COLUMNS',
    # Schema classes
    'OHLCVSchema',
    # Legacy constants
    'OHLCV_COLUMNS',
    'COLUMN_TYPES',
]
