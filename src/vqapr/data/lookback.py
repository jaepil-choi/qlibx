"""Past-only lookback declarations used by observation queries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from vqapr.domain.timestamps import at_local, require_tz_aware, shift_calendar


@dataclass(frozen=True, slots=True)
class RowsLookback:
    rows: int

    def __post_init__(self) -> None:
        if not isinstance(self.rows, int) or isinstance(self.rows, bool):
            raise TypeError("rows lookback must be an integer")
        if self.rows <= 0:
            raise ValueError("rows lookback must be positive")


@dataclass(frozen=True, slots=True)
class CalendarLookback:
    years: int = 0
    months: int = 0
    days: int = 0
    timezone: str = "UTC"

    def __post_init__(self) -> None:
        for name, value in (("years", self.years), ("months", self.months), ("days", self.days)):
            if not isinstance(value, int) or isinstance(value, bool):
                raise TypeError(f"calendar lookback {name} must be an integer")
            if value < 0:
                raise ValueError(f"calendar lookback {name} must be non-negative")
        if self.years == self.months == self.days == 0:
            raise ValueError("calendar lookback requires at least one positive amount")
        if not isinstance(self.timezone, str) or not self.timezone.strip():
            raise ValueError("timezone must be a non-empty IANA timezone name")
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as error:
            raise ValueError(f"unknown IANA timezone: {self.timezone!r}") from error

    def lower_bound(self, evaluation_time: datetime) -> datetime:
        """Return the clamped local calendar date at 00:00."""
        current = require_tz_aware(evaluation_time, name="evaluation_time").astimezone(
            ZoneInfo(self.timezone)
        )
        shifted = shift_calendar(
            current,
            years=-self.years,
            months=-self.months,
            days=-self.days,
        )
        return at_local(shifted.date(), time(0), self.timezone)


type Lookback = RowsLookback | CalendarLookback
