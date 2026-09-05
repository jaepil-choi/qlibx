from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from vqapr.data.lookback import CalendarLookback, RowsLookback
from vqapr.data.requirements import DataRequirement


def test_rows_lookback_requires_a_positive_integer() -> None:
    with pytest.raises(ValueError, match="positive"):
        RowsLookback(0)
    with pytest.raises(TypeError, match="integer"):
        RowsLookback(True)


def test_calendar_lookback_is_past_only_and_requires_a_timezone() -> None:
    with pytest.raises(ValueError, match="at least one"):
        CalendarLookback(timezone="Asia/Seoul")
    with pytest.raises(ValueError, match="non-negative"):
        CalendarLookback(days=-1, timezone="Asia/Seoul")
    with pytest.raises(ValueError, match="unknown IANA"):
        CalendarLookback(days=1, timezone="Not/AZone")


def test_calendar_lower_bound_is_local_midnight_with_month_end_clamping() -> None:
    lookback = CalendarLookback(months=1, timezone="Asia/Seoul")
    evaluation_time = datetime(2024, 3, 31, 16, tzinfo=ZoneInfo("Asia/Seoul"))

    assert lookback.lower_bound(evaluation_time) == datetime(
        2024, 2, 29, 0, tzinfo=ZoneInfo("Asia/Seoul")
    )


def test_a_requirement_is_a_dataset_a_field_and_a_lookback() -> None:
    """The pair is the id, and the consumer is not part of it.

    `049`'s ruling removed `dataset_id` on the grounds that a field id is unique across a
    workspace. Measured against the research environment that premise did not hold -- 21 of its 27
    datasets' field ids are shared -- and the owner overturned that half on 2026-09-01. The
    `consumer_id` half stands: the framework stamps it.
    """
    requirement = DataRequirement.of("price_daily", "close", lookback=RowsLookback(2))

    assert str(requirement.dataset_id) == "price_daily"
    assert requirement.field_id == "close"
    assert requirement.lookback == RowsLookback(2)
    assert not hasattr(requirement, "consumer_id")


def test_requirement_rejects_a_field_that_is_not_a_name() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        DataRequirement.of("price_daily", "", lookback=RowsLookback(2))
    with pytest.raises(ValueError, match="non-empty"):
        DataRequirement.of("price_daily", "two words", lookback=RowsLookback(2))
    with pytest.raises(TypeError, match="string"):
        DataRequirement.of("price_daily", None, lookback=RowsLookback(2))


def test_requirement_rejects_a_name_the_window_owns() -> None:
    for reserved in ("available_at", "instrument"):
        with pytest.raises(ValueError, match="reserved"):
            DataRequirement.of("price_daily", reserved, lookback=RowsLookback(2))


def test_requirement_rejects_a_lookback_that_is_not_one() -> None:
    with pytest.raises(TypeError, match="RowsLookback, CalendarLookback or InstantsLookback"):
        DataRequirement.of("price_daily", "close", lookback=2)
