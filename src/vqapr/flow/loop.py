"""The event loop both kinds of run share: a static schedule merged with the due events it mints.

A strategy run and a datamodel run are the same loop (record `148`, owner: *"datamodel은 account
없고 execution 없는 strategy처럼 돌아야 해"*). Two sources of events feed it -- the occurrences
frozen at preflight, known in full before the first step, and the due items a callback mints
while the run executes -- and a single clock orders them: the loop advances to the earliest event
either source holds, hands it to the subclass, and lets the handler leave a new due event
behind. That is a discrete-event simulation loop, and `EventLoop` is its name (owner ruling,
2026-09-08; the review in `docs/code-review/2026-09-08-four-readers-one-loop-and-the-missing-
shapes.md` §2).

What the two kinds differ in is typed here rather than left to `object`: the event a loop
handles, the trace a handled event leaves, and the result a finished loop returns are its three
type parameters, and `handle`/`finish` are abstract. A subclass that forgets one does not start;
a subclass that returns the wrong thing is a type error rather than a runtime `assert`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from vqapr.domain.agendas import OperationOccurrence
from vqapr.domain.values import require_tz_aware


class Event(Protocol):
    """Anything the loop can order: it has a place on the one clock."""

    def sort_key(self) -> tuple[datetime, int, str]: ...


@dataclass(frozen=True, slots=True)
class OccurrenceEvent:
    """A scheduled occurrence: one entry of the frozen agenda, known before the loop starts."""

    occurrence: OperationOccurrence

    def __post_init__(self) -> None:
        if not isinstance(self.occurrence, OperationOccurrence):
            raise TypeError("occurrence must be an OperationOccurrence")

    def sort_key(self) -> tuple[datetime, int, str]:
        return self.occurrence.sort_key()


@dataclass(frozen=True, slots=True)
class DueEvent:
    """A due item a handler minted: the instant a pending intent or valuation falls due.

    The negative priority deliberately orders an already-pending execution before every
    scheduled occurrence at the same UTC instant: what was decided earlier is settled before
    anything new is decided at that instant.
    """

    due_time: datetime
    pending_id: str

    def __post_init__(self) -> None:
        require_tz_aware(self.due_time, name="due_time")
        if not isinstance(self.pending_id, str) or not self.pending_id:
            raise ValueError("pending_id must be a non-empty string")

    def sort_key(self) -> tuple[datetime, int, str]:
        return (self.due_time.astimezone(UTC), -1, self.pending_id)


class EventLoop[EventT: Event, TraceT, ResultT](ABC):
    """Walk a frozen schedule, handling each scheduled event and every due event between them.

    A subclass gives the constructor its schedule, its start cutoff and an optional progress
    hook, and implements `handle` (one event in, one trace out) and `finish` (the traces in, the
    result out). `pending` returns the earliest due event the subclass's queue holds; a loop
    that never mints one keeps the default and is then the plain sequence of occurrences.
    `start` runs once before the first event.

    The walk itself is written once, here, and is not overridable: the merge order is what makes
    two runs of the same frozen inputs produce the same traces (architecture 3.2).
    """

    def __init__(
        self,
        *,
        schedule: Sequence[OperationOccurrence],
        start_cutoff: datetime,
        on_progress: Callable[[], None] | None = None,
    ) -> None:
        occurrences = tuple(schedule)
        if any(not isinstance(item, OperationOccurrence) for item in occurrences):
            raise TypeError("schedule must contain OperationOccurrence values")
        require_tz_aware(start_cutoff, name="start_cutoff")
        if on_progress is not None and not callable(on_progress):
            raise TypeError("on_progress must be callable or None")
        self._schedule = occurrences
        self._start_cutoff = start_cutoff
        self._on_progress = on_progress

    @property
    def schedule(self) -> tuple[OperationOccurrence, ...]:
        """The static events, in dispatch order."""
        return self._schedule

    def run(self) -> ResultT:
        """Synchronously process the schedule and every due event in its horizon."""
        self.start(self._start_cutoff)
        traces: list[TraceT] = []
        static = iter(OccurrenceEvent(item) for item in self._schedule)
        next_static = next(static, None)

        while next_static is not None or self.pending() is not None:
            # One call per event, for a caller that needs to prove it is still alive while the
            # run is executing. A run's only other outward sign is its result, which arrives
            # minutes later -- long after anything watching would have concluded it had died.
            if self._on_progress is not None:
                self._on_progress()
            due = self.pending()
            if due is not None and (
                next_static is None or due.sort_key() <= next_static.sort_key()
            ):
                traces.append(self.handle(due))  # type: ignore[arg-type]
                continue
            assert next_static is not None
            event = next_static
            next_static = next(static, None)
            traces.append(self.handle(event))  # type: ignore[arg-type]

        return self.finish(tuple(traces))

    def start(self, cutoff: datetime) -> None:  # noqa: B027 - a hook, empty by default
        """What happens before the first event; nothing, unless a subclass says otherwise."""

    def pending(self) -> DueEvent | None:
        """The earliest due event waiting, or `None`; a loop without fills has none."""
        return None

    @abstractmethod
    def handle(self, event: EventT) -> TraceT:
        """Handle one event -- scheduled or due -- and return its trace."""

    @abstractmethod
    def finish(self, traces: tuple[TraceT, ...]) -> ResultT:
        """Turn the traces of a completed walk into the loop's result."""


__all__ = ["DueEvent", "Event", "EventLoop", "OccurrenceEvent"]
