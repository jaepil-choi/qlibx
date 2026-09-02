"""Past-only lookback declarations used by observation queries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from vqapr.domain.timestamps import at_local, require_tz_aware, shift_calendar


@dataclass(frozen=True, slots=True)
class RowsLookback:
    """The last `rows` rows of the pivoted table: the same instants for every name.

    **A panel lookback** (design §2.4, owner ruling 2026-09-01): on a `grain: instrument_instant`
    or `grain: instant` dataset a row is one instant shared by every name, so `RowsLookback(313)`
    is 313 instants, and a name that stopped publishing simply contributes fewer values inside
    that window rather than reaching further back than everyone else. The batch's calendar span
    is bounded by the table, not by its sparsest name -- which is what makes a cross-section built
    from it safe. `docs/issues/033` measured the other meaning: 1,637 names, `rows=313`, and a
    batch spanning 1,865 sessions because a name delisted in 2019 still got its own last 313.

    **That other meaning still exists, under its own name.** `InstantsLookback(n)` is each name's
    own last n reported instants, per field, and it belongs to `grain: rows` -- the vendor's long
    table, where no row is shared between names. Registration and the read path refuse each on
    the other grain, so the same number cannot silently mean two things (§7-1, §7-3).

    Use this for anything cross-sectional or aligned on instants. Use `CalendarLookback` when the
    question is a calendar period rather than a count of instants.
    """

    rows: int

    def __post_init__(self) -> None:
        if not isinstance(self.rows, int) or isinstance(self.rows, bool):
            raise TypeError("rows lookback must be an integer")
        if self.rows <= 0:
            raise ValueError("rows lookback must be positive")


@dataclass(frozen=True, slots=True)
class InstantsLookback:
    """The last `instants` observations of **each instrument independently**.

    Per name, per field, counting only non-null values: a field's rank is computed inside its own
    instrument's partition, so a name that reports twice a week and one that reports daily both
    return `instants` values, from different dates. This was `RowsLookback`'s meaning until the
    lookback types followed the grain (design §2.4); it is the right question for a long,
    vendor-grain table -- quarterly statements where every item has its own publication date --
    and it belongs there: `grain: rows` only.

    **The batch's calendar span is therefore set by the sparsest instrument, and is unbounded
    above.** That is the property a cross-sectional model must not meet, and the type keeps it
    away from one: a panel grain refuses this lookback by name.
    """

    instants: int

    def __post_init__(self) -> None:
        if not isinstance(self.instants, int) or isinstance(self.instants, bool):
            raise TypeError("instants lookback must be an integer")
        if self.instants <= 0:
            raise ValueError("instants lookback must be positive")


@dataclass(frozen=True, slots=True)
class CalendarLookback:
    """Every observation from a calendar bound back to the evaluation time, for every instrument.

    The bound is the local calendar date at 00:00 in `timezone`, shifted back by the declared
    amount -- so the window is one period, identical for every name, and a sparse instrument simply
    contributes fewer rows inside it rather than reaching further back than everyone else.

    This is the member a cross-sectional model wants, and the one nothing steered anybody towards:
    `RowsLookback` is what `vqapr new datamodel --lookback` emitted, and until 2026-08-30 neither
    class had a docstring and neither was named in the skill (`docs/issues/033`). Pass
    `--calendar-lookback DAYS` to scaffold this one.

    Calendar days, not sessions: `days=7` spans one week including the weekend, so a lookback that
    must guarantee N trading days needs the padding for holidays that any calendar bound implies.
    """

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


type PanelLookback = RowsLookback | CalendarLookback
"""What a panel grain (`instrument_instant`, `instant`) takes: a count of the table's rows, or a
calendar period. Both give every name the same window."""

type SeriesLookback = InstantsLookback
"""What `grain: rows` takes: each name's own last N reported instants."""

type Lookback = PanelLookback | SeriesLookback

