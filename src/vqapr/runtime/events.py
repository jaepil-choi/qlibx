"""Current-session runtime events and their one fixed callback priority."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from enum import StrEnum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from vqapr.domain.timestamps import require_tz_aware


class EventKind(StrEnum):
    SESSION = "SESSION"
    DECISION = "DECISION"
    EXECUTION = "EXECUTION"
    FILL_COMMIT = "FILL_COMMIT"
    VALUATION = "VALUATION"
    MONITORING = "MONITORING"
    FINALIZE = "FINALIZE"


_PRIORITY = {kind: priority for priority, kind in enumerate(EventKind)}


def event_priority(kind: EventKind) -> int:
    if not isinstance(kind, EventKind):
        raise TypeError("kind must be an EventKind")
    return _PRIORITY[kind]


@dataclass(frozen=True, slots=True)
class Event:
    ts: datetime
    kind: EventKind
    session: date

    def __post_init__(self) -> None:
        require_tz_aware(self.ts, name="event.ts")
        if not isinstance(self.kind, EventKind):
            raise TypeError("event.kind must be an EventKind")
        if not isinstance(self.session, date) or isinstance(self.session, datetime):
            raise TypeError("event.session must be a date value")

    def sort_key(self) -> tuple[datetime, int, date]:
        return (self.ts.astimezone(UTC), event_priority(self.kind), self.session)


@dataclass(frozen=True, slots=True)
class LocalEvaluationTime:
    """Strategy-owned wall time applied to each current execution session."""

    wall_time: time
    timezone: str

    def __post_init__(self) -> None:
        if not isinstance(self.wall_time, time):
            raise TypeError("wall_time must be a time value")
        if self.wall_time.tzinfo is not None:
            raise ValueError("wall_time must not contain tzinfo")
        if not isinstance(self.timezone, str) or not self.timezone.strip():
            raise ValueError("timezone must be a non-empty IANA timezone name")
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"unknown IANA timezone: {self.timezone!r}") from exc

    @property
    def zone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


@dataclass(frozen=True, slots=True)
class SessionEvent:
    """One current daily execution session; it never contains future sessions."""

    session: date
    evaluation_time: datetime
    execution_time: datetime
    kind: EventKind = field(default=EventKind.SESSION, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.session, date) or isinstance(self.session, datetime):
            raise TypeError("session must be a date value")
        require_tz_aware(self.evaluation_time, name="session.evaluation_time")
        require_tz_aware(self.execution_time, name="session.execution_time")

    def sort_key(self) -> tuple[datetime, int, date]:
        return (
            self.evaluation_time.astimezone(UTC),
            event_priority(self.kind),
            self.session,
        )
