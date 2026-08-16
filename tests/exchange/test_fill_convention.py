from __future__ import annotations

from datetime import datetime, time
from pathlib import Path

import duckdb

from vqapr.data.sources import SourceSpec
from vqapr.domain.identifiers import execution_input_id
from vqapr.exchange.conventions import FillConvention
from vqapr.exchange.execution_table import ExecutionTableSpec, exact_execution_snapshot
from vqapr.exchange.target_selection import (
    ExactTargetConvention,
    TargetSelector,
    resolve_exact_target,
)


def _write(path: Path, rows: str) -> Path:
    con = duckdb.connect()
    try:
        con.execute(f"COPY ({rows}) TO '{path.as_posix()}' (FORMAT PARQUET)")
    finally:
        con.close()
    return path


def _spec(path: Path) -> ExecutionTableSpec:
    return ExecutionTableSpec(
        source=SourceSpec.of("execution", path),
        trade_at_field="trade_at",
        instrument_field="instrument",
        is_tradable_field="is_tradable",
        price_fields={"open": "open", "close": "close"},
    )


def _convention(selector: TargetSelector) -> ExactTargetConvention:
    return ExactTargetConvention(selector, time(15, 30), "Asia/Seoul", "close")


def test_active_fill_convention_remains_importable() -> None:
    assert FillConvention(0, time(15, 30), "Asia/Seoul", "close").offset_sessions == 0


def test_same_day_uses_venue_local_date_and_is_deterministic(tmp_path: Path) -> None:
    spec = _spec(
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

    first = resolve_exact_target(
        spec,
        execution_input_id=execution_input_id("input"),
        convention=_convention(TargetSelector.SAME_DAY),
        decision_time=decision,
        end_time=end,
    )
    second = resolve_exact_target(
        spec,
        execution_input_id=execution_input_id("input"),
        convention=_convention(TargetSelector.SAME_DAY),
        decision_time=decision,
        end_time=end,
    )

    assert first is not None
    assert first.target_at == datetime.fromisoformat("2024-03-05T06:30:00+00:00")
    assert first.identity == second.identity


def test_next_eligible_and_strict_bounds_have_no_fallback(tmp_path: Path) -> None:
    spec = _spec(
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
    equality = datetime.fromisoformat("2024-03-05T06:30:00+00:00")
    end = datetime.fromisoformat("2024-03-06T06:30:00+00:00")

    target = resolve_exact_target(
        spec,
        execution_input_id=execution_input_id("input"),
        convention=_convention(TargetSelector.NEXT_ELIGIBLE),
        decision_time=equality,
        end_time=end,
    )
    assert target is not None
    assert target.target_at == end
    assert (
        resolve_exact_target(
            spec,
            execution_input_id=execution_input_id("input"),
            convention=_convention(TargetSelector.SAME_DAY),
            decision_time=equality,
            end_time=end,
        )
        is None
    )
    assert (
        resolve_exact_target(
            spec,
            execution_input_id=execution_input_id("input"),
            convention=_convention(TargetSelector.NEXT_ELIGIBLE),
            decision_time=end,
            end_time=end,
        )
        is None
    )


def test_exact_snapshot_binds_selected_price_and_preserves_missing_and_duplicates(
    tmp_path: Path,
) -> None:
    path = _write(
        tmp_path / "snapshot.parquet",
        """
        SELECT * FROM (VALUES
          (TIMESTAMPTZ '2024-03-05 15:30:00+09', 'A', true, 11.0, 0.0),
          (TIMESTAMPTZ '2024-03-05 15:30:00+09', 'A', true, 12.0, 0.0),
          (TIMESTAMPTZ '2024-03-05 15:30:00+09', 'H', false, 20.0, 21.0)
        ) AS t(trade_at, instrument, is_tradable, open, close)
        """,
    )

    snapshot = exact_execution_snapshot(
        _spec(path),
        target_at=datetime.fromisoformat("2024-03-05T06:30:00+00:00"),
        target_instruments=("A", "MISSING"),
        held_instruments=("H", "HELD_MISSING"),
        trade_price="close",
    )

    assert [row.price for row in snapshot.rows if row.instrument == "A"] == [0.0, 0.0]
    assert snapshot.duplicate_instruments == ("A",)
    assert snapshot.missing_target_instruments == ("MISSING",)
    assert snapshot.missing_held_instruments == ("HELD_MISSING",)
