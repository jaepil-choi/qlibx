"""Frozen venue session declarations."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import date, datetime, time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from vqapr.domain.timestamps import at_local


def _validate_wall_time(value: time | None, *, name: str) -> None:
    if value is None:
        return
    if not isinstance(value, time):
        raise TypeError(f"{name} must be a time value")
    if value.tzinfo is not None:
        raise ValueError(f"{name} must be a local wall time without tzinfo")


@dataclass(frozen=True, slots=True)
class SessionCalendar:
    """An immutable set of venue session dates and explicitly declared times."""

    sessions: tuple[date, ...]
    timezone: str
    session_close: time
    session_open: time | None = None

    def __post_init__(self) -> None:
        if not self.sessions:
            raise ValueError("SessionCalendar requires at least one session date")
        if any(not isinstance(day, date) or isinstance(day, datetime) for day in self.sessions):
            raise TypeError("sessions must contain date values, not timestamps")
        if tuple(sorted(set(self.sessions))) != self.sessions:
            raise ValueError("sessions must be sorted and unique")
        if not isinstance(self.timezone, str) or not self.timezone.strip():
            raise ValueError("timezone must be a non-empty IANA timezone name")
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"unknown IANA timezone: {self.timezone!r}") from exc
        if self.session_close is None:
            raise TypeError("session_close must be a time value")
        _validate_wall_time(self.session_close, name="session_close")
        _validate_wall_time(self.session_open, name="session_open")

    @classmethod
    def of(
        cls,
        sessions: Iterable[date],
        *,
        timezone: str,
        session_close: time,
        session_open: time | None = None,
    ) -> SessionCalendar:
        declared = tuple(sessions)
        if any(not isinstance(day, date) or isinstance(day, datetime) for day in declared):
            raise TypeError("sessions must contain date values, not timestamps")
        return cls(
            sessions=tuple(sorted(set(declared))),
            timezone=timezone,
            session_close=session_close,
            session_open=session_open,
        )

    def __iter__(self) -> Iterator[date]:
        return iter(self.sessions)

    def __len__(self) -> int:
        return len(self.sessions)

    def __contains__(self, day: object) -> bool:
        return day in self.sessions

    def at(self, day: date, wall_time: time) -> datetime:
        if day not in self.sessions:
            raise ValueError(f"{day!r} is not a declared session")
        return at_local(day, wall_time, self.timezone)

    def open_at(self, day: date) -> datetime:
        if self.session_open is None:
            raise ValueError("session_open was not declared")
        return self.at(day, self.session_open)

    def close_at(self, day: date) -> datetime:
        return self.at(day, self.session_close)
