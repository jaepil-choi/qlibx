from __future__ import annotations

from datetime import datetime, time
from pathlib import Path

import duckdb

from vqapr.data.sources import SourceSpec
from vqapr.exchange.conventions import FillRule
from vqapr.exchange.execution_table import (
    ExecutionTable,
    ExecutionTableSpec,
    validate_execution_table,
)


def _write(path: Path, rows: str) -> Path:
    con = duckdb.connect()
    try:
        con.execute(f"COPY ({rows}) TO '{path.as_posix()}' (FORMAT PARQUET)")
    finally:
        con.close()
    return path


def _registration(path: Path, *, local_time: time = time(15, 30)) -> ExecutionTable:
    return ExecutionTable.of(
        "krx-daily",
        ExecutionTableSpec(
            source=SourceSpec.of("krx-execution", path),
            trade_at_field="trade_at",
            instrument_field="instrument",
            is_tradable_field="is_tradable",
            price_fields={"open": "open", "close": "close"},
        ),
        FillRule("close", "Asia/Seoul", at=local_time),
    )


def test_valid_execution_input_accepts_a_halted_row_with_a_retained_price(tmp_path: Path) -> None:
    target = _write(
        tmp_path / "valid.parquet",
        """
        SELECT * FROM (VALUES
          (TIMESTAMPTZ '2024-03-05 15:30:00+09', 'A', true, 99.0, 100.0),
          (TIMESTAMPTZ '2024-03-05 15:30:00+09', 'B', false, 48.0, 50.0),
          (TIMESTAMPTZ '2024-03-06 15:30:00+09', 'A', true, 101.0, 103.0)
        ) AS t(trade_at, instrument, is_tradable, open, close)
        """,
    )

    diagnosis = validate_execution_table(_registration(target))

    assert diagnosis.ok
    assert diagnosis.mutation is False


def test_selected_price_does_not_fall_back_to_another_valid_price(tmp_path: Path) -> None:
    target = _write(
        tmp_path / "bad-price.parquet",
        """
        SELECT TIMESTAMPTZ '2024-03-05 15:30:00+09' AS trade_at,
               'A' AS instrument, true AS is_tradable, 99.0 AS open, 0.0 AS close
        """,
    )

    diagnosis = validate_execution_table(_registration(target))

    assert not diagnosis.ok
    assert [failure.code for failure in diagnosis.failures] == [
        "execution_table.price_invalid"
    ]
    assert diagnosis.failures[0].example_total == 1
    assert "close" in diagnosis.failures[0].requirement


def test_duplicate_execution_identity_is_rejected(tmp_path: Path) -> None:
    target = _write(
        tmp_path / "duplicate.parquet",
        """
        SELECT * FROM (VALUES
          (TIMESTAMPTZ '2024-03-05 15:30:00+09', 'A', true, 99.0, 100.0),
          (TIMESTAMPTZ '2024-03-05 15:30:00+09', 'A', true, 99.0, 100.0)
        ) AS t(trade_at, instrument, is_tradable, open, close)
        """,
    )

    diagnosis = validate_execution_table(_registration(target))

    assert not diagnosis.ok
    assert [failure.code for failure in diagnosis.failures] == [
        "execution_table.key_duplicate"
    ]


def test_execution_rows_are_passive_to_fill_local_time_validation(tmp_path: Path) -> None:
    target = _write(
        tmp_path / "wrong-time.parquet",
        """
        SELECT TIMESTAMPTZ '2024-03-05 15:30:00+09' AS trade_at,
               'A' AS instrument, true AS is_tradable, 99.0 AS open, 100.0 AS close
        """,
    )

    diagnosis = validate_execution_table(_registration(target, local_time=time(9)))

    assert diagnosis.ok


def test_fill_selects_one_exact_same_day_target_with_stable_identity(tmp_path: Path) -> None:
    target = _write(
        tmp_path / "targets.parquet",
        """
        SELECT * FROM (VALUES
          (TIMESTAMPTZ '2024-03-05 09:00:00+09', 'A', true, 99.0, 100.0),
          (TIMESTAMPTZ '2024-03-05 15:30:00+09', 'A', true, 101.0, 102.0),
          (TIMESTAMPTZ '2024-03-06 15:30:00+09', 'A', true, 103.0, 104.0)
        ) AS t(trade_at, instrument, is_tradable, open, close)
        """,
    )
    registration = _registration(target)
    decision_time = datetime.fromisoformat("2024-03-05T04:00:00+09:00")
    end_time = datetime.fromisoformat("2024-03-06T16:00:00+09:00")

    selected = registration.select_target(
        decision_time=decision_time, end_time=end_time
    )

    assert selected is not None
    assert selected.target_at == datetime.fromisoformat("2024-03-05T06:30:00+00:00")
    assert selected.trade_price == "close"
    assert selected == registration.select_target(
        decision_time=decision_time, end_time=end_time
    )

