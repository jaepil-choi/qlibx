from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from vqapr.data.datasets import DatasetRegistration
from vqapr.data.lookback import CalendarLookback, RowsLookback
from vqapr.data.requirements import DataRequirement
from vqapr.data.sources import SourceSpec
from vqapr.data.store import DuckDbObservationStore
from vqapr.data.windows import ModelWindow
from vqapr.domain.errors import VqaprError
from vqapr.public import register_dataset
from vqapr.workspace import Workspace

KST = ZoneInfo("Asia/Seoul")


def _workspace(tmp_path: Path, model_price_parquet: Path) -> Workspace:
    source = SourceSpec.of("prices", model_price_parquet)
    registration = DatasetRegistration.of(
        "price_daily",
        "prices",
        instrument_field="instrument",
        available_at="available_at",
        key_fields=("available_at", "instrument"),
        fields={"close": "close", "volume": "volume"},
    )
    # Registered through the public entry point, which measures the span persistence requires.
    register_dataset(tmp_path, registration, source)
    return Workspace.open(tmp_path)


def test_rows_window_is_pit_bounded_and_counts_per_instrument_and_field(
    tmp_path: Path, model_price_parquet: Path
) -> None:
    workspace = _workspace(tmp_path, model_price_parquet)
    requirement = DataRequirement.of(
        "reversal",
        "price_daily",
        fields=("close", "volume"),
        lookback=RowsLookback(2),
    )
    window = ModelWindow(
        evaluation_time=datetime(2024, 3, 7, 16, tzinfo=KST),
        instruments=("A", "B"),
        store=DuckDbObservationStore(workspace),
        allowed_requirements=(requirement,),
    )

    batch = window.observations(requirement)

    a_rows = [row for row in batch.rows if row["instrument"] == "A"]
    assert [(row["available_at"].day, row["close"], row["volume"]) for row in a_rows] == [
        (5, None, 10.0),
        (6, 103.0, None),
        (7, 105.0, 12.0),
    ]
    assert all(row["available_at"].day != 8 for row in batch.rows)
    assert batch.access.actual_rows == {
        "A": {"close": 2, "volume": 2},
        "B": {"close": 2, "volume": 2},
    }
    assert batch.access.max_available_at == datetime(2024, 3, 7, 15, 30, tzinfo=KST)


def test_calendar_window_uses_local_midnight_not_session_count(
    tmp_path: Path, model_price_parquet: Path
) -> None:
    workspace = _workspace(tmp_path, model_price_parquet)
    requirement = DataRequirement.of(
        "calendar-model",
        "price_daily",
        fields=("close",),
        lookback=CalendarLookback(days=1, timezone="Asia/Seoul"),
    )
    window = ModelWindow(
        evaluation_time=datetime(2024, 3, 7, 16, tzinfo=KST),
        instruments=("A",),
        store=DuckDbObservationStore(workspace),
        allowed_requirements=(requirement,),
    )

    batch = window.observations(requirement)

    assert [row["available_at"].day for row in batch.rows] == [6, 7]
    assert batch.access.lower_bound == datetime(2024, 3, 6, 0, tzinfo=KST)


def test_window_rejects_an_undeclared_requirement(
    tmp_path: Path, model_price_parquet: Path
) -> None:
    workspace = _workspace(tmp_path, model_price_parquet)
    declared = DataRequirement.of(
        "reversal", "price_daily", fields=("close",), lookback=RowsLookback(2)
    )
    undeclared = DataRequirement.of(
        "reversal", "price_daily", fields=("volume",), lookback=RowsLookback(2)
    )
    window = ModelWindow(
        evaluation_time=datetime(2024, 3, 7, 16, tzinfo=KST),
        instruments=("A",),
        store=DuckDbObservationStore(workspace),
        allowed_requirements=(declared,),
    )

    with pytest.raises(VqaprError) as caught:
        window.observations(undeclared)

    assert caught.value.stage == "model_window.requirement"
    assert caught.value.mutation is False
