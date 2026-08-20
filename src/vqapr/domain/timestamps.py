"""Timezone-aware timestamp primitives.

Time is kept as ordinary ``datetime``/``date``/``time`` values.  This module
validates and combines them; it deliberately does not add a timestamp wrapper.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
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


_OFFSET = re.compile(r"(?P<sign>[+-])(?P<hour>\d{2}):(?P<minute>\d{2})\Z")


def _parse_offset(value: str) -> timedelta:
    if not isinstance(value, str):
        raise TypeError("offset must be an ISO UTC offset string")
    match = _OFFSET.fullmatch(value)
    if match is None:
        raise ValueError("offset must use ISO UTC offset format ±HH:MM")
    hours = int(match["hour"])
    minutes = int(match["minute"])
    if hours > 14 or minutes > 59 or (hours == 14 and minutes != 0):
        raise ValueError("offset must be within ±14:00")
    amount = timedelta(hours=hours, minutes=minutes)
    return -amount if match["sign"] == "-" else amount


def _format_offset(value: timedelta) -> str:
    seconds = int(value.total_seconds())
    sign = "-" if seconds < 0 else "+"
    hours, remainder = divmod(abs(seconds), 3600)
    minutes, seconds = divmod(remainder, 60)
    if seconds:
        raise ValueError("timezone offset must be expressible as ±HH:MM")
    return f"{sign}{hours:02d}:{minutes:02d}"


@dataclass(frozen=True, slots=True)
class LocalInstantDeclaration:
    """A locally declared instant with enough proof to reproduce its UTC value."""

    local_date: date
    local_time: time
    timezone: str
    fold: int
    offset: str

    def __post_init__(self) -> None:
        _require_date(self.local_date, name="local_date")
        _require_wall_time(self.local_time, name="local_time")
        if not isinstance(self.fold, int) or isinstance(self.fold, bool) or self.fold not in (0, 1):
            raise ValueError("fold must be 0 or 1")
        declared_offset = _parse_offset(self.offset)
        zone = _zone(self.timezone)
        naive = datetime.combine(self.local_date, self.local_time)
        candidate = naive.replace(tzinfo=zone, fold=self.fold)
        round_trip = candidate.astimezone(UTC).astimezone(zone)
        if round_trip.replace(tzinfo=None) != naive or round_trip.fold != self.fold:
            raise ValueError(
                f"local wall time {naive.isoformat()} with fold {self.fold} "
                f"does not exist in {self.timezone}"
            )
        computed_offset = candidate.utcoffset()
        if computed_offset != declared_offset:
            raise ValueError(
                f"declared offset {self.offset} does not match "
                f"{_format_offset(computed_offset or timedelta())} in {self.timezone}"
            )

    @property
    def instant(self) -> datetime:
        return datetime.combine(self.local_date, self.local_time).replace(
            tzinfo=_zone(self.timezone),
            fold=self.fold,
        )

    @property
    def utc_instant(self) -> datetime:
        return self.instant.astimezone(UTC)

    def identity(self) -> tuple[str, str, str, int, str]:
        return (
            self.local_date.isoformat(),
            self.local_time.isoformat(),
            self.timezone,
            self.fold,
            self.offset,
        )


def declare_local_instant(
    local_date: date, local_time: time, timezone: str
) -> LocalInstantDeclaration:
    """Resolve a wall time in a zone into a declaration, deriving its fold and offset.

    `LocalInstantDeclaration` requires `fold` and `offset` because a wall time alone does not
    identify an instant: on a DST fall-back day the same clock reading happens twice. Requiring
    them is right for a stored declaration, whose whole purpose is to reproduce one instant.

    It is wrong as something a caller types. A caller writing `0` and `"+09:00"` by hand is
    stating a fact about a zone rather than looking it up, and that is correct until the venue
    observes DST -- after which it is wrong twice a year and the declaration still validates on
    every other day.

    So this derives them, and refuses what cannot be derived:

    - a wall time that **does not exist** (spring forward) has no instant to name
    - a wall time that happens **twice** (fall back) needs the caller to say which, because
      guessing would silently pick one
    """
    zone = _zone(timezone)
    naive = datetime.combine(local_date, local_time)
    resolved = []
    for fold in (0, 1):
        candidate = naive.replace(tzinfo=zone, fold=fold)
        round_trip = candidate.astimezone(UTC).astimezone(zone)
        if round_trip.replace(tzinfo=None) == naive and round_trip.fold == fold:
            resolved.append(candidate)
    if not resolved:
        raise ValueError(
            f"local wall time {naive.isoformat()} does not exist in {timezone}; "
            "the clock skips it"
        )
    if len(resolved) > 1:
        raise ValueError(
            f"local wall time {naive.isoformat()} occurs twice in {timezone}; "
            "declare the LocalInstantDeclaration directly with the fold you mean"
        )
    candidate = resolved[0]
    return LocalInstantDeclaration(
        local_date,
        local_time,
        timezone,
        candidate.fold,
        _format_offset(candidate.utcoffset() or timedelta()),
    )


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
