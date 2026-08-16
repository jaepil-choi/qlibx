from __future__ import annotations

from datetime import datetime, time
from decimal import Decimal
from pathlib import Path

import duckdb

from vqapr.data.sources import SourceSpec
from vqapr.exchange.conventions import FillConvention, FillSelector
from vqapr.exchange.execution_table import (
    ExecutionInputRegistration,
    ExecutionTableSpec,
    exact_execution_snapshot,
)


def _write(path: Path, rows: str) -> Path:
    con = duckdb.connect()
    try:
        con.execute(f"COPY ({rows}) TO '{path.as_posix()}' (FORMAT PARQUET)")
    finally:
        con.close()
    return path


def _registration(path: Path) -> ExecutionInputRegistration:
    table = ExecutionTableSpec(
        source=SourceSpec.of("execution", path),
        trade_at_field="trade_at",
        instrument_field="instrument",
        is_tradable_field="is_tradable",
        price_fields={"open": "open", "close": "close"},
    )
    return ExecutionInputRegistration.of(
        "input",
        table,
        FillConvention(FillSelector.SAME_DAY, time(15, 30), "Asia/Seoul", "close"),
    )


def test_same_day_uses_venue_local_date_and_is_deterministic(tmp_path: Path) -> None:
    registration = _registration(
        _write(
            tmp_path / "sessions.parquet",
            """
            SELECT * FROM (VALUES
              (TIMESTAMPTZ '2024-03-05 09:00:00+09', 'DENSE', true, 90.0, 91.0),
              (TIMESTAMPTZ '2024-03-05 15:30:00+09', 'A', true, 99.0, 100.0),
              (TIMESTAMPTZ '2024-03-06 15:30:00+09', 'A', true, 101.0, 102.0)
            ) AS t(trade_at, instrument, is_tradable, open, close)
            """,
        )
    )
    decision = datetime.fromisoformat("2024-03-04T16:00:00+00:00")
    end = datetime.fromisoformat("2024-03-06T12:00:00+00:00")

    first = registration.fill.select_target(
        registration,
        decision_time=decision,
        end_time=end,
    )
    second = registration.fill.select_target(
        registration,
        decision_time=decision,
        end_time=end,
    )

    assert first is not None
    assert first.target_at == datetime.fromisoformat("2024-03-05T06:30:00+00:00")
    assert first.identity == second.identity


def test_next_eligible_and_strict_bounds_have_no_fallback(tmp_path: Path) -> None:
    registration = _registration(
        _write(
            tmp_path / "bounds.parquet",
            """
            SELECT * FROM (VALUES
              (TIMESTAMPTZ '2024-03-05 15:30:00+09', 'A', true, 99.0, 100.0),
              (TIMESTAMPTZ '2024-03-06 15:30:00+09', 'A', true, 101.0, 102.0)
            ) AS t(trade_at, instrument, is_tradable, open, close)
            """,
        )
    )
    registration = ExecutionInputRegistration(
        registration.execution_input_id,
        registration.table,
        FillConvention(
            FillSelector.NEXT_ELIGIBLE,
            time(15, 30),
            "Asia/Seoul",
            "close",
        ),
    )
    equality = datetime.fromisoformat("2024-03-05T06:30:00+00:00")
    end = datetime.fromisoformat("2024-03-06T06:30:00+00:00")

    target = registration.fill.select_target(
        registration,
        decision_time=equality,
        end_time=end,
    )
    assert target is not None
    assert target.target_at == end
    assert (
        registration.fill.select_target(
            registration,
            decision_time=end,
            end_time=end,
        )
        is None
    )


def test_exact_snapshot_preserves_missing_and_duplicate_partitions(tmp_path: Path) -> None:
    registration = _registration(
        _write(
            tmp_path / "snapshot.parquet",
            """
            SELECT * FROM (VALUES
              (TIMESTAMPTZ '2024-03-05 15:30:00+09', 'A', true, 11.0, 12.0),
              (TIMESTAMPTZ '2024-03-05 15:30:00+09', 'A', true, 13.0, 14.0),
              (TIMESTAMPTZ '2024-03-05 15:30:00+09', 'H', false, 20.0, 21.0)
            ) AS t(trade_at, instrument, is_tradable, open, close)
            """,
        )
    )

    snapshot = exact_execution_snapshot(
        registration.table,
        target_at=datetime.fromisoformat("2024-03-05T06:30:00+00:00"),
        target_instruments=("A", "MISSING"),
        held_instruments=("H", "HELD_MISSING"),
        trade_price="close",
    )

    assert [row.price for row in snapshot.rows if row.instrument == "A"] == [
        Decimal("12.0"),
        Decimal("14.0"),
    ]
    assert snapshot.duplicate_instruments == ("A",)
    assert snapshot.missing_target_instruments == ("MISSING",)
    assert snapshot.missing_held_instruments == ("HELD_MISSING",)
