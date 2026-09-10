from __future__ import annotations

from datetime import datetime, time
from pathlib import Path

import duckdb

from vqapr.data.datasets import DatasetRegistration
from vqapr.data.sources import SourceSpec
from vqapr.data.validation import verify_source
from vqapr.exchange.conventions import FillRule
from vqapr.exchange.execution_table import ExecutionTable, ExecutionTableSpec


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


def _dataset(path: Path) -> tuple[DatasetRegistration, SourceSpec]:
    """The same venue table as a dataset with an execution role (record `185`): what
    registration measures through the one door (record `234`)."""
    return (
        DatasetRegistration.of(
            "krx-daily",
            "krx-execution",
            instrument_field="instrument",
            available_at="trade_at",
            key_fields=("trade_at", "instrument"),
            fields={"open": "open", "close": "close", "is_tradable": "is_tradable"},
            field_types={"open": "DOUBLE", "close": "DOUBLE", "is_tradable": "BOOLEAN"},
            grain="instrument_instant",
            execution={"is_tradable": "is_tradable"},
        ),
        SourceSpec.of("krx-execution", path),
    )


def test_valid_execution_input_accepts_a_halted_row_with_a_retained_price(tmp_path: Path) -> None:
    target = _write(
        tmp_path / "valid.parquet",
        """
        SELECT * FROM (VALUES
          (TIMESTAMPTZ '2024-03-05 15:30:00+09', 'A', true, 99.0::DOUBLE, 100.0::DOUBLE),
          (TIMESTAMPTZ '2024-03-05 15:30:00+09', 'B', false, 48.0::DOUBLE, 50.0::DOUBLE),
          (TIMESTAMPTZ '2024-03-06 15:30:00+09', 'A', true, 101.0::DOUBLE, 103.0::DOUBLE)
        ) AS t(trade_at, instrument, is_tradable, open, close)
        """,
    )

    diagnosis, _, measured = verify_source(*_dataset(target))

    assert diagnosis.ok
    assert diagnosis.mutation is False
    assert measured.execution_prices == ("close", "open"), "both prices positive when tradable"
    assert measured.verified


def test_a_non_positive_price_is_measured_not_refused_and_the_run_cannot_choose_it(
    tmp_path: Path,
) -> None:
    """Record `234`: registration measures which prices are positive on every tradable row;
    the refusal lands at preflight, where a run chooses one (`execution.price_not_positive`),
    instead of scanning the table again for the price it chose."""
    target = _write(
        tmp_path / "bad-price.parquet",
        """
        SELECT TIMESTAMPTZ '2024-03-05 15:30:00+09' AS trade_at,
               'A' AS instrument, true AS is_tradable, 99.0::DOUBLE AS open, 0.0::DOUBLE AS close
        """,
    )

    diagnosis, _, measured = verify_source(*_dataset(target))

    assert diagnosis.ok
    assert measured.execution_prices == ("open",), "close is 0 on a tradable row"


def test_duplicate_execution_identity_is_rejected(tmp_path: Path) -> None:
    target = _write(
        tmp_path / "duplicate.parquet",
        """
        SELECT * FROM (VALUES
          (TIMESTAMPTZ '2024-03-05 15:30:00+09', 'A', true, 99.0::DOUBLE, 100.0::DOUBLE),
          (TIMESTAMPTZ '2024-03-05 15:30:00+09', 'A', true, 99.0::DOUBLE, 100.0::DOUBLE)
        ) AS t(trade_at, instrument, is_tradable, open, close)
        """,
    )

    diagnosis, _, _ = verify_source(*_dataset(target))

    assert not diagnosis.ok
    assert [failure.code for failure in diagnosis.failures] == ["dataset.key_duplicate"]


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

