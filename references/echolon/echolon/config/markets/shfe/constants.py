"""
SHFE Trading Constants.

Derived constants for trading calculations:
- Trading minutes per day
- Expected bars per day for different bar sizes
- Session duration calculations
"""

from typing import Dict

from ..shfe.sessions import ALL_SESSIONS, DAY_SESSIONS, NIGHT


# =============================================================================
# Trading Time Constants
# =============================================================================

# Total trading minutes per day (including night session)
# Night: 240 + Day1: 75 + Day2: 60 + Afternoon: 90 = 465 minutes
TOTAL_TRADING_MINUTES: int = sum(
    session.duration_minutes for session in ALL_SESSIONS
)

# Total trading minutes per day (day sessions only)
# Day1: 75 + Day2: 60 + Afternoon: 90 = 225 minutes
DAY_TRADING_MINUTES: int = sum(
    session.duration_minutes for session in DAY_SESSIONS
)

# Night session duration
NIGHT_TRADING_MINUTES: int = NIGHT.duration_minutes  # 240 minutes


# =============================================================================
# Bar Count Configuration
# =============================================================================

# Expected bars per day for different bar sizes (with night session)
# Supports both short ("5m") and long ("5min") formats
BARS_PER_DAY: Dict[str, int] = {
    # Short format (from state.json)
    "1m": 465,
    "5m": 93,
    "15m": 31,
    "30m": 16,
    "1h": 8,
    # Long format ("Nmin")
    "1min": 465,
    "5min": 93,
    "15min": 31,
    "30min": 16,
}

# Expected bars per day without night session
BARS_PER_DAY_NO_NIGHT: Dict[str, int] = {
    # Short format
    "1m": 225,
    "5m": 45,
    "15m": 15,
    "30m": 8,
    "1h": 4,
    # Long format ("Nmin")
    "1min": 225,
    "5min": 45,
    "15min": 15,
    "30min": 8,
}

# Session durations in minutes
SESSION_DURATION_MINUTES: Dict[str, int] = {
    "night": 240,      # 21:00-01:00
    "day1": 75,        # 09:00-10:15
    "day2": 60,        # 10:30-11:30
    "afternoon": 90,   # 13:30-15:00
    "morning": 135,    # day1 + day2 combined
}


# =============================================================================
# Helper Functions
# =============================================================================

def get_bars_per_day(bar_size: str, has_night_session: bool = True) -> int:
    """
    Get expected bars per day for a bar size.

    Args:
        bar_size: Bar size string (e.g., '5min', '15min')
        has_night_session: Whether to include night session

    Returns:
        Expected number of bars per trading day
    """
    if has_night_session:
        return BARS_PER_DAY.get(bar_size)  
    return BARS_PER_DAY_NO_NIGHT.get(bar_size, 45)


def get_trading_minutes(include_night: bool = True) -> int:
    """
    Get total trading minutes per day.

    Args:
        include_night: Whether to include night session

    Returns:
        Total trading minutes
    """
    if include_night:
        return TOTAL_TRADING_MINUTES
    return DAY_TRADING_MINUTES


def get_session_bars(bar_size: str, session_phase: str, has_night_session: bool = True) -> int:
    """
    Get expected number of bars for a specific session phase.

    Args:
        bar_size: Bar size string ('5m', '15m', '1h', etc.)
        session_phase: Session name ('night', 'morning', 'afternoon', 'day1', 'day2')
        has_night_session: Whether instrument trades night session

    Returns:
        Expected number of bars in that session
    """
    # Parse bar size to minutes
    bar_minutes = _parse_bar_size_minutes(bar_size)

    # Get session duration
    session_minutes = SESSION_DURATION_MINUTES.get(session_phase, 0)

    # For instruments without night session, night bars = 0
    if session_phase == 'night' and not has_night_session:
        return 0

    return max(1, session_minutes // bar_minutes)


def _parse_bar_size_minutes(bar_size: str) -> int:
    """
    Parse bar size string to minutes.

    Args:
        bar_size: Bar size string ('1m', '5m', '15m', '30m', '1h', '1min', '5min', etc.)

    Returns:
        Bar size in minutes
    """
    bar_size_lower = bar_size.lower()

    # Handle hour format
    if 'h' in bar_size_lower:
        hours = int(bar_size_lower.replace('h', ''))
        return hours * 60

    # Handle minute formats (both "5m" and "5min")
    if 'min' in bar_size_lower:
        return int(bar_size_lower.replace('min', ''))
    if 'm' in bar_size_lower:
        return int(bar_size_lower.replace('m', ''))

    # Handle day format
    if 'd' in bar_size_lower:
        return 1440  # 24 * 60

