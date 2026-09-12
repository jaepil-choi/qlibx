"""The events of a run's one walk, and the order they take at a shared instant.

A run walks two static clocks merged into one ordered sequence (design §3, record `206`): the
SCHEDULE clock -- the events frozen at preflight, where a model decides -- and the MARKET
clock -- every instant the execution table has inside the run, where a pending decision fills,
the book is valued and the declared Compliance rules observe it. Both are known in full before
the first step, so nothing is minted while the run walks and two runs of the same frozen inputs
produce the same traces (architecture 3.2). At one instant the market clock goes first (§3.1:
what was decided earlier is settled and valued before anything new is decided) -- that rule is
`MarketEvent.sort_key`'s priority, and it lives here because it is a fact about the events.

The walk itself is `run/engine/loop.py::RunLoop.run`. Until record `231` an abstract `EventLoop`
stood here with `RunLoop` as its only subclass (`docs/issues/097`); the walk moved to the one
class that walks.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from vqapr.domain.instants import require_tz_aware


class Event(Protocol):
    """Anything the loop can order: it has a place on the one clock. A scheduled event is the
    domain's `ScheduledEvent` itself, which already knows its place; a market instant is a
    `MarketEvent`."""

    def sort_key(self) -> tuple[datetime, int, str]: ...


@dataclass(frozen=True, slots=True)
class MarketEvent:
    """One instant of the market clock: the execution table has a row here.

    The negative priority orders it before every scheduled event at the same UTC instant
    (design §3.1): the pending intent whose target this is fills, the book is valued and judged,
    and only then does a model decide at this instant.
    """

    instant: datetime

    def __post_init__(self) -> None:
        require_tz_aware(self.instant, name="instant")

    def sort_key(self) -> tuple[datetime, int, str]:
        return (self.instant.astimezone(UTC), -1, "")


__all__ = ["Event", "MarketEvent"]
