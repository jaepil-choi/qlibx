"""Finite operation schedule declarations.

Moved from `runtime/agendas.py` (one-shape Step 7, record 162): an event is a value a Model
is handed (`calls.py` imports it), so it lives with the other values, below `flow/`.

Agendas are resolved input, never a recurrence or calendar source.  Their local
clock proof is retained with each event so the canonical UTC ordering is
reproducible across timezone transitions.

**An event has no role and an schedule no provenance** (record `182`). Both were the clothes
of the time an schedule was a registered declaration one of three roles could own; since record
`148` the one schedule is derived from the run, every run kind walks the same events, and
what an event dispatches to is decided by the loop that handles it (`flow/loop.py`), not
by a field on the event. The role priority that ordered events of different roles at
one instant had no reachable input -- an schedule is single-role by construction -- and
`provenance` was computed, verified and carried with no reader
(`docs/code-review/2026-09-08-the-agenda-carries-a-role-nobody-chose.md`).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from vqapr.domain.identifiers import EventId, ScheduleId, event_id
from vqapr.domain.instants import LocalInstantDeclaration, declare_local_instant, require_tz_aware

SCHEDULED_PRIORITY = 0
"""The second term of a scheduled event's sort key. A due event (`flow/loop.py`) sorts at
`-1`, ahead of every event at the same instant: what was decided earlier is settled before
anything new is decided there."""


def _identity(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _require_timezone(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("timezone must be a non-empty IANA timezone name")
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"unknown IANA timezone: {value!r}") from exc
    return value


def _require_identifier(value: str, *, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if not value or value != value.strip() or any(character.isspace() for character in value):
        raise ValueError(f"{name} must be a non-empty identifier without whitespace")
    return value


_EVERY = re.compile(r"^(?P<count>[1-9]\d*)(?P<unit>[mhdwM])$")
DAY_UNITS = frozenset({"d", "w", "M"})
INTRADAY_UNITS = frozenset({"m", "h"})
GROUP_UNITS = frozenset({"w", "M"})
ANCHORS = ("first", "last")


@dataclass(frozen=True, slots=True)
class ScheduleRule:
    """The schedule clock as a person writes it: a trading-day filter and a within-day rule.

    Design §3.4. `every` is a count and a unit -- `1d`, `2d`, `1w`, `1M` select trading DAYS
    (every Nth trading day; the first trading day of every Nth ISO week; of every Nth calendar
    month) and pair with `at`, one or more wall times on each selected day. `1m`, `5m`, `1h`
    select INSTANTS inside every trading day, from `from_time` to `to_time` inclusive, and refuse
    `at`. Which days are trading days is not this value's to know: it is handed them, resolved
    from data (§3.3), and does only arithmetic on top -- so nothing here is a guess about a
    market.

    `on` picks WHICH trading day of each week or month a `w` or `M` rule fires on: `first`, the
    default, or `last` (record `253`). Month-end rebalancing had no spelling, and three agents
    given "rebalance on the last trading day of each month" declared it three different ways,
    moving the fill between month-end close, next-day open and next-day close
    (`docs/issues/report-2026-09-11-an-agenda-cannot-fire-on-the-last-trading-day-of-a-month.md`).
    The trading days are the table's, known before the run as every schedule's are, so `last` asks
    nothing of the future that `1d` does not.
    """

    every: str
    at: tuple[time, ...] = ()
    from_time: time | None = None
    to_time: time | None = None
    on: str = "first"

    def __post_init__(self) -> None:
        if not isinstance(self.every, str) or not _EVERY.match(self.every):
            # The grammar, not examples: a refusal that listed `1d, 1w, 1M, 5m or 1h` beside a
            # refused `1y` read as the closed set of accepted values, and a reader who wanted a
            # yearly cadence moved the schedule into the model instead of writing `12M`
            # (`docs/issues/report-2026-09-10-agenda-has-no-year-unit-...`).
            hint = ""
            if isinstance(self.every, str) and self.every[-1:] in ("y", "Y"):
                hint = "; there is no year unit, a yearly cadence is 12M"
            raise ValueError(
                "every is a count and a unit -- the count is any positive integer; the unit is "
                "d, w or M to select trading days (every Nth trading day, the first trading day of "
                "every Nth ISO week or Nth calendar month -- or the last, with `on: last`: 2d, "
                "1w, 3M, 12M) or m, h to select instants inside each day (5m, 1h); "
                f"got {self.every!r}{hint}"
            )
        if self.on not in ANCHORS:
            raise ValueError(
                "on is first or last: which trading day of each week or month a w or M rule "
                f"fires on; got {self.on!r}"
            )
        if self.on != "first" and self.unit not in GROUP_UNITS:
            raise ValueError(
                f"on: {self.on} picks a trading day of each week or month, so it pairs with a w "
                f"or M rule; every {self.every} has no week or month to be {self.on} in"
            )
        at = tuple(self.at)
        for value in (*at, self.from_time, self.to_time):
            if value is not None and (not isinstance(value, time) or value.tzinfo is not None):
                raise ValueError("schedule wall times must be timezone-naive datetime.time values")
        if self.intraday:
            if at:
                raise ValueError(
                    f"every {self.every} selects instants inside the day; declare from/to, not at"
                )
            if self.from_time is None or self.to_time is None:
                raise ValueError(
                    f"every {self.every} needs from and to, the window inside each trading day"
                )
            if self.from_time > self.to_time:
                raise ValueError("from must not be later than to")
        else:
            if self.from_time is not None or self.to_time is not None:
                raise ValueError(f"every {self.every} selects days; declare at, not from/to")
            if not at:
                raise ValueError(
                    f"every {self.every} needs at: the wall time(s) on each selected day"
                )
            if len(set(at)) != len(at):
                raise ValueError("at must not repeat a wall time")
        object.__setattr__(self, "at", tuple(sorted(at)))

    @property
    def count(self) -> int:
        match = _EVERY.match(self.every)
        assert match is not None
        return int(match.group("count"))

    @property
    def unit(self) -> str:
        return self.every[-1]

    @property
    def intraday(self) -> bool:
        return self.unit in INTRADAY_UNITS

    def select_days(self, days: Sequence[date]) -> tuple[date, ...]:
        """The trading days this rule fires on, out of the sorted trading days it is handed.

        `on: last` picks the last day of each week or month the days show to be OVER: one a later
        handed day follows, or one falling on its group's last calendar day. A table that stops
        mid-month does not say whether that month had more sessions, so its final group does not
        fire rather than firing on a day that may not be the last (record `253`). A caller that
        wants every month inside a run hands days past the run's end and cuts after
        (`Schedule.expand(through=...)`).
        """
        if self.unit in ("d", "m", "h"):
            return tuple(days[:: self.count]) if self.unit == "d" else tuple(days)
        groups: dict[object, list[date]] = {}
        for day in days:
            groups.setdefault(self._group(day), []).append(day)
        members = list(groups.values())
        picked: list[date] = []
        for index, group in enumerate(members):
            if self.on == "first":
                picked.append(group[0])
            elif index + 1 < len(members) or self._group(group[-1] + timedelta(days=1)) != (
                self._group(group[-1])
            ):
                picked.append(group[-1])
        return tuple(picked[:: self.count])

    def _group(self, day: date) -> object:
        """The ISO week or the calendar month `day` belongs to, by this rule's unit."""
        return day.isocalendar()[:2] if self.unit == "w" else (day.year, day.month)

    def times(self) -> tuple[time, ...]:
        """The wall times on one selected day, in order."""
        if not self.intraday:
            return self.at
        assert self.from_time is not None and self.to_time is not None
        step = timedelta(minutes=self.count) if self.unit == "m" else timedelta(hours=self.count)
        anchor = datetime(2000, 1, 1)
        cursor = datetime.combine(anchor.date(), self.from_time)
        last = datetime.combine(anchor.date(), self.to_time)
        out: list[time] = []
        while cursor <= last:
            out.append(cursor.time())
            cursor += step
        return tuple(out)

    def describe(self) -> str:
        if self.intraday:
            assert self.from_time is not None and self.to_time is not None
            return (
                f"every {self.every} from {self.from_time.isoformat()} to "
                f"{self.to_time.isoformat()} on each trading day"
            )
        when = ", ".join(value.isoformat() for value in self.at)
        anchor = " on the last trading day" if self.on == "last" else ""
        return f"every {self.every}{anchor} at {when}"


@dataclass(frozen=True, slots=True)
class ScheduledEvent:
    event_id: EventId
    local_instant: LocalInstantDeclaration
    _content_identity: str = field(default="", init=False, repr=False, compare=False)
    """Memo for `content_identity`, which is derived from frozen fields and cannot change.

    Deriving it costs a json encode and a sha256. `FrozenRun.identity` re-derives it for every
    event of every schedule on each access, and a run reads that identity about sixteen times
    per callback, so recomputing made the run quadratic in its own length. Kept lazy rather than
    computed in `__post_init__` because decoding a workspace builds every event and never
    asks any of them for an identity.
    """

    def __post_init__(self) -> None:
        _require_identifier(self.event_id, name="event_id")

    @property
    def evaluation_time(self) -> datetime:
        return self.local_instant.instant

    @property
    def utc_evaluation_time(self) -> datetime:
        return self.local_instant.utc_instant

    @property
    def content_identity(self) -> str:
        if not self._content_identity:
            object.__setattr__(
                self,
                "_content_identity",
                _identity(
                    {
                        "event_id": self.event_id,
                        "local_instant": self.local_instant.identity(),
                    }
                ),
            )
        return self._content_identity

    def sort_key(self) -> tuple[datetime, int, str]:
        return (self.utc_evaluation_time, SCHEDULED_PRIORITY, self.event_id)


@dataclass(frozen=True, slots=True)
class Schedule:
    schedule_id: ScheduleId
    timezone: str
    events: tuple[ScheduledEvent, ...]
    _content_identity: str = field(default="", init=False, repr=False, compare=False)
    """Memo for the derived identity. See `ScheduledEvent._content_identity`."""

    def __post_init__(self) -> None:
        _require_identifier(self.schedule_id, name="schedule_id")
        _require_timezone(self.timezone)
        events = tuple(self.events)
        if any(event.local_instant.timezone != self.timezone for event in events):
            raise ValueError("every event timezone must match the schedule timezone")
        event_ids = [event.event_id for event in events]
        if len(set(event_ids)) != len(event_ids):
            raise ValueError("event_id values must be unique within an schedule")
        object.__setattr__(
            self,
            "events",
            tuple(sorted(events, key=ScheduledEvent.sort_key)),
        )

    @property
    def content_identity(self) -> str:
        if not self._content_identity:
            object.__setattr__(
                self,
                "_content_identity",
                _identity(
                    {
                        "timezone": self.timezone,
                        "events": [
                            event.content_identity for event in self.events
                        ],
                    }
                ),
            )
        return self._content_identity

    def inclusive_slice(self, start: datetime, end: datetime) -> tuple[ScheduledEvent, ...]:
        require_tz_aware(start, name="start")
        require_tz_aware(end, name="end")
        start_utc = start.astimezone(UTC)
        end_utc = end.astimezone(UTC)
        if start_utc > end_utc:
            raise ValueError("start must not be after end")
        return tuple(
            event
            for event in self.events
            if start_utc <= event.utc_evaluation_time <= end_utc
        )

    @classmethod
    def expand(
        cls,
        *,
        schedule_id: ScheduleId,
        days: Iterable[datetime | date],
        rule: ScheduleRule,
        timezone: str,
        through: date | None = None,
    ) -> Schedule:
        """Resolve a rule over the trading days it is handed into a finite, ordered schedule.

        Design §3.4: the declaration is a trading-day filter plus a within-day rule, preflight
        expands it over the days the execution table has rows for, and the result is what the
        run consumes from then on. `days` accepts the instants `Workspace.evaluation_times`
        returns; only their venue-local date is used, each day once. The event id is
        `{schedule_id}-{date}T{HHMM}` -- one scheme for one and for many instants a day. A wall
        time that does not exist, or happens twice, on any selected day is refused rather than
        resolved by guess (`declare_local_instant`).

        `through` keeps the days selected on or before it: an `on: last` rule is handed days past
        the run's end, which say whether its last month is over, and fires on none of them.
        """
        zone = ZoneInfo(timezone)
        seen: set[date] = set()
        ordered: list[date] = []
        for session in days:
            if isinstance(session, datetime):
                day = (
                    session.astimezone(zone).date()
                    if session.tzinfo is not None
                    else session.date()
                )
            elif isinstance(session, date):
                day = session
            else:
                raise TypeError("days must contain datetime or date values")
            if day not in seen:
                seen.add(day)
                ordered.append(day)
        ordered.sort()
        times = rule.times()
        events = tuple(
            ScheduledEvent(
                event_id(f"{schedule_id}-{day.isoformat()}T{at.strftime('%H%M')}"),
                declare_local_instant(day, at, timezone),
            )
            for day in rule.select_days(ordered)
            if through is None or day <= through
            for at in times
        )
        return cls(schedule_id=schedule_id, timezone=timezone, events=events)

    @classmethod
    def daily(
        cls,
        *,
        schedule_id: ScheduleId,
        sessions: Iterable[datetime | date],
        at: time,
        timezone: str,
    ) -> Schedule:
        """One event per session, at the same venue-local wall time: `expand` with `1d`.

        The constructor takes events that are already known. The common case is not a list --
        it is "every session this registered dataset has, at 08:00 local", and turning one into
        the other is mechanical work that was being written by hand at every call site.

        Three things stop being the caller's to get right:

        - **The event id.** Derived as ``{schedule_id}-{date}``. Two call sites inventing
          slightly different id schemes produce different identities for the same session, and a
          replay stops being comparable to the run it replays.
        - **fold and offset.** Derived from the zone rather than typed as constants. A hand-written
          ``0`` and ``"+09:00"`` is correct until the venue observes DST, after which it is wrong
          twice a year and right on every day anyone tests.
        - **Duplicate sessions.** A dataset can carry several rows for one day; the schedule takes
          the day once.

        `sessions` accepts datetimes, so the sessions a dataset actually has can be passed
        straight through from ``Workspace.evaluation_times``. Only their venue-local date is used:
        the time of day comes from ``at``, because when a row became available and when a decision
        is made are different facts.

        A wall time that does not exist, or happens twice, on any session is refused rather than
        resolved by guess. There is no remedy inside the run declaration: a run names one `at` for
        every session, so a venue whose clock skips or repeats that wall time on some day needs a
        different `at`, or sessions that avoid the day.
        """
        return cls.expand(
            schedule_id=schedule_id,
            days=sessions,
            rule=ScheduleRule("1d", (at,)),
            timezone=timezone,
        )
