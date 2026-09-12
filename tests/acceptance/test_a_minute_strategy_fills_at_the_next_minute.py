"""AC-1 of the two-clocks campaign: a strategy that decides every minute fills every minute --
and the book is valued at every minute the market clock has (design §3, §3.1).

§3.4 gives the schedule `every: 1m` with `from`/`to`; §3.5 gives the fill its default, "the first
market-clock instant after the decision" -- on a minute table, the next minute; §3.1 makes
VALUATION and COMPLIANCE stages of the market clock, so the NAV series has the table's
resolution whether or not a decision was made at an instant. Through the CLI, the way a user
would declare it (records `205`, `206`).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
import pytest

from tests.cli.test_commands import _cli, _register_roster

_ZONE = ZoneInfo("Asia/Seoul")
DAY = "2024-03-05"

_ALWAYS_LONG = '''"""Wants to be fully invested in A at every decision; only the first fill trades."""

from decimal import Decimal

from vqapr import public as vq


class AlwaysLong(vq.StrategyModel):
    def inputs(self):
        return {
            "prices": vq.DatasetInput(
                dataset_id="prices", fields=("close",), lookback=vq.RowsLookback(rows=1)
            )
        }

    def decide(self, call):
        return vq.Rebalance.of(long={"A": Decimal(1)}, invested="1.0")
'''


def _parquets(root: Path) -> tuple[Path, Path]:
    """A daily observation and a MINUTE execution table: 09:00 to 09:10 KST, one row a minute,
    the price rising one unit a minute."""
    observation = root / "observation.parquet"
    execution = root / "execution.parquet"
    con = duckdb.connect()
    try:
        con.execute(
            f"""COPY (SELECT session_date, available_at, instrument, close::DOUBLE AS close
            FROM (VALUES
              (DATE '{DAY}', TIMESTAMPTZ '{DAY} 03:00:00+09', 'A', 100.0)
            ) AS t(session_date, available_at, instrument, close))
            TO '{observation.as_posix()}' (FORMAT PARQUET)"""
        )
        minutes = ",\n".join(
            f"(TIMESTAMPTZ '{DAY} 09:{minute:02d}:00+09', 'A', true, {100 + minute}.0)"
            for minute in range(0, 11)
        )
        con.execute(
            f"""COPY (SELECT trade_at, instrument, is_tradable, close::DOUBLE AS close
            FROM (VALUES
{minutes}
            ) AS t(trade_at, instrument, is_tradable, close))
            TO '{execution.as_posix()}' (FORMAT PARQUET)"""
        )
    finally:
        con.close()
    return observation, execution


def _workspace(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    observation, execution = _parquets(root)
    venue = root / "venue.py"
    venue.write_text(
        "from decimal import Decimal\n"
        "from vqapr.public import AcademicExchange, TradeRule\n"
        "from vqapr.public import ListingAccess\n"
        "class Venue(AcademicExchange):\n"
        "    def __init__(self):\n"
        "        super().__init__({'A': TradeRule('A', Decimal('1'), Decimal('1'), False,\n"
        "            ListingAccess.LONG_ONLY)})\n",
        encoding="utf-8",
    )
    (root / "always_long.py").write_text(_ALWAYS_LONG, encoding="utf-8")
    declaration = root / "workspace.yaml"
    declaration.write_text(
        f"""
datasets:
  prices:
    source_id: price-source
    path: {observation.as_posix()}
    instrument_field: instrument
    available_at: available_at
    grain: instrument_instant
    key_fields: [available_at, instrument]
    fields: {{close: close}}
    field_types: {{close: DOUBLE}}
  venue-minute:
    source_id: venue-source
    path: {execution.as_posix()}
    instrument_field: instrument
    available_at: trade_at
    grain: instrument_instant
    key_fields: [trade_at, instrument]
    fields: {{close: close, is_tradable: is_tradable}}
    field_types: {{close: DOUBLE, is_tradable: BOOLEAN}}
    execution: {{is_tradable: is_tradable}}
components:
  venue:
    kind: exchange
    path: {venue.as_posix()}
    object_name: Venue
  always-long:
    kind: strategy
    path: {(root / "always_long.py").as_posix()}
    object_name: AlwaysLong
""",
        encoding="utf-8",
    )
    code, payload = _cli(capsys, "--project-root", str(root), "register", str(declaration))
    assert code == 0, payload
    _register_roster(root, capsys, {"A": "stock"})


def _run(
    root: Path, capsys: pytest.CaptureFixture[str], run_id: str, execution: dict
) -> dict:
    runs = root / f"runs-{run_id}.yaml"
    runs.write_text(
        json.dumps(
            {
                "runs": {
                    run_id: {
                        "writes": f"{run_id}-weights",
                        "strategy": {"component": "always-long"},
                        "timezone": "Asia/Seoul",
                        # Six decisions, 09:00 to 09:05, one a minute.
                        "schedule": {"every": "1m", "from": "09:00", "to": "09:05"},
                        "exchange": "venue",
                        "execution": execution,
                        "start": datetime(2024, 3, 5, 0, tzinfo=_ZONE).isoformat(),
                        "end": datetime(2024, 3, 5, 23, tzinfo=_ZONE).isoformat(),
                        "initial_account": {"cash": "1000", "mode": "long_only"},
                        "instruments": ["A"],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    code, payload = _cli(capsys, "--project-root", str(root), "register", str(runs))
    assert code == 0, payload
    code, checked = _cli(capsys, "--project-root", str(root), "check", run_id)
    assert code == 0 and checked["ok"] is True, checked
    code, ran = _cli(capsys, "--project-root", str(root), "run", run_id)
    assert code == 0, ran
    assert ran["strategies"]["always-long"]["status"] == "completed"
    return ran


def _rows(root: Path, run_id: str, table: str, columns: str) -> list[tuple]:
    record = (root / ".vqapr" / "runs" / run_id).as_posix()
    con = duckdb.connect()
    try:
        return con.execute(
            f"SELECT {columns} FROM read_parquet('{record}/strategies/*/tables/{table}/*.parquet')"
            " ORDER BY 1"
        ).fetchall()
    finally:
        con.close()


def _minutes(rows: list[tuple]) -> list[int]:
    return [moment.astimezone(_ZONE).minute for moment, *_ in rows]


@pytest.mark.slow
def test_a_minute_schedule_with_the_default_fill_trades_at_the_next_minute(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """No fill block: each decision fills at the next minute. And the market clock values the
    book at all eleven minutes, decision or not (design §3.1)."""
    _workspace(tmp_path, capsys)
    _run(tmp_path, capsys, "minutely", {"dataset": "venue-minute", "trade_price": "close"})

    decisions = _rows(tmp_path, "minutely", "vqapr.weight", "DISTINCT event_time")
    first = datetime(2024, 3, 5, 9, 0, tzinfo=_ZONE)
    assert [moment.astimezone(_ZONE).replace(tzinfo=_ZONE) for (moment,) in decisions] == [
        first + timedelta(minutes=k) for k in range(6)
    ], "six decisions, one a minute, on the schedule clock"

    fills = _rows(tmp_path, "minutely", "vqapr.fill", "event_time, dealt_quantity")
    assert _minutes(fills) == [1, 2, 3, 4, 5, 6], "each decision filled at the NEXT minute"
    assert fills[0][1] != "0", "the first decision bought"
    assert all(dealt == "0" for _, dealt in fills[1:]), "already invested: nothing more to buy"

    navs = _rows(
        tmp_path,
        "minutely",
        "vqapr.account",
        "event_time, nav, stage",
    )
    account_rows = [row for row in navs if row[1] is not None]
    assert _minutes(account_rows) == list(range(0, 11)), (
        "the book is valued at EVERY market-clock instant, whether or not a decision fell there"
    )
    assert {stage for _, _, stage in account_rows} == {"VALUATION"}
    valued = [float(nav) for _, nav, _ in account_rows]
    assert valued[1:] == sorted(valued[1:]) and len(set(valued[1:])) == 10, (
        "a held book marked at a rising price has a rising NAV, minute by minute"
    )


@pytest.mark.slow
def test_a_pending_decision_survives_the_market_instants_before_its_fill(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`after: 5m` from a 09:00 decision fills at 09:05. The instants in between value the held
    book without consuming the pending decision; a later decision replaces it (§3.1: the
    pending slot holds one intent, and EXECUTE at 09:05 settles whichever is pending then)."""
    _workspace(tmp_path, capsys)
    _run(
        tmp_path,
        capsys,
        "delayed",
        {"dataset": "venue-minute", "trade_price": "close", "fill": {"after": "5m"}},
    )

    fills = _rows(tmp_path, "delayed", "vqapr.fill", "event_time, dealt_quantity")
    # Decisions at 09:00..09:05 each want 09:05..09:10; each later decision replaces the pending
    # one, so the first fill lands at 09:10 -- the target of the last decision -- and once.
    assert _minutes(fills) == [10], f"fills at {_minutes(fills)}"
    assert fills[0][1] != "0"

    navs = [row for row in _rows(tmp_path, "delayed", "vqapr.account", "event_time, nav") if row[1]]
    assert _minutes(navs) == list(range(0, 11)), "valued at every instant regardless of the fill"
