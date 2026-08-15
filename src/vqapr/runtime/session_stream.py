"""Deterministic current-session delivery derived from frozen execution instants."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import overload

from vqapr.domain.timestamps import at_local, require_tz_aware
from vqapr.runtime.events import LocalEvaluationTime, SessionEvent


@dataclass(frozen=True, slots=True)
class SessionStream(Sequence[SessionEvent]):
    """Frozen daily session inputs; Strategy receives its elements one at a time."""

    events: tuple[SessionEvent, ...]

    def __post_init__(self) -> None:
        if not self.events:
            raise ValueError("SessionStream requires at least one execution session")
        if any(not isinstance(event, SessionEvent) for event in self.events):
            raise TypeError("SessionStream accepts SessionEvent values only")
        if tuple(sorted(self.events, key=SessionEvent.sort_key)) != self.events:
            raise ValueError("SessionStream events must be in canonical order")
        sessions = tuple(event.session for event in self.events)
        if len(sessions) != len(set(sessions)):
            raise ValueError("SessionStream requires one execution time per daily session")

    @classmethod
    def from_execution_times(
        cls,
        execution_times: Iterable[datetime],
        *,
        callback_time: LocalEvaluationTime,
    ) -> SessionStream:
        if not isinstance(callback_time, LocalEvaluationTime):
            raise TypeError("callback_time must be a LocalEvaluationTime")

        unique: dict[datetime, datetime] = {}
        for value in execution_times:
            require_tz_aware(value, name="execution_time")
            unique[value.astimezone(UTC)] = value.astimezone(UTC)
        if not unique:
            raise ValueError("SessionStream requires at least one execution time")

        events: list[SessionEvent] = []
        seen_sessions: set[object] = set()
        for execution_time in sorted(unique):
            session = execution_time.astimezone(callback_time.zone).date()
            if session in seen_sessions:
                raise ValueError(
                    f"daily session {session.isoformat()} has more than one execution time"
                )
            seen_sessions.add(session)
            events.append(
                SessionEvent(
                    session=session,
                    evaluation_time=at_local(
                        session,
                        callback_time.wall_time,
                        callback_time.timezone,
                    ),
                    execution_time=execution_time,
                )
            )
        return cls(tuple(events))

    def __iter__(self) -> Iterator[SessionEvent]:
        return iter(self.events)

    def __len__(self) -> int:
        return len(self.events)

    @overload
    def __getitem__(self, index: int) -> SessionEvent: ...

    @overload
    def __getitem__(self, index: slice) -> Sequence[SessionEvent]: ...

    def __getitem__(self, index: int | slice) -> SessionEvent | Sequence[SessionEvent]:
        return self.events[index]
