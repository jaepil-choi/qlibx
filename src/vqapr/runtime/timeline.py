"""A deterministic frozen event sequence, not a clock."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from typing import overload

from vqapr.runtime.events import Event


@dataclass(frozen=True, slots=True)
class Timeline(Sequence[Event]):
    events: tuple[Event, ...]

    def __post_init__(self) -> None:
        if any(not isinstance(event, Event) for event in self.events):
            raise TypeError("Timeline accepts Event values only")
        if tuple(sorted(self.events, key=Event.sort_key)) != self.events:
            raise ValueError("Timeline events must already be in canonical order; use Timeline.of")

    @classmethod
    def of(cls, events: Iterable[Event]) -> Timeline:
        supplied = tuple(events)
        if any(not isinstance(event, Event) for event in supplied):
            raise TypeError("Timeline accepts Event values only")
        return cls(tuple(sorted(supplied, key=Event.sort_key)))

    def __iter__(self) -> Iterator[Event]:
        return iter(self.events)

    def __len__(self) -> int:
        return len(self.events)

    @overload
    def __getitem__(self, index: int) -> Event: ...

    @overload
    def __getitem__(self, index: slice) -> Sequence[Event]: ...

    def __getitem__(self, index: int | slice) -> Event | Sequence[Event]:
        return self.events[index]
