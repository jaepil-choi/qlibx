"""
SHFE Session Context Provider
=============================

SHFE-specific implementation of session context provider.

Uses centralized session configuration from utils/configs/market_config.py.
No duplicate constants - single source of truth.

SHFE trading sessions (Beijing Time, UTC+8):
1. Night Session:  21:00 - 01:00 (next day, 240 minutes)
2. Day Session 1:  09:00 - 10:15 (75 minutes)
3. Morning Break:  10:15 - 10:30 (15 minutes, NO TRADING)
4. Day Session 2:  10:30 - 11:30 (60 minutes)
5. Lunch Break:    11:30 - 13:30 (120 minutes, NO TRADING)
6. Afternoon:      13:30 - 15:00 (90 minutes)

Total effective trading time: 465 minutes (7.75 hours)
"""

import logging
from datetime import datetime, time, timedelta
from typing import Dict, Optional, TYPE_CHECKING

from echolon.strategy.frequency.session_context_provider import BaseSessionContextProvider

# Import session constants from centralized config (single source of truth)
from echolon.config.markets.core.types import SessionPhaseSpec
from echolon.config.markets.shfe.sessions import SESSIONS as SHFE_SESSIONS
from echolon.config.markets.shfe.phases import PHASES as SHFE_SESSION_PHASES_GRANULAR
from echolon.config.markets.shfe.phases import PHASES_AGGREGATED as SHFE_SESSION_PHASES_AGGREGATED
from echolon.config.markets.shfe.phases import is_aggregated_bar_size_minutes

if TYPE_CHECKING:
    from echolon.markets.interface import IMarketAdapter

logger = logging.getLogger(__name__)


# =============================================================================
# SHFE Session Constants (derived from centralized config)
# =============================================================================

# Night session times
NIGHT_SESSION_START = SHFE_SESSIONS['night'].start  # time(21, 0)
NIGHT_SESSION_END = SHFE_SESSIONS['night'].end      # time(1, 0)
NIGHT_SESSION_MINUTES = SHFE_SESSIONS['night'].duration_minutes  # 240

# Day session times (composite of day1 + day2 + afternoon)
DAY_SESSION_START = SHFE_SESSIONS['day1'].start     # time(9, 0)
DAY_SESSION_END = SHFE_SESSIONS['afternoon'].end    # time(15, 0)
DAY_SESSION_MINUTES = 225  # 3.75 hours effective (excluding breaks)

# Break times (derived from session phase boundaries)
# Use granular phases for break times since breaks are physical time boundaries
MORNING_BREAK_START = SHFE_SESSION_PHASES_GRANULAR['morning_break'].start  # time(10, 15)
MORNING_BREAK_END = SHFE_SESSION_PHASES_GRANULAR['morning_break'].end      # time(10, 30)
MORNING_BREAK_MINUTES = SHFE_SESSION_PHASES_GRANULAR['morning_break'].duration_minutes  # 15

LUNCH_BREAK_START = SHFE_SESSION_PHASES_GRANULAR['lunch_break'].start      # time(11, 30)
LUNCH_BREAK_END = SHFE_SESSION_PHASES_GRANULAR['lunch_break'].end          # time(13, 30)
LUNCH_BREAK_MINUTES = SHFE_SESSION_PHASES_GRANULAR['lunch_break'].duration_minutes  # 120


class SHFESessionProvider(BaseSessionContextProvider):
    """
    SHFE-specific session context provider.

    Provides FACTUAL session context for Shanghai Futures Exchange:
    - Night session (21:00-01:00) + Day session (09:00-15:00)
    - Morning break (10:15-10:30) and lunch break (11:30-13:30)
    - Session phases from market config

    DESIGN PRINCIPLE:
        Infrastructure provides factual data only.
        Strategy decides opening/closing phase thresholds.

    Parameters:
        market_adapter: SHFE market adapter
        bar_size_minutes: Bar size in minutes (default: 5)
    """

    def __init__(
        self,
        market_adapter: 'IMarketAdapter' = None,
        bar_size_minutes: int = 5,
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
        Load SHFE session phases from centralized config (bar-size-aware).

        Returns:
            For granular bar sizes (5m, 15m): PHASES with night, morning, afternoon, etc.
            For aggregated bar sizes (30m, 1h): PHASES_AGGREGATED with night_session, day_session
        """
        if is_aggregated_bar_size_minutes(self._bar_size_minutes):
            logger.debug(f"Using AGGREGATED phases for bar_size={self._bar_size_minutes}min")
            return SHFE_SESSION_PHASES_AGGREGATED
        else:
            logger.debug(f"Using GRANULAR phases for bar_size={self._bar_size_minutes}min")
            return SHFE_SESSION_PHASES_GRANULAR

    def _get_session_start_time(self, session_type: str) -> time:
        """Get SHFE session start time."""
        if session_type == 'night':
            return NIGHT_SESSION_START
        elif session_type == 'day':
            return DAY_SESSION_START
        return time(0, 0)

    def _get_session_end_time(self, session_type: str) -> time:
        """Get SHFE session end time."""
        if session_type == 'night':
            return NIGHT_SESSION_END
        elif session_type == 'day':
            return DAY_SESSION_END
        return time(23, 59)

    def _get_break_minutes_before(self, current_time: datetime) -> int:
        """Get SHFE break minutes that occurred before current_time."""
        session_type = self.get_session_type(current_time)

        if session_type == 'night':
            return 0  # No breaks in night session

        if session_type != 'day':
            return 0

        check_time = current_time.time()
        break_minutes = 0

        # Morning break: 10:15-10:30 (15 min)
        if check_time >= MORNING_BREAK_END:
            break_minutes += MORNING_BREAK_MINUTES

        # Lunch break: 11:30-13:30 (120 min)
        if check_time >= LUNCH_BREAK_END:
            break_minutes += LUNCH_BREAK_MINUTES

        return break_minutes

    def _get_total_bars_in_session(self, session_type: str) -> int:
        """Get total bars in SHFE session type."""
        if session_type == 'night':
            return NIGHT_SESSION_MINUTES // self._bar_size_minutes
        elif session_type == 'day':
            return DAY_SESSION_MINUTES // self._bar_size_minutes
        return 0

    def get_total_sessions_per_day(self) -> int:
        """SHFE has 2 sessions per trading day (night + day)."""
        return 2

    # =========================================================================
    # SHFE-Specific Overrides
    # =========================================================================

    def get_session_index(self, current_time: datetime) -> int:
        """
        Get 0-based session index for SHFE.

        SHFE trading day structure:
        - Session 0: Night session (21:00-01:00) - starts the trading day
        - Session 1: Day session (09:00-15:00) - ends the trading day
        """
        session_type = self.get_session_type(current_time)
        if session_type == 'break':
            return -1
        elif session_type == 'night':
            return 0  # Night is first session of trading day
        elif session_type == 'day':
            return 1  # Day is second session of trading day
        return -1

    def get_minutes_to_next_session(self, current_time: datetime) -> Optional[int]:
        """Get minutes until next SHFE session starts."""
        if self.is_trading_allowed(current_time):
            return None  # Already in session

        check_time = current_time.time()
        current_minutes = check_time.hour * 60 + check_time.minute

        # Define session start times
        day_start_minutes = DAY_SESSION_START.hour * 60 + DAY_SESSION_START.minute
        night_start_minutes = NIGHT_SESSION_START.hour * 60 + NIGHT_SESSION_START.minute

        # Check breaks within day session
        if MORNING_BREAK_START <= check_time < MORNING_BREAK_END:
            # In morning break, next trading at 10:30
            return (MORNING_BREAK_END.hour * 60 + MORNING_BREAK_END.minute) - current_minutes

        if LUNCH_BREAK_START <= check_time < LUNCH_BREAK_END:
            # In lunch break, next trading at 13:30
            return (LUNCH_BREAK_END.hour * 60 + LUNCH_BREAK_END.minute) - current_minutes

        # Between sessions
        if current_minutes < day_start_minutes:
            # Before day session (after night session ended)
            return day_start_minutes - current_minutes

        if current_minutes >= (DAY_SESSION_END.hour * 60) and current_minutes < night_start_minutes:
            # After day session, before night session
            return night_start_minutes - current_minutes

        # After night session start time (next day session)
        return (24 * 60 - current_minutes) + day_start_minutes

    def get_bar_of_session(self, current_time: datetime) -> int:
        """Get 0-indexed bar position within SHFE session."""
        session_type = self.get_session_type(current_time)
        if session_type in ('break', 'unknown'):
            return 0

        check_time = current_time.time()

        if session_type == 'night':
            # Night session starts at 21:00
            session_start = current_time.replace(
                hour=NIGHT_SESSION_START.hour,
                minute=NIGHT_SESSION_START.minute,
                second=0,
                microsecond=0
            )
            if check_time < NIGHT_SESSION_START:
                # We're past midnight, session started yesterday
                session_start -= timedelta(days=1)

            delta = current_time - session_start
            minutes_elapsed = delta.total_seconds() / 60
            return max(0, int(minutes_elapsed // self._bar_size_minutes))

        elif session_type == 'day':
            # Day session starts at 09:00
            session_start = current_time.replace(
                hour=DAY_SESSION_START.hour,
                minute=DAY_SESSION_START.minute,
                second=0,
                microsecond=0
            )

            delta = current_time - session_start
            minutes_elapsed = delta.total_seconds() / 60

            # Subtract break times
            if check_time >= MORNING_BREAK_END:
                minutes_elapsed -= MORNING_BREAK_MINUTES
            if check_time >= LUNCH_BREAK_END:
                minutes_elapsed -= LUNCH_BREAK_MINUTES

            return max(0, int(minutes_elapsed // self._bar_size_minutes))

        return 0

    def get_minutes_since_session_open(self, current_time: datetime) -> int:
        """Get minutes since SHFE session started."""
        session_type = self.get_session_type(current_time)
        if session_type in ('break', 'unknown'):
            return 0

        check_time = current_time.time()
        current_minutes = check_time.hour * 60 + check_time.minute

        if session_type == 'night':
            session_start_minutes = NIGHT_SESSION_START.hour * 60 + NIGHT_SESSION_START.minute

            if current_minutes >= session_start_minutes:
                return current_minutes - session_start_minutes
            else:
                # Past midnight
                return (24 * 60 - session_start_minutes) + current_minutes

        elif session_type == 'day':
            session_start_minutes = DAY_SESSION_START.hour * 60 + DAY_SESSION_START.minute
            elapsed = current_minutes - session_start_minutes

            # Subtract break times
            if check_time >= MORNING_BREAK_END:
                elapsed -= MORNING_BREAK_MINUTES
            if check_time >= LUNCH_BREAK_END:
                elapsed -= LUNCH_BREAK_MINUTES

            return max(0, elapsed)

        return 0

    def get_minutes_to_session_close(self, current_time: datetime) -> int:
        """Get minutes until SHFE session ends."""
        session_type = self.get_session_type(current_time)
        if session_type in ('break', 'unknown'):
            return 0

        check_time = current_time.time()
        current_minutes = check_time.hour * 60 + check_time.minute

        if session_type == 'night':
            session_end_minutes = NIGHT_SESSION_END.hour * 60 + NIGHT_SESSION_END.minute
            if current_minutes >= NIGHT_SESSION_START.hour * 60:
                # Before midnight
                return (24 * 60 - current_minutes) + session_end_minutes
            else:
                # After midnight
                return session_end_minutes - current_minutes

        elif session_type == 'day':
            session_end_minutes = DAY_SESSION_END.hour * 60 + DAY_SESSION_END.minute
            remaining = session_end_minutes - current_minutes

            # Subtract remaining break time if we haven't passed it yet
            if check_time < MORNING_BREAK_START:
                remaining -= MORNING_BREAK_MINUTES
            if check_time < LUNCH_BREAK_START:
                remaining -= LUNCH_BREAK_MINUTES

            return max(0, remaining)

        return 0

    def __repr__(self) -> str:
        return f"SHFESessionProvider(bar_size={self._bar_size_minutes}min)"
