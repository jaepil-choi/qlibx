from __future__ import annotations

from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
import pytest

from vqapr.data.sources import SourceSpec
from vqapr.domain.errors import FailureFamily, VqaprError
from vqapr.exchange.execution_table import ExecutionTableSpec, execution_session_times
from vqapr.runtime.events import EventKind, LocalEvaluationTime
from vqapr.runtime.session_stream import SessionStream

KST = ZoneInfo("Asia/Seoul")


@pytest.fixture
def execution_parquet(tmp_path: Path) -> Path:
    target = tmp_path / "execution.parquet"
    con = duckdb.connect()
    try:
        con.execute(
            f"""COPY (
                SELECT * FROM (VALUES
                  (TIMESTAMPTZ '2024-03-06 15:30:00+09', 'A', true, 101.0),
                  (TIMESTAMPTZ '2024-03-05 15:30:00+09', 'B', true, 200.0),
                  (TIMESTAMPTZ '2024-03-05 15:30:00+09', 'A', false, 100.0)
                ) AS t(trade_at, instrument, is_tradable, close)
            ) TO '{target.as_posix()}' (FORMAT PARQUET)"""
        )
    finally:
        con.close()
    return target


def _spec(path: Path) -> ExecutionTableSpec:
    return ExecutionTableSpec(
        source=SourceSpec.of("execution", path),
        trade_at_field="trade_at",
        instrument_field="instrument",
        is_tradable_field="is_tradable",
        price_fields={"close": "close"},
    )


def test_execution_table_binding_detaches_its_price_mapping(execution_parquet: Path) -> None:
    prices = {"close": "close"}
    spec = ExecutionTableSpec(
        source=SourceSpec.of("execution", execution_parquet),
        trade_at_field="trade_at",
        instrument_field="instrument",
        is_tradable_field="is_tradable",
        price_fields=prices,
    )

    prices["open"] = "open"

    assert dict(spec.price_fields) == {"close": "close"}
    with pytest.raises(TypeError):
        spec.price_fields["open"] = "open"  # type: ignore[index]


def test_execution_table_is_the_authoritative_session_source(
    execution_parquet: Path,
) -> None:
    times = execution_session_times(_spec(execution_parquet))

    assert times == (
        datetime(2024, 3, 5, 6, 30, tzinfo=ZoneInfo("UTC")),
        datetime(2024, 3, 6, 6, 30, tzinfo=ZoneInfo("UTC")),
    )


def test_session_stream_delivers_each_current_execution_session_once(
    execution_parquet: Path,
) -> None:
    stream = SessionStream.from_execution_times(
        execution_session_times(_spec(execution_parquet)),
        callback_time=LocalEvaluationTime(time(4, 0), "Asia/Seoul"),
    )

    assert [event.kind for event in stream] == [EventKind.SESSION, EventKind.SESSION]
    assert [event.session.isoformat() for event in stream] == ["2024-03-05", "2024-03-06"]
    assert [event.evaluation_time for event in stream] == [
        datetime(2024, 3, 5, 4, 0, tzinfo=KST),
        datetime(2024, 3, 6, 4, 0, tzinfo=KST),
    ]
    assert [event.execution_time for event in stream] == list(
        execution_session_times(_spec(execution_parquet))
    )


def test_session_stream_rejects_two_execution_instants_for_one_daily_session() -> None:
    with pytest.raises(ValueError, match="more than one execution time"):
        SessionStream.from_execution_times(
            [
                datetime(2024, 3, 5, 9, 0, tzinfo=KST),
                datetime(2024, 3, 5, 15, 30, tzinfo=KST),
            ],
            callback_time=LocalEvaluationTime(time(4, 0), "Asia/Seoul"),
        )


def test_execution_session_source_rejects_a_naive_trade_time(tmp_path: Path) -> None:
    target = tmp_path / "naive-execution.parquet"
    con = duckdb.connect()
    try:
        con.execute(
            f"""COPY (
                SELECT TIMESTAMP '2024-03-05 15:30:00' AS trade_at,
                       'A' AS instrument, true AS is_tradable, 100.0 AS close
            ) TO '{target.as_posix()}' (FORMAT PARQUET)"""
        )
    finally:
        con.close()

    with pytest.raises(VqaprError) as caught:
        execution_session_times(_spec(target))

    assert caught.value.family is FailureFamily.EXCHANGE
    assert caught.value.mutation is False
    assert caught.value.failures[0].code == "execution_table.sessions.field_type"
