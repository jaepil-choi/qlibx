from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from vqapr.data.datasets import DatasetRegistration
from vqapr.data.lookback import CalendarLookback, InstantsLookback, RowsLookback
from vqapr.data.requirements import DataRequirement
from vqapr.data.sources import SourceSpec
from vqapr.data.store import DuckDbObservationStore
from vqapr.data.windows import ModelWindow
from vqapr.domain.errors import Stage, VqaprError
from vqapr.public import register_dataset
from vqapr.workspace import Workspace

KST = ZoneInfo("Asia/Seoul")


def _workspace(
    tmp_path: Path, model_price_parquet: Path, grain: str = "instrument_instant"
) -> Workspace:
    source = SourceSpec.of("prices", model_price_parquet)
    registration = DatasetRegistration.of(
        "price_daily",
        "prices",
        instrument_field="instrument",
        available_at="available_at",
        grain=grain,
        key_fields=("available_at", "instrument"),
        fields={"close": "close", "volume": "volume"},
        field_types={"close": "DOUBLE", "volume": "DOUBLE"},
    )
    # Registered through the public entry point, which measures the span persistence requires.
    register_dataset(tmp_path, registration, source)
    return Workspace.open(tmp_path)


def test_rows_window_is_pit_bounded_and_counts_per_field(
    tmp_path: Path, model_price_parquet: Path
) -> None:
    """An InstantsLookback on a rows-grain table counts each field's OWN last N per name.

    `volume` is null on the 6th and `close` is present on it, so the two fields reach back
    different distances for the same instrument. That is the property this pins, and it is now
    read one requirement at a time rather than one batch carrying both.
    """
    workspace = _workspace(tmp_path, model_price_parquet, grain="rows")
    window_for = lambda requirement: ModelWindow(  # noqa: E731
        evaluation_time=datetime(2024, 3, 7, 16, tzinfo=KST),
        instruments=("A", "B"),
        store=DuckDbObservationStore(workspace),
        allowed_requirements=(requirement,),
        consumer_id="reversal",
    )

    close = DataRequirement.of("price_daily", "close", lookback=InstantsLookback(2))
    volume = DataRequirement.of("price_daily", "volume", lookback=InstantsLookback(2))
    closes = window_for(close).observations(close)
    volumes = window_for(volume).observations(volume)

    assert [
        (row["available_at"].day, row["close"]) for row in closes.rows if row["instrument"] == "A"
    ] == [(6, 103.0), (7, 105.0)]
    assert [
        (row["available_at"].day, row["volume"]) for row in volumes.rows if row["instrument"] == "A"
    ] == [(5, 10.0), (7, 12.0)]
    # The 8th is past the evaluation time for both.
    assert all(row["available_at"].day != 8 for row in (*closes.rows, *volumes.rows))
    assert closes.access.actual_rows == {"A": {"close": 2}, "B": {"close": 2}}
    assert volumes.access.actual_rows == {"A": {"volume": 2}, "B": {"volume": 2}}
    assert closes.access.max_available_at == datetime(2024, 3, 7, 15, 30, tzinfo=KST)
    # Stamped by the framework from the component that read, and the dataset resolved from the
    # field id rather than named by the requirement.
    assert closes.access.consumer_id == "reversal"
    assert str(closes.access.dataset_id) == "price_daily"


def test_calendar_window_uses_local_midnight_not_session_count(
    tmp_path: Path, model_price_parquet: Path
) -> None:
    workspace = _workspace(tmp_path, model_price_parquet)
    requirement = DataRequirement.of(
        "price_daily", "close", lookback=CalendarLookback(days=1, timezone="Asia/Seoul")
    )
    window = ModelWindow(
        evaluation_time=datetime(2024, 3, 7, 16, tzinfo=KST),
        instruments=("A",),
        store=DuckDbObservationStore(workspace),
        allowed_requirements=(requirement,),
        consumer_id="test-consumer",
    )

    batch = window.observations(requirement)

    assert [row["available_at"].day for row in batch.rows] == [6, 7]
    assert batch.access.lower_bound == datetime(2024, 3, 6, 0, tzinfo=KST)


def test_window_rejects_an_undeclared_requirement(
    tmp_path: Path, model_price_parquet: Path
) -> None:
    workspace = _workspace(tmp_path, model_price_parquet)
    declared = DataRequirement.of("price_daily", "close", lookback=RowsLookback(2))
    undeclared = DataRequirement.of("price_daily", "volume", lookback=RowsLookback(2))
    window = ModelWindow(
        evaluation_time=datetime(2024, 3, 7, 16, tzinfo=KST),
        instruments=("A",),
        store=DuckDbObservationStore(workspace),
        allowed_requirements=(declared,),
        consumer_id="test-consumer",
    )

    with pytest.raises(VqaprError) as caught:
        window.observations(undeclared)

    assert caught.value.stage is Stage.RUN
    assert caught.value.mutation is False
