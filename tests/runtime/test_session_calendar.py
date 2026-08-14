from dataclasses import FrozenInstanceError
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from vqapr.runtime.session_calendar import SessionCalendar


def test_calendar_is_a_frozen_sorted_session_set_with_explicit_time() -> None:
    calendar = SessionCalendar.of(
        [date(2024, 3, 6), date(2024, 3, 5), date(2024, 3, 5)],
        timezone="Asia/Seoul",
        session_open=time(9, 0),
        session_close=time(15, 30),
    )

    assert calendar.sessions == (date(2024, 3, 5), date(2024, 3, 6))
    assert calendar.close_at(date(2024, 3, 6)) == datetime(
        2024, 3, 6, 15, 30, tzinfo=ZoneInfo("Asia/Seoul")
    )
    with pytest.raises(FrozenInstanceError):
        calendar.timezone = "UTC"  # type: ignore[misc]


def test_calendar_does_not_invent_an_open_time() -> None:
    calendar = SessionCalendar.of(
        [date(2024, 3, 5)],
        timezone="Asia/Seoul",
        session_close=time(15, 30),
    )

    assert calendar.session_open is None
    with pytest.raises(ValueError, match="not declared"):
        calendar.open_at(date(2024, 3, 5))


def test_calendar_refuses_an_empty_session_set() -> None:
    with pytest.raises(ValueError, match="at least one"):
        SessionCalendar.of([], timezone="Asia/Seoul", session_close=time(15, 30))


def test_calendar_requires_an_explicit_close_time() -> None:
    with pytest.raises(TypeError, match="session_close"):
        SessionCalendar.of(
            [date(2024, 3, 5)],
            timezone="Asia/Seoul",
            session_close=None,  # type: ignore[arg-type]
        )


def test_calendar_refuses_a_timezone_attached_to_a_wall_time() -> None:
    with pytest.raises(ValueError, match="wall time"):
        SessionCalendar.of(
            [date(2024, 3, 5)],
            timezone="Asia/Seoul",
            session_close=time(15, 30, tzinfo=ZoneInfo("UTC")),
        )


def test_calendar_rejects_a_timestamp_disguised_as_a_session_date() -> None:
    with pytest.raises(TypeError, match="date values"):
        SessionCalendar.of(
            [datetime(2024, 3, 5, 15, 30)],
            timezone="Asia/Seoul",
            session_close=time(15, 30),
        )
