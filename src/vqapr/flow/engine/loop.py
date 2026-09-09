"""The event loop both kinds of run share: two clocks merged into one ordered walk.

A strategy run and a datamodel run are the same loop (record `148`, owner: *"datamodel은 account
없고 execution 없는 strategy처럼 돌아야 해"*). Since the two-clocks campaign (design §3, record
`206`) the loop has two static sources and no dynamic one: the STRATEGY clock -- the occurrences
frozen at preflight, where a model decides -- and the MARKET clock -- every instant the
execution table has inside the run, where a pending decision fills, the book is valued and the
declared Compliance rules observe it. Both are known in full before the first step, so the walk is
one sorted merge and nothing is minted while it runs: two runs of the same frozen inputs produce the
same traces (architecture 3.2). At one instant the market clock goes first (§3.1: what was
decided earlier is settled and valued before anything new is decided).

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

    def sort_key(self) -> tuple[datetime, int, str]:
        return self.occurrence.sort_key()


@dataclass(frozen=True, slots=True)
class MarketEvent:
    """One instant of the market clock: the execution table has a row here.

    The negative priority orders it before every scheduled occurrence at the same UTC instant
    (design §3.1): the pending intent whose target this is fills, the book is valued and judged,
    and only then does a model decide at this instant.
    """

    instant: datetime

    def __post_init__(self) -> None:
        require_tz_aware(self.instant, name="instant")

    def sort_key(self) -> tuple[datetime, int, str]:
        return (self.instant.astimezone(UTC), -1, "")


class EventLoop[EventT: Event, TraceT, ResultT](ABC):
    """Walk a frozen schedule, handling each event in clock order.

    A subclass gives the constructor its occurrences, its start cutoff and an optional progress
    hook, and implements `handle` (one event in, one trace out) and `finish` (the traces in, the
    result out). `events` is the whole ordered walk; the default is the occurrences alone, and a
    subclass with a market clock merges its instants in. `start` runs once before the first
    event.

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
        require_tz_aware(start_cutoff, name="start_cutoff")
        if on_progress is not None and not callable(on_progress):
            raise TypeError("on_progress must be callable or None")
        self._schedule = occurrences
        self._start_cutoff = start_cutoff
        self._on_progress = on_progress

    @property
    def schedule(self) -> tuple[OperationOccurrence, ...]:
        """The strategy-clock events, in dispatch order."""
        return self._schedule

    def events(self) -> tuple[EventT, ...]:
        """Every event of the walk, in clock order. The occurrences alone, unless overridden."""
        return tuple(OccurrenceEvent(item) for item in self._schedule)  # type: ignore[misc]

    def run(self) -> ResultT:
        """Synchronously process every event of the walk."""
        self.start(self._start_cutoff)
        traces: list[TraceT] = []
        for event in sorted(self.events(), key=lambda item: item.sort_key()):
            # One call per event, for a caller that needs to prove it is still alive while the
            # run is executing. A run's only other outward sign is its result, which arrives
            # minutes later -- long after anything watching would have concluded it had died.
            if self._on_progress is not None:
                self._on_progress()
            traces.append(self.handle(event))
        return self.finish(tuple(traces))

    def start(self, cutoff: datetime) -> None:  # noqa: B027 - a hook, empty by default
        """What happens before the first event; nothing, unless a subclass says otherwise."""

    @abstractmethod
    def handle(self, event: EventT) -> TraceT:
        """Handle one event -- a decision or a market instant -- and return its trace."""

    @abstractmethod
    def finish(self, traces: tuple[TraceT, ...]) -> ResultT:
        """Turn the traces of a completed walk into the loop's result."""


__all__ = ["Event", "EventLoop", "MarketEvent", "OccurrenceEvent"]
