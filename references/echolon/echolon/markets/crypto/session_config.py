"""
Crypto Session Configuration
============================

Trading session configuration for cryptocurrency markets.

This module re-exports session configuration from the canonical source
at config/markets/crypto/perpetuals.py.

Crypto trading is 24/7/365:
- No market open/close
- No weekends off
- No holidays
- Continuous liquidity

For intraday strategies:
- Can use any bar frequency
- No need to consider session boundaries
- 24 hours = full trading day

Time zone:
- Typically use UTC for consistency
- Exchange timestamps may vary
"""

from datetime import time

# Import from canonical source
from echolon.config.markets.crypto.perpetuals import (
    CONTINUOUS_SESSION,
    ALL_SESSIONS,
    TOTAL_TRADING_MINUTES,
    BARS_PER_DAY,
    get_bars_per_day,
)

__all__ = [
    'CONTINUOUS_SESSION',
    'ALL_SESSIONS',
    'TOTAL_TRADING_MINUTES',
    'BARS_PER_DAY',
    'get_bars_per_day',
    'is_session_active',
    'get_session_close_time',
]


def is_session_active(check_time: time) -> bool:
    """
    Check if trading session is active.

    For crypto, always returns True (24/7 trading).

    Args:
        check_time: Time to check

    Returns:
        Always True for crypto
    """
    return True


def get_session_close_time() -> time:
    """
    Get the session close time.

    For crypto, returns 23:59:59 (end of day).

    Returns:
        Time representing end of day
    """
    return time(23, 59, 59)
