from __future__ import annotations

from datetime import datetime, time
from pathlib import Path

import duckdb
import pytest

from vqapr.data.sources import SourceSpec
from vqapr.domain.errors import VqaprError
from vqapr.exchange.conventions import FillConvention, FillSelector
from vqapr.exchange.execution_table import (
    ExecutionInputRegistration,
    ExecutionTableSpec,
    validate_execution_input,
)
from vqapr.workspace import Workspace


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
            selector=FillSelector.SAME_DAY,
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


def test_execution_rows_are_passive_to_fill_local_time_validation(tmp_path: Path) -> None:
    target = _write(
        tmp_path / "wrong-time.parquet",
        """
        SELECT TIMESTAMPTZ '2024-03-05 15:30:00+09' AS trade_at,
               'A' AS instrument, true AS is_tradable, 99.0 AS open, 100.0 AS close
        """,
    )

    diagnosis = validate_execution_input(_registration(target, local_time=time(9)))

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

    selected = registration.fill.select_target(
        registration, decision_time=decision_time, end_time=end_time
    )

    assert selected is not None
    assert selected.target_at == datetime.fromisoformat("2024-03-05T06:30:00+00:00")
    assert selected.selector is FillSelector.SAME_DAY
    assert selected.trade_price == "close"
    assert selected == registration.fill.select_target(
        registration, decision_time=decision_time, end_time=end_time
    )


def test_workspace_fill_round_trip_is_idempotent_and_rejects_offset_sessions(
    tmp_path: Path,
) -> None:
    registration = _registration(tmp_path / "execution.parquet")
    workspace = Workspace.create(tmp_path)

    assert workspace.register_execution_input(registration)
    assert not workspace.register_execution_input(registration)
    assert Workspace.open(tmp_path).execution_input("krx-daily") == registration

    document = workspace.path.read_text(encoding="utf-8")
    workspace.path.write_text(
        document.replace("selector: SAME_DAY", "offset_sessions: 0"),
        encoding="utf-8",
    )

    with pytest.raises(VqaprError, match="offset_sessions is no longer supported"):
        Workspace.open(tmp_path)
