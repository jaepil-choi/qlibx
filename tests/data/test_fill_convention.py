"""When a decision fills: the first market-clock instant after it, narrowed by at/after/within.

Design §3.5 (record `205`). The rule filters REAL instants -- the execution table's -- rather than
constructing a wall time, so the fold/offset proof the old convention carried has nothing to
prove: an instant that happens twice on a fall-back day is two candidates and the first later one
wins; a wall time that never happens on a spring-forward day matches nothing and the next day's
does. `within` is what used to be the difference between `SAME_DAY` and `NEXT_ELIGIBLE`.
"""

from __future__ import annotations

from datetime import datetime, time
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest

from vqapr.data.execution_table import ExecutionTable, ExecutionTableSpec, exact_execution_snapshot
from vqapr.data.source import SourceSpec
from vqapr.domain.fill import FillRule, parse_duration


def _write(path: Path, rows: str) -> Path:
    con = duckdb.connect()
    try:
        con.execute(f"COPY ({rows}) TO '{path.as_posix()}' (FORMAT PARQUET)")
    finally:
        con.close()
    return path


def _registration(path: Path, fill: FillRule | None = None) -> ExecutionTable:
    table = ExecutionTableSpec(
        source=SourceSpec.of("execution", path),
        trade_at_field="trade_at",
        instrument_field="instrument",
        is_tradable_field="is_tradable",
        price_fields={"open": "open", "close": "close"},
    )
    return ExecutionTable.of(
        "input", table, fill or FillRule("close", "Asia/Seoul", at=time(15, 30))
    )


_TWO_DAYS = """
SELECT * FROM (VALUES
  (TIMESTAMPTZ '2024-03-05 09:00:00+09', 'DENSE', true, 90.0, 91.0),
  (TIMESTAMPTZ '2024-03-05 15:30:00+09', 'A', true, 99.0, 100.0),
  (TIMESTAMPTZ '2024-03-06 09:00:00+09', 'DENSE', true, 100.0, 101.0),
  (TIMESTAMPTZ '2024-03-06 15:30:00+09', 'A', true, 101.0, 102.0)
) AS t(trade_at, instrument, is_tradable, open, close)
"""


def test_the_default_is_the_first_instant_after_the_decision(tmp_path: Path) -> None:
    """No handles: a 04:00 KST decision fills at that day's 09:00 print, not its close."""
    registration = _registration(
        _write(tmp_path / "t.parquet", _TWO_DAYS), FillRule("close", "Asia/Seoul")
    )
    decision = datetime.fromisoformat("2024-03-05T04:00:00+09:00")
    end = datetime.fromisoformat("2024-03-06T23:00:00+09:00")

    first = registration.select_target(decision_time=decision, end_time=end)
    again = registration.select_target(decision_time=decision, end_time=end)

    assert first is not None
    assert first.target_at == datetime.fromisoformat("2024-03-05T00:00:00+00:00")
    assert first.trade_price == "close"
    assert first.identity == again.identity, "the same decision selects the same target"
    # Strictly later: a decision AT the 09:00 print fills at the 15:30 one.
    at_the_print = registration.select_target(
        decision_time=datetime.fromisoformat("2024-03-05T09:00:00+09:00"), end_time=end
    )
    assert at_the_print is not None
    assert at_the_print.target_at == datetime.fromisoformat("2024-03-05T06:30:00+00:00")


def test_at_keeps_the_instants_at_that_wall_time_in_the_runs_zone(tmp_path: Path) -> None:
    """`at: 15:30` skips the 09:00 print; the zone is the run's, so the same table read from
    Honolulu names a different wall time for the same instant."""
    registration = _registration(_write(tmp_path / "t.parquet", _TWO_DAYS))
    decision = datetime.fromisoformat("2024-03-05T04:00:00+09:00")
    end = datetime.fromisoformat("2024-03-06T23:00:00+09:00")

    target = registration.select_target(decision_time=decision, end_time=end)
    assert target is not None
    assert target.target_at == datetime.fromisoformat("2024-03-05T06:30:00+00:00")

    # 15:30 KST is 20:30 the previous day in Honolulu: `at: 20:30` there is the same instant.
    honolulu = _registration(
        _write(tmp_path / "h.parquet", _TWO_DAYS),
        FillRule("close", "Pacific/Honolulu", at=time(20, 30)),
    )
    there = honolulu.select_target(decision_time=decision, end_time=end)
    assert there is not None and there.target_at == target.target_at


def test_the_run_end_is_a_hard_bound_and_the_decision_is_strictly_before(tmp_path: Path) -> None:
    registration = _registration(_write(tmp_path / "bounds.parquet", _TWO_DAYS))
    equality = datetime.fromisoformat("2024-03-05T06:30:00+00:00")
    end = datetime.fromisoformat("2024-03-06T06:30:00+00:00")

    target = registration.select_target(decision_time=equality, end_time=end)
    assert target is not None
    assert target.target_at == end, "an instant equal to the end is inside the horizon"
    assert registration.select_target(decision_time=end, end_time=end) is None


def test_after_is_a_minimum_gap_and_within_a_maximum(tmp_path: Path) -> None:
    """`after: 1h` from 08:30 skips the 09:00 print; `within: 1h` from 04:00 finds nothing --
    which is a fact, not a guess, and what preflight refuses."""
    path = _write(tmp_path / "gaps.parquet", _TWO_DAYS)
    end = datetime.fromisoformat("2024-03-06T23:00:00+09:00")

    delayed = _registration(path, FillRule("close", "Asia/Seoul", after="1h"))
    target = delayed.select_target(
        decision_time=datetime.fromisoformat("2024-03-05T08:30:00+09:00"), end_time=end
    )
    assert target is not None
    assert target.target_at == datetime.fromisoformat("2024-03-05T06:30:00+00:00")

    bounded = _registration(path, FillRule("close", "Asia/Seoul", within="1h"))
    assert (
        bounded.select_target(
            decision_time=datetime.fromisoformat("2024-03-05T04:00:00+09:00"), end_time=end
        )
        is None
    )
    same_day = _registration(path, FillRule("close", "Asia/Seoul", at=time(15, 30), within="12h"))
    # The old SAME_DAY: a decision after the close has no same-day close, and a `within` shorter
    # than a day forbids the next day's.
    assert (
        same_day.select_target(
            decision_time=datetime.fromisoformat("2024-03-05T16:00:00+09:00"),
            end_time=end,
        )
        is None
    )


def test_a_repeated_wall_time_is_two_candidates_and_the_first_later_wins(tmp_path: Path) -> None:
    """Fall back in New York: 01:30 happens twice. No fold to declare -- the earlier instant that
    is still after the decision is the fill, deterministically."""
    registration = _registration(
        _write(
            tmp_path / "dst.parquet",
            """
            SELECT * FROM (VALUES
              (TIMESTAMPTZ '2024-11-03 01:30:00-04', 'A', true, 99.0, 100.0, 1.0),
              (TIMESTAMPTZ '2024-11-03 01:30:00-05', 'A', true, 101.0, 102.0, 1.0)
            ) AS t(trade_at, instrument, is_tradable, open, close, pad)
            """,
        ),
        FillRule("close", "America/New_York", at=time(1, 30)),
    )
    end = datetime.fromisoformat("2024-11-03T07:00:00+00:00")

    first = registration.select_target(
        decision_time=datetime.fromisoformat("2024-11-03T04:00:00+00:00"), end_time=end
    )
    assert first is not None and first.target_at == datetime.fromisoformat("2024-11-03T05:30:00+00:00")
    second = registration.select_target(
        decision_time=datetime.fromisoformat("2024-11-03T05:30:00+00:00"), end_time=end
    )
    assert second is not None and second.target_at == datetime.fromisoformat("2024-11-03T06:30:00+00:00")


def test_a_wall_time_the_clock_skips_matches_nothing_that_day(tmp_path: Path) -> None:
    """Spring forward: 02:30 never happens on 2024-03-10, so `at: 02:30` finds the next day's."""
    registration = _registration(
        _write(
            tmp_path / "gap.parquet",
            """
            SELECT * FROM (VALUES
              (TIMESTAMPTZ '2024-03-10 03:30:00-04', 'A', true, 99.0, 100.0),
              (TIMESTAMPTZ '2024-03-11 02:30:00-04', 'A', true, 101.0, 102.0)
            ) AS t(trade_at, instrument, is_tradable, open, close)
            """,
        ),
        FillRule("close", "America/New_York", at=time(2, 30)),
    )
    target = registration.select_target(
        decision_time=datetime.fromisoformat("2024-03-10T05:00:00+00:00"),
        end_time=datetime.fromisoformat("2024-03-12T00:00:00+00:00"),
    )
    assert target is not None
    assert target.target_at == datetime.fromisoformat("2024-03-11T06:30:00+00:00")


@pytest.mark.parametrize(
    ("kwargs", "said"),
    [
        ({"after": "soon"}, "count and a unit"),
        ({"within": "0d"}, "count and a unit"),
        ({"after": "2d", "within": "1d"}, "after must not exceed within"),
        ({"at": time(15, 30, tzinfo=datetime.now().astimezone().tzinfo)}, "timezone-naive"),
    ],
)
def test_a_rule_that_cannot_be_satisfied_is_refused_by_name(kwargs: dict, said: str) -> None:
    with pytest.raises(ValueError, match=said):
        FillRule("close", "Asia/Seoul", **kwargs)
    assert parse_duration("90m", name="x").total_seconds() == 5400


def test_the_rule_describes_itself_the_way_the_declaration_reads() -> None:
    assert FillRule("close", "Asia/Seoul").describe() == (
        "the first execution instant after the decision"
    )
    assert FillRule("close", "Asia/Seoul", at=time(15, 30), within="1d").describe() == (
        "the first execution instant after the decision, at 15:30:00 Asia/Seoul, within 1d"
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
