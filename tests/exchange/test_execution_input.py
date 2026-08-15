from __future__ import annotations

from datetime import time
from pathlib import Path

import duckdb

from vqapr.data.sources import SourceSpec
from vqapr.exchange.conventions import FillConvention
from vqapr.exchange.execution_table import (
    ExecutionInputRegistration,
    ExecutionTableSpec,
    validate_execution_input,
)


def _write(path: Path, rows: str) -> Path:
    con = duckdb.connect()
    try:
        con.execute(f"COPY ({rows}) TO '{path.as_posix()}' (FORMAT PARQUET)")
    finally:
        con.close()
    return path


def _registration(path: Path, *, local_time: time = time(15, 30)) -> ExecutionInputRegistration:
    return ExecutionInputRegistration.of(
        "krx-daily",
        ExecutionTableSpec(
            source=SourceSpec.of("krx-execution", path),
            trade_at_field="trade_at",
            instrument_field="instrument",
            is_tradable_field="is_tradable",
            price_fields={"open": "open", "close": "close"},
        ),
        FillConvention(
            offset_sessions=0,
            local_time=local_time,
            timezone="Asia/Seoul",
            trade_price="close",
        ),
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

    diagnosis = validate_execution_input(_registration(target))

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

    diagnosis = validate_execution_input(_registration(target))

    assert not diagnosis.ok
    assert [failure.code for failure in diagnosis.failures] == [
        "execution_input.register.price.invalid"
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

    diagnosis = validate_execution_input(_registration(target))

    assert not diagnosis.ok
    assert [failure.code for failure in diagnosis.failures] == [
        "execution_input.register.key.duplicate"
    ]


def test_fill_local_time_must_match_every_execution_instant(tmp_path: Path) -> None:
    target = _write(
        tmp_path / "wrong-time.parquet",
        """
        SELECT TIMESTAMPTZ '2024-03-05 15:30:00+09' AS trade_at,
               'A' AS instrument, true AS is_tradable, 99.0 AS open, 100.0 AS close
        """,
    )

    diagnosis = validate_execution_input(_registration(target, local_time=time(9)))

    assert not diagnosis.ok
    assert [failure.code for failure in diagnosis.failures] == [
        "execution_input.register.time.local_time_mismatch"
    ]
