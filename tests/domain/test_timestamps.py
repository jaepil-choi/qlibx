from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from vqapr.domain.instants import at_local, require_tz_aware, shift_calendar


def test_require_tz_aware_rejects_a_naive_datetime() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        require_tz_aware(datetime(2024, 3, 6, 4, 0))


def test_at_local_builds_an_aware_timestamp_in_the_declared_timezone() -> None:
    value = at_local(date(2024, 3, 6), time(4, 0), "Asia/Seoul")

    assert value == datetime(2024, 3, 6, 4, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    assert value.tzinfo.key == "Asia/Seoul"


@pytest.mark.parametrize(
    ("day", "wall_time", "message"),
    [
        (date(2024, 3, 10), time(2, 30), "does not exist"),
        (date(2024, 11, 3), time(1, 30), "ambiguous"),
    ],
)
def test_at_local_refuses_dst_gaps_and_folds(day: date, wall_time: time, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        at_local(day, wall_time, "America/New_York")


def test_at_local_refuses_a_time_that_carries_another_timezone() -> None:
    with pytest.raises(ValueError, match="wall time"):
        at_local(date(2024, 3, 6), time(4, 0, tzinfo=ZoneInfo("UTC")), "Asia/Seoul")


def test_shift_calendar_clamps_month_end_and_preserves_local_time() -> None:
    source = datetime(2024, 3, 31, 4, 0, tzinfo=ZoneInfo("Asia/Seoul"))

    shifted = shift_calendar(source, months=-1)

    assert shifted == datetime(2024, 2, 29, 4, 0, tzinfo=ZoneInfo("Asia/Seoul"))
