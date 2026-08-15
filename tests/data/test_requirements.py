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


def test_requirement_rejects_empty_or_duplicate_framework_fields() -> None:
    with pytest.raises(ValueError, match="at least one"):
        DataRequirement.of("reversal", "price_daily", fields=(), lookback=RowsLookback(2))
    with pytest.raises(ValueError, match="unique"):
        DataRequirement.of(
            "reversal",
            "price_daily",
            fields=("close", "close"),
            lookback=RowsLookback(2),
        )
