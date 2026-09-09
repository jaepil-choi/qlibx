"""AC-1 of the two-clocks campaign: a strategy that decides every minute fills every minute.

Design §3.4 gives the agenda `every: 1m` with `from`/`to`; §3.5 gives the fill its default,
"the first market-clock instant after the decision" -- on a minute table, the next minute. No
selector, no fill wall time, no fill zone: the market clock is the table and the strategy clock
is the rule. Through the CLI, the way a user would declare it (record `205`).
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

from vqapr import authoring as va


class AlwaysLong(va.StrategyModel):
    def inputs(self):
        return {
            "prices": va.DatasetInput(
                dataset_id="prices", fields=("close",), lookback=va.RowsLookback(rows=1)
            )
        }

    def decide(self, call):
        return va.Rebalance.of(long={"A": Decimal(1)}, invested="1.0")
'''


def _parquets(root: Path) -> tuple[Path, Path]:
    """A daily observation and a MINUTE execution table: 09:00 to 09:10 KST, one row a minute."""
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


@pytest.mark.slow
def test_a_minute_agenda_with_the_default_fill_trades_at_the_next_minute(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    observation, execution = _parquets(tmp_path)
    venue = tmp_path / "venue.py"
    venue.write_text(
        "from decimal import Decimal\n"
        "from vqapr.exchange.venue import AcademicExchange, TradeRule\n"
        "from vqapr.exchange.listings import ListingAccess\n"
        "class Venue(AcademicExchange):\n"
        "    def __init__(self):\n"
        "        super().__init__({'A': TradeRule('A', Decimal('1'), Decimal('1'), False,\n"
        "            ListingAccess.LONG_ONLY)})\n",
        encoding="utf-8",
    )
    (tmp_path / "always_long.py").write_text(_ALWAYS_LONG, encoding="utf-8")
    declaration = tmp_path / "workspace.yaml"
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
    path: {(tmp_path / "always_long.py").as_posix()}
    object_name: AlwaysLong
""",
        encoding="utf-8",
    )
    code, payload = _cli(capsys, "--project-root", str(tmp_path), "register", str(declaration))
    assert code == 0, payload
    _register_roster(tmp_path, capsys, {"A": "stock"})

    runs = tmp_path / "runs.yaml"
    runs.write_text(
        json.dumps(
            {
                "runs": {
                    "minutely": {
                        "writes": "minutely-weights",
                        "strategy": {"component": "always-long"},
                        "timezone": "Asia/Seoul",
                        # Six decisions, 09:00 to 09:05, one a minute. No fill block: each fills
                        # at the first execution instant after it, the next minute.
                        "agenda": {"every": "1m", "from": "09:00", "to": "09:05"},
                        "exchange": "venue",
                        "execution": {"dataset": "venue-minute", "trade_price": "close"},
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
    code, payload = _cli(capsys, "--project-root", str(tmp_path), "register", str(runs))
    assert code == 0, payload

    code, checked = _cli(capsys, "--project-root", str(tmp_path), "check", "minutely")
    assert code == 0, checked
    assert checked["ok"] is True

    code, ran = _cli(capsys, "--project-root", str(tmp_path), "run", "minutely")

    assert code == 0, ran
    assert ran["strategies"]["always-long"]["status"] == "completed"
    record = (tmp_path / ".vqapr" / "runs" / "minutely").as_posix()
    con = duckdb.connect()
    try:
        decisions = con.execute(
            f"SELECT DISTINCT event_time FROM read_parquet('{record}/strategies/*/tables/"
            "vqapr.weight/*.parquet') ORDER BY 1"
        ).fetchall()
        fills = con.execute(
            f"SELECT event_time, dealt_quantity FROM read_parquet('{record}/strategies/*/tables/"
            "vqapr.fill/*.parquet') ORDER BY 1"
        ).fetchall()
    finally:
        con.close()
    first = datetime(2024, 3, 5, 9, 0, tzinfo=_ZONE)
    assert [moment.astimezone(_ZONE).replace(tzinfo=_ZONE) for (moment,) in decisions] == [
        first + timedelta(minutes=k) for k in range(6)
    ], "six decisions, one a minute, on the strategy clock"
    fill_minutes = [moment.astimezone(_ZONE).minute for moment, _ in fills]
    assert fill_minutes == [1, 2, 3, 4, 5, 6], "each decision filled at the NEXT minute"
    assert fills[0][1] != "0", "the first decision bought"
    assert all(dealt == "0" for _, dealt in fills[1:]), "already invested: nothing more to buy"
