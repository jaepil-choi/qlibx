"""Execution table, roster, orders: three sets, two inclusions (design §6.2, record `203`).

```
execution table     A005930 (stock) + A069500 (etf) + A000660 (stock)   what the venue prices
roster              A005930                                             what the project declared
orders              whatever the strategy decides                       checked at the fill instant
```

Nothing is required between the roster and the table: an ETF may sit in the table undeclared as
long as nothing orders it. `orders ⊆ roster` is checked when the orders exist, and the refusal
names EVERY undeclared id in the batch rather than the first. Through the CLI, because the
envelope is what a reader meets.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
import pytest
from test_commands import _cli, _register_roster

STOCK, ETF, OTHER = "A005930", "A069500", "A000660"
_ZONE = ZoneInfo("Asia/Seoul")

_HOLDS_STOCK = '''"""Orders the one declared name and nothing else."""

from decimal import Decimal

from vqapr import authoring as va


class HoldsStock(va.StrategyModel):
    def inputs(self):
        return {
            "prices": va.DatasetInput(
                dataset_id="prices", fields=("close",), lookback=va.RowsLookback(rows=1)
            )
        }

    def decide(self, call):
        return va.Rebalance.of(long={"A005930": Decimal(1)}, invested="1.0")
'''

_WANTS_ALL = '''"""Orders every name in the table, two of which the project never declared."""

from decimal import Decimal

from vqapr import authoring as va


class WantsAll(va.StrategyModel):
    def inputs(self):
        return {
            "prices": va.DatasetInput(
                dataset_id="prices", fields=("close",), lookback=va.RowsLookback(rows=1)
            )
        }

    def decide(self, call):
        third = Decimal(1) / Decimal(3)
        return va.Rebalance.of(
            long={"A069500": third, "A005930": third, "A000660": third}, invested="1.0"
        )
'''


def _parquets(root: Path) -> tuple[Path, Path]:
    """Three names priced on two sessions: the table is wider than the roster on purpose."""
    observation = root / "observation.parquet"
    execution = root / "execution.parquet"
    names = (STOCK, ETF, OTHER)
    con = duckdb.connect()
    try:
        observed = ",\n".join(
            f"(DATE '{day}', TIMESTAMPTZ '{day} 03:00:00+09', '{name}', {close})"
            for day in ("2024-03-05", "2024-03-06")
            for name, close in zip(names, (100.0, 90.0, 50.0), strict=True)
        )
        con.execute(
            f"""COPY (SELECT session_date, available_at, instrument, close::DOUBLE AS close
            FROM (VALUES
{observed}
            ) AS t(session_date, available_at, instrument, close))
            TO '{observation.as_posix()}' (FORMAT PARQUET)"""
        )
        traded = ",\n".join(
            f"(TIMESTAMPTZ '{day} 15:30:00+09', '{name}', true, {close})"
            for day in ("2024-03-05", "2024-03-06")
            for name, close in zip(names, (100.0, 90.0, 50.0), strict=True)
        )
        con.execute(
            f"""COPY (SELECT trade_at, instrument, is_tradable, close::DOUBLE AS close
            FROM (VALUES
{traded}
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
        "from vqapr.exchange.venue import AcademicExchange, TradeRule\n"
        "from vqapr.exchange.listings import ListingAccess\n"
        "class Venue(AcademicExchange):\n"
        "    def __init__(self):\n"
        "        super().__init__({name: TradeRule(name, Decimal('1'), Decimal('1'), False,\n"
        f"            ListingAccess.LONG_ONLY) for name in {(STOCK, ETF, OTHER)!r}}})\n",
        encoding="utf-8",
    )
    (root / "holds_stock.py").write_text(_HOLDS_STOCK, encoding="utf-8")
    (root / "wants_all.py").write_text(_WANTS_ALL, encoding="utf-8")
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
  venue-daily:
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
  holds-stock:
    kind: strategy
    path: {(root / "holds_stock.py").as_posix()}
    object_name: HoldsStock
  wants-all:
    kind: strategy
    path: {(root / "wants_all.py").as_posix()}
    object_name: WantsAll
""",
        encoding="utf-8",
    )
    code, payload = _cli(capsys, "--project-root", str(root), "register", str(declaration))
    assert code == 0, payload
    # The roster declares ONE of the three names the table prices.
    _register_roster(root, capsys, {STOCK: "stock"})


def _run(root: Path, capsys: pytest.CaptureFixture[str], run_id: str, strategy: str) -> None:
    body = {
        "writes": f"{run_id}-weights",
        "strategy": {"component": strategy},
        "timezone": "Asia/Seoul",
        "agenda": {"every": "1d", "at": "04:00"},
        "exchange": "venue",
        "execution": {
            "dataset": "venue-daily",
            "fill": {
                "selector": "next_eligible",
                "at": "15:30",
                "timezone": "Asia/Seoul",
                "trade_price": "close",
            },
        },
        "start": datetime(2024, 3, 5, 0, tzinfo=_ZONE).isoformat(),
        "end": datetime(2024, 3, 6, 23, tzinfo=_ZONE).isoformat(),
        "initial_account": {"cash": "1000000", "mode": "long_only"},
        "instruments": [STOCK, ETF, OTHER],
    }
    path = root / f"runs-{run_id}.yaml"
    path.write_text(json.dumps({"runs": {run_id: body}}), encoding="utf-8")
    code, payload = _cli(capsys, "--project-root", str(root), "register", str(path))
    assert code == 0, payload


def test_a_strategy_that_orders_only_declared_names_runs_over_a_wider_table(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An ETF in the table, a share in the roster, a share in the orders: it runs."""
    _workspace(tmp_path, capsys)
    _run(tmp_path, capsys, "narrow", "holds-stock")

    code, checked = _cli(capsys, "--project-root", str(tmp_path), "check", "narrow")
    assert code == 0, checked
    assert checked["ok"] is True, "the table being wider than the roster is not a defect"

    code, ran = _cli(capsys, "--project-root", str(tmp_path), "run", "narrow")

    assert code == 0, ran
    assert ran["roster"]["known"] is True
    assert ran["roster"]["by_kind"] == {"stock": 1}
    assert ran["strategies"]["holds-stock"]["status"] == "completed"
    fills = (
        duckdb.connect()
        .execute(
            "SELECT instrument, kind, dealt_quantity FROM read_parquet("
            f"'{(tmp_path / '.vqapr' / 'runs' / 'narrow').as_posix()}/strategies/*/tables/"
            "vqapr.fill/*.parquet')"
        )
        .fetchall()
    )
    assert fills, "the declared name was filled"
    assert {name for name, _, _ in fills} == {STOCK}
    # A zero-dealt row (the second session changes nothing) carries no category; the dealt one
    # is stamped with what the roster said.
    assert {kind for _, kind, dealt in fills if dealt != "0"} == {"stock"}


def test_an_order_for_undeclared_names_fails_the_run_naming_every_one_of_them(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The runtime half of the gate. `check` cannot see it -- which ids get ordered is the
    strategy's decision -- and the refusal lists both undeclared ids, not the first."""
    _workspace(tmp_path, capsys)
    _run(tmp_path, capsys, "wide", "wants-all")

    code, checked = _cli(capsys, "--project-root", str(tmp_path), "check", "wide")
    assert code == 0, checked
    assert checked["ok"] is True, "preflight can only know that SOMETHING is declared"

    code, ran = _cli(capsys, "--project-root", str(tmp_path), "run", "wide")

    assert code == 1, ran
    assert ran["ok"] is False
    assert ran["stage"] == "run.strategy_failed"
    block = ran["strategies"]["wants-all"]
    assert block["status"] == "failed"
    assert block["stage"] == "simulation.due.instrument_declaration"
    assert block["kind"] == "PRE_COMMIT", "refused before any fill reached the account"
    (failure,) = ran["failures"]
    assert failure["code"] == "instrument.undeclared"
    assert failure["status"] == 412
    assert ETF in failure["observed"] and OTHER in failure["observed"]
    assert STOCK not in failure["observed"].split("reached")[-1], "the declared one is not named"
    assert "vqapr register" in failure["fix"]
    assert not list((tmp_path / ".vqapr" / "runs" / "wide").rglob("vqapr.fill/*.parquet")), (
        "no fill was recorded for a batch the gate refused"
    )
