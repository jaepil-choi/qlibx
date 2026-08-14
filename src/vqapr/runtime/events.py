"""Frozen runtime events and their one fixed priority."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum

from vqapr.domain.timestamps import require_tz_aware


class EventKind(StrEnum):
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
