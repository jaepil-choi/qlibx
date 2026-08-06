"""Deterministic clock primitives."""

import heapq
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import NamedTuple, Protocol


def require_aware(timestamp: datetime) -> datetime:
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("clock timestamps must be timezone-aware")
    return timestamp.astimezone(UTC)


class Clock(Protocol):
    @property
    def now(self) -> datetime: ...

    def schedule(self, event: "Event", callback: Callable[["Event"], None]) -> None: ...

    def advance_to_next(self) -> list["Handler"]: ...

    def is_finished(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class Event:
    name: str
    ts: datetime
    priority: int
    payload: object | None = None


class Handler(NamedTuple):
    event: Event
    callback: Callable[[Event], None]


class BacktestClock:
    """Explicit, monotonically advancing simulation clock."""

    def __init__(self, start: datetime) -> None:
        self._now = require_aware(start)
        self._queue: list[
            tuple[datetime, int, int, Event, Callable[[Event], None]]
        ] = []
        self._sequence = 0

    @property
    def now(self) -> datetime:
        return self._now

    def advance_to(self, timestamp: datetime) -> None:
        selected = require_aware(timestamp)
        if selected < self._now:
            raise ValueError("clock cannot move backwards")
        self._now = selected

    def schedule(self, event: Event, callback: Callable[[Event], None]) -> None:
        timestamp = require_aware(event.ts)
        if timestamp < self._now:
            raise ValueError("cannot schedule an event before clock.now")
        normalized = Event(event.name, timestamp, event.priority, event.payload)
        heapq.heappush(
            self._queue,
            (timestamp, event.priority, self._sequence, normalized, callback),
        )
        self._sequence += 1

    def advance_to_next(self) -> list[Handler]:
        if not self._queue:
            return []
        timestamp = self._queue[0][0]
        self._now = timestamp
        handlers: list[Handler] = []
        while self._queue and self._queue[0][0] == timestamp:
            _, _, _, event, callback = heapq.heappop(self._queue)
            handlers.append(Handler(event, callback))
        return handlers

    def is_finished(self) -> bool:
        return not self._queue
