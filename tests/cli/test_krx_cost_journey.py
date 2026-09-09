"""The assertion whose absence let 1,300 tests pass while 64 fills recorded `0.00`.

A first-time-user journey was asked "do ETFs cost less to trade than stocks?" and could not answer
it. `vqapr new exchange` emitted a subclass of `AcademicExchange` whose `_rule()` returned four
arguments and no `buy`/`sell`, so the agent copied that shape onto a `KrxExchange` subclass and
produced a Korean venue that charged nothing. Registration accepted it, preflight accepted it,
`check` returned `ok`, the run completed, and every fill carried `commission: 0.00, tax: 0.00`.

Nothing refused, because nothing was wrong: a zero-cost venue is a legal, complete, reproducible
run. What was wrong was the scaffold, which taught the shape that silently zeroes the capability on
the one profile whose entire reason for existing is that it charges.

So this test asserts on **fill values**, never on registration returning `ok`. It drives the
emitted `--profile krx` scaffold end to end and checks the three facts the mission needed:
commission on both sides, sale tax on the stock, and no sale tax on the ETF.
"""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
import pytest

from vqapr.cli.main import main
from vqapr.record import read_table, strategy_refs

_ZONE = ZoneInfo("Asia/Seoul")
STOCK = "A005930"
ETF = "A069500"


def _cli(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, dict]:
    code = main(argv)
    out = capsys.readouterr().out.strip()
    return code, json.loads(out.splitlines()[-1])


def _parquets(root: Path) -> tuple[Path, Path]:
    """Prices that force a rotation, so the run both buys and sells each name.

    A journey that only ever buys cannot answer the question: the KRX sale tax is charged on the
    SELL side, and the ETF exemption is an exemption from exactly that. The closes below make the
    stock the strongest name on sessions 1 and 3 and the ETF strongest on session 2, so the run
    sells the stock into the ETF and then sells the ETF back.
    """
    observation = root / "observation.parquet"
    execution = root / "execution.parquet"
    rows = [
        # session, stock close, etf close
        ("2024-03-05", 100.0, 90.0),
        ("2024-03-06", 100.0, 120.0),
        ("2024-03-07", 150.0, 120.0),
        ("2024-03-08", 150.0, 120.0),
    ]
    con = duckdb.connect()
    try:
        observed = ",\n".join(
            f"(DATE '{day}', TIMESTAMPTZ '{day} 03:00:00+09', '{name}', {close})"
            for day, stock, etf in rows
            for name, close in ((STOCK, stock), (ETF, etf))
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
            for day, stock, etf in rows
            for name, close in ((STOCK, stock), (ETF, etf))
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


_STRATEGY = '''"""Holds whichever name closed highest, so leadership changes force a sale."""

from decimal import Decimal

from vqapr import authoring as va


class Rotate(va.StrategyModel):
    def inputs(self):
        return {
            "prices": va.DatasetInput(
                dataset_id="prices", fields=("close",), lookback=va.RowsLookback(rows=1)
            )
        }

    def decide(self, call):
        latest = {
            name: Decimal(str(value))
            for name, value in call.read("prices", "close").latest().items()
        }
        if not latest:
            return va.Hold(reason="no-observations")
        winner = max(latest, key=lambda name: latest[name])
        return va.Rebalance.of(long={winner: Decimal(1)}, invested="1.0")
'''


def _declaration(root: Path, observation: Path, execution: Path) -> Path:
    path = root / "workspace.yaml"
    path.write_text(
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
""",
        encoding="utf-8",
    )
    return path


@pytest.mark.slow
def test_the_krx_scaffold_charges_a_stock_and_exempts_an_etf(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`vqapr new exchange --profile krx`, run as emitted, charging what KRX charges.

    The venue under test is the scaffold's own output, edited only where its docstring says to
    edit: the category of the ETF. That is the whole point -- a scaffold is judged by what happens
    when a user copies it, not by whether the machinery behind it can be driven correctly by
    someone who already knows the answer.
    """
    observation, execution = _parquets(tmp_path)
    code, payload = _cli(
        capsys, "--project-root", str(tmp_path), "register", str(
            _declaration(tmp_path, observation, execution)
        )
    )
    assert code == 0, payload

    # The roster: what each id IS. The project's statement, not the venue's.
    from vqapr.domain.instruments import export_roster

    written = export_roster({STOCK: "stock", ETF: "etf"}, tmp_path / "roster")
    roster = tmp_path / "roster.yaml"
    roster.write_text(
        "instruments:\n  tables:\n"
        + "".join(
            f"    {kind}: {path.relative_to(tmp_path).as_posix()}\n"
            for kind, path in sorted(written.items())
        ),
        encoding="utf-8",
    )
    code, payload = _cli(capsys, "--project-root", str(tmp_path), "register", str(roster))
    assert code == 0, payload
    assert payload["registered"]["instruments"][0]["by_kind"] == {"stock": 1, "etf": 1}

    # The venue, emitted by the scaffold under test.
    code, emitted = _cli(
        capsys, "--project-root", str(tmp_path), "new", "exchange", "krx-venue",
        "--profile", "krx", "--instruments", STOCK, ETF,
    )
    assert code == 0, emitted
    source = Path(emitted["path"])
    body = source.read_text(encoding="utf-8")
    assert "krx_listings" in body, "the krx profile builds its trading facts from ids alone"
    # THE POINT: the emitted venue names no category anywhere. What each instrument is comes from
    # the registered roster at fill time, so there is nothing here to edit and nothing to keep in
    # step. A venue holding its own copy could disagree with the roster, and a fill would then say
    # one category and be charged as another (issue 013).
    for category in ("stock", "etf", "index", "factor"):
        assert f'"{category}"' not in body, (
            f"the scaffold declares {category!r}; a venue that names a category can disagree "
            "with the roster"
        )
    assert ETF in body and STOCK in body, "both ids are listed, as ids"
    # Run it exactly as emitted. No edit at all, which the previous version of this test needed.
    code, payload = _cli(
        capsys, "--project-root", str(tmp_path), "register", emitted["declaration"]
    )
    assert code == 0, payload

    (tmp_path / "rotate.py").write_text(_STRATEGY, encoding="utf-8")
    strategy = tmp_path / "rotate.yaml"
    strategy.write_text(
        f"""
components:
  rotate:
    kind: strategy
    path: {(tmp_path / "rotate.py").as_posix()}
    object_name: Rotate
""",
        encoding="utf-8",
    )
    code, payload = _cli(capsys, "--project-root", str(tmp_path), "register", str(strategy))
    assert code == 0, payload

    runs = tmp_path / "runs.yaml"
    runs.write_text(
        json.dumps(
            {
                "runs": {
                    "krx": {
                        "writes": "krx-weights",
                        "strategies": {"rotate": {}},
                        # Decide at 04:00 on every session the prices have a row for; the book
                        # is valued at the 15:30 fill it lands on (record 148).
                        "sessions_from": "prices",
                        "timezone": "Asia/Seoul",
                        "at": "04:00",
                        "exchange": "krx-venue",
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
                        "end": datetime(2024, 3, 8, 23, tzinfo=_ZONE).isoformat(),
                        "initial_account": {"cash": "1000000", "mode": "long_only"},
                        "instruments": [STOCK, ETF],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    code, payload = _cli(capsys, "--project-root", str(tmp_path), "register", str(runs))
    assert code == 0, payload

    code, ran = _cli(capsys, "--project-root", str(tmp_path), "run", "krx")

    assert code == 0, ran
    assert ran["roster"]["known"] is True
    assert ran["roster"]["by_kind"] == {"stock": 1, "etf": 1}

    store = tmp_path / ".vqapr"
    (strategy_ref,) = strategy_refs(store, "krx")
    assert ran["strategies"]["rotate"]["record"] == strategy_ref
    fills = [
        row
        for row in read_table(store, "krx", "vqapr.fill", strategy_ref)
        if Decimal(str(row.get("dealt_quantity") or 0)) != 0
    ]
    assert fills, "the journey must trade, or it proves nothing about what trading costs"

    # Every dealt fill carries the category the project declared, not the venue's guess.
    assert {row["kind"] for row in fills} <= {"stock", "etf"}

    charged = [row for row in fills if Decimal(str(row["commission"])) != 0]
    assert len(charged) == len(fills), (
        "KRX charges commission on both sides of every trade; a zero here is the defect this "
        f"test exists to catch: {fills}"
    )

    sells = [row for row in fills if Decimal(str(row.get("dealt_quantity") or 0)) < 0]
    stock_sales = [row for row in sells if row["kind"] == "stock"]
    etf_sales = [row for row in sells if row["kind"] == "etf"]
    assert stock_sales, "the rotation must sell the stock, or the tax assertion proves nothing"
    assert etf_sales, "the rotation must sell the ETF, or the exemption assertion proves nothing"

    # The whole question the journey could not answer.
    assert all(Decimal(str(row["tax"])) > 0 for row in stock_sales), (
        f"a KRX stock sale pays the sale tax: {stock_sales}"
    )
    assert all(Decimal(str(row["tax"])) == 0 for row in etf_sales), (
        f"a KRX ETF sale is exempt from the sale tax: {etf_sales}"
    )
