"""Timezone-aware timestamp primitives.

Time is kept as ordinary ``datetime``/``date``/``time`` values.  This module
validates and combines them; it deliberately does not add a timestamp wrapper.
"""

from __future__ import annotations

import calendar
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def require_tz_aware(value: datetime, *, name: str = "timestamp") -> datetime:
    """Return *value* after rejecting naive or non-datetime values."""
    if not isinstance(value, datetime):
        raise TypeError(f"{name} must be a datetime, got {type(value).__name__}")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


def _require_date(value: date, *, name: str) -> date:
    if not isinstance(value, date) or isinstance(value, datetime):
        raise TypeError(f"{name} must be a date value")
    return value


def _require_wall_time(value: time, *, name: str) -> time:
    if not isinstance(value, time):
        raise TypeError(f"{name} must be a time value")
    if value.tzinfo is not None:
        raise ValueError(f"{name} must be a local wall time without tzinfo")
    return value


def _zone(timezone_name: str) -> ZoneInfo:
    if not isinstance(timezone_name, str) or not timezone_name.strip():
        raise ValueError("timezone must be a non-empty IANA timezone name")
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"unknown IANA timezone: {timezone_name!r}") from exc


def at_local(day: date, wall_time: time, timezone_name: str) -> datetime:
    """Combine declared local values and reject DST gaps or folds.

    Ambiguous wall times require a policy choice.  Because this layer has no
    such policy declaration, accepting either fold would be an implicit guess.
    """
    _require_date(day, name="day")
    _require_wall_time(wall_time, name="wall_time")
    zone = _zone(timezone_name)
    naive = datetime.combine(day, wall_time)

    candidates: list[datetime] = []
    for fold in (0, 1):
        candidate = naive.replace(tzinfo=zone, fold=fold)
        round_trip = candidate.astimezone(UTC).astimezone(zone)
        if round_trip.replace(tzinfo=None) == naive and round_trip.fold == fold:
            candidates.append(candidate)

    if not candidates:
        raise ValueError(f"local wall time {naive.isoformat()} does not exist in {timezone_name}")
    if len(candidates) > 1:
        raise ValueError(f"local wall time {naive.isoformat()} is ambiguous in {timezone_name}")
    return candidates[0]


def shift_calendar(
    value: datetime,
    *,
    years: int = 0,
    months: int = 0,
    days: int = 0,
) -> datetime:
    """Move an aware local datetime with month-end clamping.

    This is calendar arithmetic, not session counting.  The local wall time and
    timezone are preserved, and a shifted DST gap/fold is rejected rather than
    resolved silently.
    """
    require_tz_aware(value)
    for name, amount in (("years", years), ("months", months), ("days", days)):
        if not isinstance(amount, int) or isinstance(amount, bool):
            raise TypeError(f"{name} must be an integer")

    month_index = value.year * 12 + (value.month - 1) + years * 12 + months
    target_year, zero_based_month = divmod(month_index, 12)
    target_month = zero_based_month + 1
    target_day = min(value.day, calendar.monthrange(target_year, target_month)[1])
    shifted_day = date(target_year, target_month, target_day) + timedelta(days=days)
    wall_time = value.time().replace(tzinfo=None)

    if isinstance(value.tzinfo, ZoneInfo):
        return at_local(shifted_day, wall_time, value.tzinfo.key)
    return datetime.combine(shifted_day, wall_time).replace(tzinfo=value.tzinfo)
