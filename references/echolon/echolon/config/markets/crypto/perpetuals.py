"""
Crypto Perpetual Futures Configuration.

Cryptocurrency perpetual contracts have unique characteristics:
- 24/7 trading (no sessions or breaks)
- No contract expiry (perpetual)
- Funding rate mechanism instead of rollover
- Different margin and fee structures

This module provides base configuration for crypto perpetuals.
Exchange-specific details (Binance, OKX, etc.) can extend this.
"""

from datetime import time
from typing import Dict, List

from ..core.types import SessionWindow, SessionPhaseSpec, InstrumentSpec


# =============================================================================
# 24/7 Session Configuration
# =============================================================================

# Crypto has a single continuous session
CONTINUOUS_SESSION = SessionWindow(
 name='continuous',
 start=time(0, 0),
 end=time(23, 59),
 crosses_midnight=False, # Conceptually continuous
)

SESSIONS: Dict[str, SessionWindow] = {
 'continuous': CONTINUOUS_SESSION,
}

ALL_SESSIONS: List[SessionWindow] = [CONTINUOUS_SESSION]


# =============================================================================
# Session Phases (Optional - for intraday analysis)
# =============================================================================
# While crypto trades 24/7, some traders segment by global market hours

PHASES: Dict[str, SessionPhaseSpec] = {
 'asia': SessionPhaseSpec(
 name='asia',
 start=time(0, 0),
 end=time(8, 0),
 session_type='continuous',
 # UTC: 00:00-08:00 (Asia trading hours)
 ),
 'europe': SessionPhaseSpec(
 name='europe',
 start=time(8, 0),
 end=time(16, 0),
 session_type='continuous',
 # UTC: 08:00-16:00 (European trading hours)
 ),
 'americas': SessionPhaseSpec(
 name='americas',
 start=time(16, 0),
 end=time(0, 0),
 session_type='continuous',
 crosses_midnight=True,
 # UTC: 16:00-00:00 (Americas trading hours)
 ),
}


# =============================================================================
# Common Perpetual Instruments
# =============================================================================

# Base specs - exchanges will override commission/margin
PERPETUALS: Dict[str, InstrumentSpec] = {
 'btc': InstrumentSpec(
 code='btc',
 name='Bitcoin Perpetual',
 market='CRYPTO',
 multiplier=1.0, # 1 BTC per contract (varies by exchange)
 tick_size=0.1, # $0.10
 margin_rate=0.01, # 1% initial margin (100x max leverage)
 commission=0.0004, # 0.04% taker fee (typical)
 commission_type='percentage',
 currency='USDT',
 trading_unit='contracts',
 min_order_size=0.001,
 has_night_session=False, # N/A - 24/7
 sessions=ALL_SESSIONS,
 ),
 'eth': InstrumentSpec(
 code='eth',
 name='Ethereum Perpetual',
 market='CRYPTO',
 multiplier=1.0,
 tick_size=0.01,
 margin_rate=0.02, # 2% initial margin (50x max leverage)
 commission=0.0004,
 commission_type='percentage',
 currency='USDT',
 trading_unit='contracts',
 min_order_size=0.01,
 has_night_session=False,
 sessions=ALL_SESSIONS,
 ),
 'sol': InstrumentSpec(
 code='sol',
 name='Solana Perpetual',
 market='CRYPTO',
 multiplier=1.0,
 tick_size=0.001,
 margin_rate=0.05, # 5% initial margin (20x max leverage)
 commission=0.0004,
 commission_type='percentage',
 currency='USDT',
 trading_unit='contracts',
 min_order_size=0.1,
 has_night_session=False,
 sessions=ALL_SESSIONS,
 ),
}


# =============================================================================
# Constants
# =============================================================================

# 24/7 = 1440 minutes per day
TOTAL_TRADING_MINUTES = 24 * 60 # 1440

# Bars per day for different timeframes
BARS_PER_DAY: Dict[str, int] = {
 "1min": 1440,
 "5min": 288,
 "15min": 96,
 "30min": 48,
 "1h": 24,
 "4h": 6,
}


def get_bars_per_day(bar_size: str) -> int:
 """Get expected bars per day for a bar size."""
 return BARS_PER_DAY.get(bar_size, 288) # Default to 5min
