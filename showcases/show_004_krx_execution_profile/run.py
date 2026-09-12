"""The same real signal executed through two profiles.

One frozen strategy, one real KRX price history, two execution profiles::

    Academic   fractional quantity, zero cost, full fill
    KRX-shaped whole shares, 3bp commission both sides, 20bp sale tax on sells, long only

The two runs differ **only** by the registered exchange component -- everything else (the
materialized score, the strategy, the execution dataset, the agendas) is byte-identical, so
the difference in outcome is exactly the declared venue friction.

**Both venues are the shipped ones.** ``ShowcaseKrxExchange`` extends ``KrxExchange``, so the
whole-share step, the 3bp commission on both sides, the 20bp sale tax on sells and the
long-only access all come from the package's own KRX terms rather than being reproduced on an
academic venue. An earlier revision of this showcase had to approximate them, because the
surface it was written against typed its exchange field to one academic class; that caveat is
gone and the comparison now measures the real engine class.

Neither profile models price ticks, queue position, liquidity or borrow. This fixture trades
stocks only and never exercises a price limit.

Reproduce::

    uv run python showcases/show_004_krx_execution_profile/run.py
"""

from __future__ import annotations

import argparse
import html
import json
import shutil
import sys
from collections.abc import Mapping
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb

# The showcase's own directory is not guaranteed to be on sys.path - an acceptance
# test importing this module runs from the repo root. Locate it explicitly.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import show004_models as models

from vqapr.cli.register import run as register_cli
from vqapr.public import (
    AccountMode,
    AccountSnapshot,
    ComponentRef,
    DataModelEntry,
    DatasetRegistration,
    RunDefinition,
    RunExecution,
    RunFill,
    RunSchedule,
    SourceSpec,
    StrategyEntry,
    export_roster,
    freeze,
    register_data_model,
    register_dataset,
    register_exchange,
    register_strategy_model,
    run,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from extract_dw_fixture import FixtureSpec, extract

ROOT = Path(__file__).resolve().parent
MODELS = Path(models.__file__).resolve()
"""Resolved through the imported module, not by name.

`MomentumLongOnly` is authored against `vqapr.public`, so the loader adapts it and the
adapter re-imports the authored class by module name. Importing it here is what gives that
name something to resolve to.
"""
OUTPUTS = ROOT / "outputs"
INPUTS = OUTPUTS / "inputs"
PROJECT = OUTPUTS / "project"
VENUE = "Asia/Seoul"
OFFSET = "+09:00"
INITIAL_CASH = Decimal("1000000000")
VERIFIED_AGAINST = "vqapr-0.16.0"
LAST_VERIFIED_AT = "2026-09-10"

KRX_COMMISSION_RATE = Decimal("0.0003")
"""Brokerage commission charged on both sides -- matches vqapr.component.exchange.krx."""

KRX_SALE_TAX_RATE = Decimal("0.002")
"""Securities transaction tax charged on sells only -- matches vqapr.component.exchange.krx."""

SPEC = FixtureSpec(asof="20260331", start="20260401", end="20260529", universe_size=6)


def _reset_outputs() -> None:
    if OUTPUTS.exists():
        shutil.rmtree(OUTPUTS)
    OUTPUTS.mkdir(parents=True)


def _sessions(path: Path) -> list[date]:
    con = duckdb.connect()
    try:
        return [
            row[0]
            for row in con.execute(
                f"""
                SELECT DISTINCT CAST(available_at AT TIME ZONE '{VENUE}' AS DATE) AS session
                FROM read_parquet('{path.as_posix()}') ORDER BY session
                """
            ).fetchall()
        ]
    finally:
        con.close()


def _definition(
    *,
    universe: tuple[str, ...],
    exchange: ComponentRef,
    strategy_ref: ComponentRef,
    callback_days: list[date],
) -> RunDefinition:
    """The two runs' one difference, isolated into one argument.

    Everything else is shared by construction rather than by copy: the same registered
    strategy, the same sessions and wall time, the same execution dataset and fill, the same account.
    """
    return RunDefinition(
        run_id=exchange.component_id,
        strategy=StrategyEntry(str(strategy_ref.component_id)),
        timezone=VENUE,
        schedule=RunSchedule(every="1d", at=(time(8, 30),)),
        exchange=exchange.component_id,
        execution=RunExecution(
            dataset="krx-daily",
            trade_price="close",
            fill=RunFill(at=time(15, 30)),
        ),
        start=datetime.fromisoformat(f"{callback_days[0].isoformat()}T00:00:00{OFFSET}"),
        end=datetime.fromisoformat(f"{callback_days[-1].isoformat()}T23:00:00{OFFSET}"),
        initial_account_snapshot=AccountSnapshot(0, INITIAL_CASH, {}),
        initial_account_mode=AccountMode.LONG_ONLY,
        instruments=universe,
        writes=f"{exchange.component_id}-weights",
    )


def _write_exchanges(universe: tuple[str, ...]) -> dict[str, Path]:
    """The two venues, as registrable components.

    Written to disk because a registered component is resolved by re-importing its module and
    looking the class up by name; a class built inside `main()` has no import location.
    """
    components = PROJECT / "components"
    components.mkdir(parents=True, exist_ok=True)

    academic = components / "academic_exchange.py"
    academic.write_text(
        f'''"""Fractional quantity, zero cost, full fill."""

from __future__ import annotations

from decimal import Decimal

from vqapr.public import AcademicExchange, ListingAccess, TradeRule

UNIVERSE = {universe!r}


class ShowcaseAcademicExchange(AcademicExchange):
    def __init__(self):
        super().__init__(
            {{
                instrument: TradeRule(
                    instrument,
                    Decimal("0.00000001"),
                    Decimal("0.00000001"),
                    True,
                    ListingAccess.SIGNED,
                )
                for instrument in UNIVERSE
            }},
            "show004-academic",
        )
''',
        encoding="utf-8",
    )

    krx = components / "krx_exchange.py"
    krx.write_text(
        f'''"""Whole shares, 3bp commission both sides, 20bp sale tax, long only."""

from __future__ import annotations

from vqapr.public import KrxExchange

UNIVERSE = {universe!r}


class ShowcaseKrxExchange(KrxExchange):
    def __init__(self):
        # `price_limits` stays off by omission: the fixture carries a close and no base price,
        # and a venue that declared a limit band would demand a price this table does not have.
        super().__init__(UNIVERSE, "show004-krx")
''',
        encoding="utf-8",
    )
    return {"academic": academic, "krx": krx}


def _recorded_fills(result: Any) -> list[dict[str, Any]]:
    """Every committed fill, from the run's own published record.

    The Account no longer carries the whole journal -- it is published to ``vqapr.fill`` and
    dropped -- so replaying its arithmetic reads the record. Rows arrive in commit order, which
    is the order the Account applied them.
    """
    return [dict(row) for row in result.final_state.recorder_rows.get("vqapr.fill", ())]


def _profile_outcome(result: Any) -> dict[str, Any]:
    """The KRX/Academic comparison, built from the committed Account and the fill record."""
    account = result.final_state.account.snapshot
    commission = Decimal("0")
    tax = Decimal("0")
    dealt = 0
    traded_notional = Decimal("0")
    for row in _recorded_fills(result):
        if Decimal(row["dealt_quantity"]) == 0:
            continue
        dealt += 1
        commission += Decimal(row["commission"] or 0)
        tax += Decimal(row["tax"] or 0)
        # Notional is a derived value, so the record carries its two factors instead.
        traded_notional += abs(Decimal(row["dealt_quantity"])) * Decimal(row["price"])

    replay_cash = INITIAL_CASH
    replay_positions: dict[str, Decimal] = {}
    for row in _recorded_fills(result):
        if Decimal(row["dealt_quantity"]) == 0:
            continue
        replay_cash += Decimal(row["cash_delta"])
        held = replay_positions.get(str(row["instrument"]), Decimal("0")) + Decimal(
            row["dealt_quantity"]
        )
        if held == 0:
            replay_positions.pop(str(row["instrument"]), None)
        else:
            replay_positions[str(row["instrument"])] = held
    if replay_cash != account.cash:
        raise AssertionError(f"cash replay {replay_cash} != committed {account.cash}")
    if replay_positions != dict(account.positions):
        raise AssertionError("position replay does not match the committed Account")

    whole_shares = all(
        quantity == quantity.to_integral_value() for quantity in account.positions.values()
    )
    # `run_completed()` exposes cash/positions but no committed NAV -- unlike the legacy
    # engine's `Account.latest_mark`, `RunAccount` carries no valuation. NAV is therefore
    # reported as cash + the mark-to-close value of every held position, valued at each
    # instrument's own last dealt fill price -- the same close the run itself last traded
    # at, not a second independently-fetched price.
    last_price: dict[str, Decimal] = {}
    for row in _recorded_fills(result):
        if row["price"] is not None:
            last_price[str(row["instrument"])] = Decimal(row["price"])
    marked_value = sum(
        (quantity * last_price[instrument] for instrument, quantity in account.positions.items()
         if instrument in last_price),
        Decimal("0"),
    )
    final_nav = account.cash + marked_value

    return {
        "final_nav": final_nav,
        "final_cash": account.cash,
        "positions": {k: str(v) for k, v in sorted(account.positions.items())},
        "dealt_fills": dealt,
        "traded_notional": traded_notional,
        "commission": commission,
        "tax": tax,
        "total_cost": commission + tax,
        "account_version": account.version,
        "whole_share_positions": whole_shares,
        "replay_matches_account": True,
    }


def _row(label: str, academic: Any, krx: Any) -> dict[str, Any]:
    return {"metric": label, "academic": str(academic), "krx": str(krx)}


def _table(rows: list[Mapping[str, Any]]) -> str:
    if not rows:
        return "<p>No rows.</p>"
    columns = list(rows[0])
    head = "".join(f"<th>{html.escape(str(c))}</th>" for c in columns)
    body = "".join(
        "<tr>" + "".join(f"<td>{html.escape(str(r[c]))}</td>" for c in columns) + "</tr>"
        for r in rows
    )
    return f"<table><tr>{head}</tr>{body}</table>"


def _report(trace: dict[str, Any]) -> str:
    comparison = _table(trace["comparison"])
    universe = _table(trace["universe"])
    drag = html.escape(json.dumps(trace["cost_drag"], indent=2, ensure_ascii=False, default=str))
    return f"""<!doctype html><meta charset="utf-8"><title>vqapr execution profiles</title>
<style>
body{{font-family:system-ui;max-width:1100px;margin:2rem auto;line-height:1.5}}
pre,table{{border:1px solid #ccc;padding:1rem;overflow:auto}}
td,th{{padding:.35rem .6rem;border:1px solid #ddd;text-align:right}}
td:first-child,th:first-child{{text-align:left}}
</style>
<h1>One real signal, two execution profiles</h1>
<p>Both runs use the same frozen strategy, the same real KRX closes and the same agendas. They
differ only by the registered exchange component.</p>
<h2>Universe</h2>{universe}
<h2>Outcome</h2>{comparison}
<h2>Cost drag attributable to the KRX profile</h2><pre>{drag}</pre>
<p>Academic charges nothing and trades fractional quantity. The KRX profile charges 3bp
commission on both sides, 20bp sale tax on sells, trades whole shares only and refuses short
positions. Neither profile models price ticks, price limits, queue position, liquidity or
borrow.</p>
<p>Verified against {VERIFIED_AGAINST}; last verified {LAST_VERIFIED_AT}.</p>"""


def main() -> None:
    _reset_outputs()
    fixture = extract(SPEC, INPUTS)
    observation_path = INPUTS / str(fixture["observation_path"])
    execution_path = INPUTS / str(fixture["execution_path"])
    universe = tuple(str(row["ticker"]) for row in fixture["universe"])
    sessions = _sessions(observation_path)
    score_days = sessions[5:-1]
    callback_days = sessions[6:]

    register_dataset(
        PROJECT,
        DatasetRegistration.of(
            "price_daily",
            "krx-observation",
            instrument_field="instrument",
            available_at="available_at",
            grain="instrument_instant",
            key_fields=("available_at", "instrument"),
            # The extracted slice stores close as DECIMAL(18, 4), which no field may be declared
            # as (issue 088): cast to DOUBLE here; the model already reads it as float.
            fields={"close": "CAST(close AS DOUBLE)", "is_supervised": "is_supervised"},
            field_types={"close": "DOUBLE", "is_supervised": "BOOLEAN"},
        ),
        SourceSpec.of("krx-observation", observation_path),
    )
    register_dataset(
        PROJECT,
        # The venue table is a dataset with an execution role (record 185): `trade_at` is the
        # instant its row is a fact about, the role names the tradable flag, and which price
        # a run fills at is that run's own `execution.fill.trade_price`.
        DatasetRegistration.of(
            "krx-daily",
            "krx-execution",
            instrument_field="instrument",
            available_at="trade_at",
            grain="instrument_instant",
            key_fields=("trade_at", "instrument"),
            fields={"close": "CAST(close AS DOUBLE)", "is_tradable": "is_tradable"},
            field_types={"close": "DOUBLE", "is_tradable": "BOOLEAN"},
            execution={"is_tradable": "is_tradable"},
        ),
        SourceSpec.of("krx-execution", execution_path),
    )

    # The materialized score registers itself as an ordinary dataset, so the strategy declares
    # `momentum_score` and reads it the same way it reads any other. Nothing re-exports it.
    register_data_model(PROJECT, "momentum-model", MODELS, "MomentumModel")
    score_definition = RunDefinition(
        run_id="momentum-score",
        instruments=universe,
        datamodel=DataModelEntry("momentum-model", ("score", "eligible")),
        timezone=VENUE,
        schedule=RunSchedule(every="1d", at=(time(16, 0),), days_from="price_daily"),
        start=datetime.fromisoformat(f"{score_days[0].isoformat()}T00:00:00{OFFSET}"),
        end=datetime.fromisoformat(f"{score_days[-1].isoformat()}T23:00:00{OFFSET}"),
        writes="momentum_score",
    )
    run(PROJECT, freeze(PROJECT, score_definition), store_root=PROJECT / ".vqapr")

    # The project declares what each id IS, once, before anything trades. KrxExchange resolves
    # what a fill COSTS from this roster rather than from the venue, which is why the KRX profile
    # cannot run without it: a venue that stated its own categories would be stating a fact that
    # was never its own. This fixture is stocks only, so every name is declared a stock.
    written = export_roster(dict.fromkeys(universe, "stock"), PROJECT)
    declaration = PROJECT / "instruments.yaml"
    declaration.write_text(
        "instruments:\n  tables:\n"
        + "".join(f"    {kind}: {path.name}\n" for kind, path in sorted(written.items())),
        encoding="utf-8",
    )
    # Registered through the CLI's own entry point, which is what a user runs. Reaching past it
    # would let this showcase pass while `vqapr register` was broken.
    register_cli(argparse.Namespace(declaration=str(declaration)), project_root=PROJECT)

    exchanges = _write_exchanges(universe)
    strategy_ref = register_strategy_model(
        PROJECT, "momentum-strategy", MODELS, "MomentumLongOnly",
    )
    academic_ref = register_exchange(
        PROJECT, "show004-academic", exchanges["academic"], "ShowcaseAcademicExchange",
    )
    krx_ref = register_exchange(PROJECT, "show004-krx", exchanges["krx"], "ShowcaseKrxExchange")


    def _outcome(exchange: ComponentRef) -> dict[str, Any]:
        definition = _definition(
            universe=universe,
            exchange=exchange,
            strategy_ref=strategy_ref,
            callback_days=callback_days,
        )
        return _profile_outcome(run(PROJECT, freeze(PROJECT, definition)).result())

    academic = _outcome(academic_ref)
    krx = _outcome(krx_ref)

    if not krx["whole_share_positions"]:
        raise AssertionError("the KRX profile must hold whole shares only")
    if academic["total_cost"] != 0:
        raise AssertionError("the Academic profile must charge nothing")
    if krx["total_cost"] <= 0:
        raise AssertionError("the KRX profile must charge its declared costs")

    nav_gap = academic["final_nav"] - krx["final_nav"]
    trace = {
        "status": "current",
        "verified_against": VERIFIED_AGAINST,
        "last_verified_at": LAST_VERIFIED_AT,
        "fixture": fixture,
        "universe": [
            {"ticker": r["ticker"], "name": r["name"], "index_weight": r["index_weight"]}
            for r in fixture["universe"]
        ],
        "comparison": [
            _row("final NAV", academic["final_nav"], krx["final_nav"]),
            _row("final cash", academic["final_cash"], krx["final_cash"]),
            _row("dealt fills", academic["dealt_fills"], krx["dealt_fills"]),
            _row("traded notional", academic["traded_notional"], krx["traded_notional"]),
            _row("commission", academic["commission"], krx["commission"]),
            _row("sale tax", academic["tax"], krx["tax"]),
            _row("total cost", academic["total_cost"], krx["total_cost"]),
            _row(
                "whole shares only", academic["whole_share_positions"], krx["whole_share_positions"]
            ),
            _row("account version", academic["account_version"], krx["account_version"]),
            _row(
                "replay matches", academic["replay_matches_account"], krx["replay_matches_account"]
            ),
        ],
        "cost_drag": {
            "nav_gap": str(nav_gap),
            "krx_total_cost": str(krx["total_cost"]),
            "krx_commission": str(krx["commission"]),
            "krx_sale_tax": str(krx["tax"]),
            "krx_traded_notional": str(krx["traded_notional"]),
            "effective_cost_bps_of_notional": str(
                (krx["total_cost"] / krx["traded_notional"] * Decimal("10000")).quantize(
                    Decimal("0.01")
                )
            )
            if krx["traded_notional"]
            else None,
            "claim": (
                "The two runs share one frozen strategy, dataset and execution table. The NAV "
                "gap therefore combines the declared KRX cost with the whole-share rounding "
                "residual; it is not a separate signal."
            ),
        },
        "academic": {k: str(v) for k, v in academic.items()},
        "krx": {k: str(v) for k, v in krx.items()},
        "exchange_surface_note": (
            "Both venues are the shipped engine classes: AcademicExchange and KrxExchange. "
            "The KRX economics measured here (whole shares, 3bp commission both sides, 20bp "
            "sale tax on sells, long only) come from the package's own KRX terms rather than "
            "being reproduced on an academic venue. Price limits are off, because the fixture "
            "carries a close and no base price."
        ),
    }

    (OUTPUTS / "trace.json").write_text(
        json.dumps(trace, indent=2, default=str, ensure_ascii=False), encoding="utf-8"
    )
    (OUTPUTS / "report.html").write_text(_report(trace), encoding="utf-8")
    print(OUTPUTS / "report.html")


if __name__ == "__main__":
    main()
