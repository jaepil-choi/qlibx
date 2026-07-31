"""
Crypto Session Context Provider
===============================

Crypto-specific implementation of session context provider.

Crypto trading is 24/7/365:
- No market open/close
- No weekends off
- No holidays
- Continuous liquidity

Session structure:
- Single continuous session spanning full day: 00:00 - 23:59:59
- No breaks
- No session boundaries to manage

For intraday strategies:
- Can use any bar frequency
- No need to consider session boundaries
- 24 hours = full trading day

This is a simplified implementation compared to traditional markets.
"""

import logging
from datetime import datetime, time
from typing import Dict, Optional, TYPE_CHECKING

from echolon.strategy.frequency.session_context_provider import BaseSessionContextProvider
from echolon.config.markets.core.types import SessionPhaseSpec

if TYPE_CHECKING:
    from echolon.markets.interface import IMarketAdapter

logger = logging.getLogger(__name__)


# =============================================================================
# Crypto Session Constants
# =============================================================================

# Crypto trades 24/7 - single continuous session
SESSION_START = time(0, 0)
SESSION_END = time(23, 59, 59)
TOTAL_MINUTES_PER_DAY = 24 * 60  # 1440 minutes


class CryptoSessionProvider(BaseSessionContextProvider):
    """
    Crypto-specific session context provider.

    Provides FACTUAL session context for 24/7 cryptocurrency trading:
    - Single continuous session (no breaks)
    - No session boundaries
    - Simplified phase structure

    DESIGN PRINCIPLE:
        Infrastructure provides factual data only.
        Strategy decides opening/closing phase thresholds.

    Parameters:
        market_adapter: Crypto market adapter
        bar_size_minutes: Bar size in minutes (default: 15)
    """

    def __init__(
        self,
        market_adapter: 'IMarketAdapter' = None,
        bar_size_minutes: int = 15,
    ):
        super().__init__(
            market_adapter=market_adapter,
            bar_size_minutes=bar_size_minutes,
        )

    # =========================================================================
    # Abstract Method Implementations
    # =========================================================================

    def _load_session_phases(self) -> Dict[str, SessionPhaseSpec]:
        """
        Load crypto session phases.

        Crypto has a simplified phase structure since it trades 24/7.
        We define optional phases for day boundaries if needed.
        """
        return {
            'continuous': SessionPhaseSpec(
                name='continuous',
                start=time(0, 0),
                end=time(23, 59, 59),
                is_trading=True,
                session_type='continuous',
            ),
        }

    def _get_session_start_time(self, session_type: str) -> time:
        """Get crypto session start time (always 00:00)."""
        return SESSION_START

    def _get_session_end_time(self, session_type: str) -> time:
        """Get crypto session end time (always 23:59)."""
        return SESSION_END

    def _get_break_minutes_before(self, current_time: datetime) -> int:
        """Get break minutes (always 0 for crypto)."""
        return 0  # No breaks in crypto

    def _get_total_bars_in_session(self, session_type: str) -> int:
        """Get total bars per day for crypto."""
        return TOTAL_MINUTES_PER_DAY // self._bar_size_minutes

    def get_total_sessions_per_day(self) -> int:
        """Crypto has 1 continuous session per day."""
        return 1

    # =========================================================================
    # Crypto-Specific Overrides (simplified implementations)
    # =========================================================================

    def get_session_type(self, current_time: datetime) -> str:
        """Get session type (always 'continuous' for crypto)."""
        return 'continuous'

    def get_session_phase(self, current_time: datetime) -> Optional[str]:
        """Get session phase (always 'continuous' for crypto)."""
        return 'continuous'

    def get_session_index(self, current_time: datetime) -> int:
        """Get session index (always 0 for crypto's single session)."""
        return 0

    def is_trading_allowed(self, current_time: datetime) -> bool:
        """Check if trading is allowed (always True for crypto)."""
        return True

    def is_session_break(self, current_time: datetime) -> bool:
        """Check if in break (always False for crypto)."""
        return False

    def get_bar_of_session(self, current_time: datetime) -> int:
        """Get 0-indexed bar position within day."""
        check_time = current_time.time()
        minutes_since_midnight = check_time.hour * 60 + check_time.minute
        return minutes_since_midnight // self._bar_size_minutes

    def get_bars_remaining_in_session(self, current_time: datetime) -> int:
        """Get bars remaining until SESSION end (for crypto, session = day)."""
        total_bars = self._get_total_bars_in_session('continuous')
        bar_of_session = self.get_bar_of_session(current_time)
        return max(0, total_bars - bar_of_session - 1)

    def get_minutes_since_session_open(self, current_time: datetime) -> int:
        """Get minutes since midnight."""
        check_time = current_time.time()
        return check_time.hour * 60 + check_time.minute

    def get_minutes_to_session_close(self, current_time: datetime) -> int:
        """Get minutes until midnight."""
        minutes_since_open = self.get_minutes_since_session_open(current_time)
        return TOTAL_MINUTES_PER_DAY - minutes_since_open

    def get_minutes_to_next_session(self, current_time: datetime) -> Optional[int]:
        """Get minutes to next session (None for crypto, always in session)."""
        return None

    def __repr__(self) -> str:
        return f"CryptoSessionProvider(bar_size={self._bar_size_minutes}min)"
