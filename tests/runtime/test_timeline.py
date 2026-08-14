from dataclasses import FrozenInstanceError
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from vqapr.runtime.events import Event, EventKind
from vqapr.runtime.timeline import Timeline

KST = ZoneInfo("Asia/Seoul")
SESSION = date(2024, 3, 6)


def _event(hour: int, minute: int, kind: EventKind) -> Event:
    return Event(datetime(2024, 3, 6, hour, minute, tzinfo=KST), kind, SESSION)


def test_timeline_uses_the_one_fixed_equal_timestamp_order() -> None:
    events = [
        _event(15, 30, EventKind.FINALIZE),
        _event(15, 30, EventKind.MONITORING),
        _event(15, 30, EventKind.VALUATION),
        _event(15, 30, EventKind.FILL_COMMIT),
        _event(15, 30, EventKind.EXECUTION),
        _event(15, 30, EventKind.DECISION),
    ]

    timeline = Timeline.of(events)

    assert [event.kind for event in timeline] == [
        EventKind.DECISION,
        EventKind.EXECUTION,
        EventKind.FILL_COMMIT,
        EventKind.VALUATION,
        EventKind.MONITORING,
        EventKind.FINALIZE,
    ]


def test_data_available_is_not_an_event_kind() -> None:
    assert "DATA_AVAILABLE" not in EventKind.__members__


def test_event_time_exists_without_a_corresponding_data_row() -> None:
    decision = _event(4, 0, EventKind.DECISION)

    timeline = Timeline.of([decision])

    assert timeline.events == (decision,)
    assert timeline.events[0].ts.hour == 4


def test_input_order_does_not_change_the_frozen_timeline() -> None:
    decision = _event(4, 0, EventKind.DECISION)
    execution = _event(15, 30, EventKind.EXECUTION)

    assert Timeline.of([execution, decision]) == Timeline.of([decision, execution])


def test_event_refuses_a_naive_timestamp() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        Event(datetime(2024, 3, 6, 4, 0), EventKind.DECISION, SESSION)


def test_timeline_is_immutable() -> None:
    timeline = Timeline.of([_event(4, 0, EventKind.DECISION)])

    with pytest.raises(FrozenInstanceError):
        timeline.events = ()  # type: ignore[misc]
