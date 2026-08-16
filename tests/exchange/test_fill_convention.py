from __future__ import annotations

from datetime import datetime, time
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest

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


def test_dst_target_requires_matching_fold_and_offset_proof(tmp_path: Path) -> None:
    registration = ExecutionInputRegistration.of(
        "input",
        ExecutionTableSpec(
            source=SourceSpec.of(
                "execution",
                _write(
                    tmp_path / "dst.parquet",
                    """
                    SELECT * FROM (VALUES
                      (TIMESTAMPTZ '2024-11-03 01:30:00-04', 'A', true, 99.0, 100.0),
                      (TIMESTAMPTZ '2024-11-03 01:30:00-05', 'A', true, 101.0, 102.0)
                    ) AS t(trade_at, instrument, is_tradable, open, close)
                    """,
                ),
            ),
            trade_at_field="trade_at",
            instrument_field="instrument",
            is_tradable_field="is_tradable",
            price_fields={"close": "close"},
        ),
        FillConvention(FillSelector.NEXT_ELIGIBLE, time(1, 30), "America/New_York", "close"),
    )
    decision = datetime.fromisoformat("2024-11-03T04:00:00+00:00")
    end = datetime.fromisoformat("2024-11-03T07:00:00+00:00")

    with pytest.raises(ValueError, match="ambiguous"):
        registration.fill.select_target(registration, decision_time=decision, end_time=end)
    wrong = FillConvention(
        FillSelector.NEXT_ELIGIBLE, time(1, 30), "America/New_York", "close", 0, "-05:00"
    )
    with pytest.raises(ValueError, match="does not resolve"):
        wrong.select_target(registration, decision_time=decision, end_time=end)

    proven = FillConvention(
        FillSelector.NEXT_ELIGIBLE, time(1, 30), "America/New_York", "close", 1, "-05:00"
    )
    target = proven.select_target(
        ExecutionInputRegistration(registration.execution_input_id, registration.table, proven),
        decision_time=decision,
        end_time=end,
    )
    assert target is not None
    assert target.target_at == datetime.fromisoformat("2024-11-03T06:30:00+00:00")
    assert proven.declaration_identity != registration.fill.declaration_identity


def test_nonexistent_dst_target_is_rejected_instead_of_skipped(tmp_path: Path) -> None:
    registration = ExecutionInputRegistration.of(
        "input",
        ExecutionTableSpec(
            source=SourceSpec.of(
                "execution",
                _write(
                    tmp_path / "gap.parquet",
                    """
                    SELECT * FROM (VALUES
                      (TIMESTAMPTZ '2024-03-10 03:30:00-04', 'A', true, 99.0, 100.0)
                    ) AS t(trade_at, instrument, is_tradable, open, close)
                    """,
                ),
            ),
            trade_at_field="trade_at",
            instrument_field="instrument",
            is_tradable_field="is_tradable",
            price_fields={"close": "close"},
        ),
        FillConvention(FillSelector.NEXT_ELIGIBLE, time(2, 30), "America/New_York", "close"),
    )

    with pytest.raises(ValueError, match="does not exist"):
        registration.fill.select_target(
            registration,
            decision_time=datetime.fromisoformat("2024-03-10T05:00:00+00:00"),
            end_time=datetime.fromisoformat("2024-03-10T08:00:00+00:00"),
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
