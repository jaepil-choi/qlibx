"""
SHFE Trading Sessions Configuration.

Shanghai Futures Exchange trading sessions (Beijing Time, UTC+8):
- Night session: 21:00-01:00 (next day) - 4 hours
- Day session 1: 09:00-10:15 - 75 minutes
- Morning break: 10:15-10:30 - 15 minutes (NO TRADING)
- Day session 2: 10:30-11:30 - 60 minutes
- Lunch break: 11:30-13:30 - 120 minutes (NO TRADING)
- Afternoon: 13:30-15:00 - 90 minutes

Total effective trading: 465 minutes (7.75 hours)
"""

from datetime import time
from typing import Dict, List

from ..core.types import SessionWindow


# Individual session windows
NIGHT = SessionWindow(
    name='night',
    start=time(21, 0),
    end=time(1, 0),
    crosses_midnight=True
)

DAY1 = SessionWindow(
    name='day1',
    start=time(9, 0),
    end=time(10, 15)
)

DAY2 = SessionWindow(
    name='day2',
    start=time(10, 30),
    end=time(11, 30)
)

AFTERNOON = SessionWindow(
    name='afternoon',
    start=time(13, 30),
    end=time(15, 0)
)


# Session collections
SESSIONS: Dict[str, SessionWindow] = {
    'night': NIGHT,
    'day1': DAY1,
    'day2': DAY2,
    'afternoon': AFTERNOON,
}

ALL_SESSIONS: List[SessionWindow] = [NIGHT, DAY1, DAY2, AFTERNOON]
DAY_SESSIONS: List[SessionWindow] = [DAY1, DAY2, AFTERNOON]
NIGHT_SESSIONS: List[SessionWindow] = [NIGHT]


def get_session(name: str) -> SessionWindow:
    """Get a session window by name."""
    return SESSIONS[name]


def get_session_for_time(t: time) -> str:
    """
    Get the session name for a given time.

    Args:
        t: Time to check

    Returns:
        Session name or None if outside trading hours
    """
    for name, session in SESSIONS.items():
        if session.contains_time(t):
            return name
    return None
