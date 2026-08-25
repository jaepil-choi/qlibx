"""The same real signal executed through two profiles.

One frozen strategy, one real KRX price history, two execution profiles::

    Academic   fractional quantity, zero cost, full fill
    KRX-shaped whole shares, 3bp commission both sides, 20bp sale tax on sells, long only

The two runs differ **only** by the declared ``venues.Academic`` venue -- everything else
(the derived score, the strategy, the execution input) is byte-identical, so the
difference in outcome is exactly the declared venue friction.

Migrated from the legacy engine-registration spine (``preflight_run``/``run``/
``register_component``, imported from the deprecated public-adapter module) onto the supported
``Project``/``vqapr.simulation``/``vqapr.authoring`` surface.

**No ``venues.Krx`` exists on the supported surface.** ``Simulation.exchange`` is strictly
typed to ``venues.Academic``. The KRX economics this showcase measures (whole shares, 3bp
commission both sides, 20bp sale tax on sells, long only) are reproduced *on* ``Academic``
(``quantity_step=1``, matching buy/sell ``VenueCost``, ``ListingAccess.LONG_ONLY``) --
this reproduces the shipped ``KrxExchange``'s declared rates exactly but not its
KRX-specific mechanics (price-limit bands, the ETF/stock tax-exemption split) that
``Academic`` has no field for. This fixture trades stocks only and never exercises a
price limit, so the substitution is exact for what this showcase actually measures; see
`show_008`'s module docstring for the same documented substitution.

The dataset-store split that once forced this showcase to keep a legacy
``register_dataset`` call is fixed: ``Project.simulate()`` bridges catalog-registered
datasets into the store preflight reads, so a plain ``Project.register(DatasetDeclaration)``
is now sufficient. ``completed.fills()`` replaces the old ``recorder_rows`` reach-through
for the account/cost readback this showcase's whole comparison is built from.

Reproduce::

    uv run python showcases/show_004_krx_execution_profile/run.py
"""

from __future__ import annotations

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

import vqapr
from vqapr.project import DatasetDeclaration
from vqapr.simulation import (
    AccountMode,
    AccountSnapshot,
    Cadence,
    Execution,
    ExecutionInput,
    FillConvention,
    FillSelector,
    InitialAccount,
    Schedule,
    Simulation,
)
from vqapr.venues import Academic, Listing, ListingAccess, VenueCost

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from extract_dw_fixture import FixtureSpec, extract

ROOT = Path(__file__).resolve().parent
OUTPUTS = ROOT / "outputs"
INPUTS = OUTPUTS / "inputs"
PROJECT = OUTPUTS / "project"
VENUE = "Asia/Seoul"
OFFSET = "+09:00"
INITIAL_CASH = Decimal("1000000000")
VERIFIED_AGAINST = "vqapr-0.1.0+show-004-working-tree"
LAST_VERIFIED_AT = "2026-08-25"

KRX_COMMISSION_RATE = Decimal("0.0003")
"""Brokerage commission charged on both sides -- matches vqapr.exchange.venues.krx."""

KRX_SALE_TAX_RATE = Decimal("0.002")
"""Securities transaction tax charged on sells only -- matches vqapr.exchange.venues.krx."""

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


def _simulation(*, universe: tuple[str, ...], execution_path: Path, exchange: Academic,
                 callback_days: list[date]) -> Simulation:
    start = datetime.fromisoformat(f"{callback_days[0].isoformat()}T00:00:00{OFFSET}")
    end = datetime.fromisoformat(f"{callback_days[-1].isoformat()}T23:00:00{OFFSET}")
    return Simulation(
        schedule=Schedule(
            strategy=Cadence(sessions=tuple(callback_days), at=time(8, 30), timezone=VENUE),
            valuation=Cadence(sessions=tuple(callback_days), at=time(16, 0), timezone=VENUE),
            monitoring=None,
            start=start,
            end=end,
        ),
        execution=Execution(
            input=ExecutionInput(
                input_id="krx-daily",
                path=execution_path,
                hive_partitioned=False,
                trade_at_field="trade_at",
                instrument_field="instrument",
                is_tradable_field="is_tradable",
                price_fields={"close": "close"},
            ),
            fill=FillConvention(
                selector=FillSelector.SAME_DAY, at=time(15, 30), timezone=VENUE, trade_price="close"
            ),
        ),
        exchange=exchange,
        account=InitialAccount(
            snapshot=AccountSnapshot(version=0, cash=INITIAL_CASH, positions={}),
            mode=AccountMode.LONG_ONLY,
        ),
        constraints=(),
        instruments=universe,
        initial_strategy_state=None,
    )


def _register_momentum_score(project: Any) -> None:
    """Re-register the materialized momentum score as a physical dataset.

    ``Project.simulate()``/``run_completed()`` resolve a Strategy's declared inputs
    through the legacy Workspace-backed store, while ``Project.materialize`` persists
    into the transactional catalog only; a materialized ("derived") dataset is invisible
    to a Simulation unless it is also written out as an ordinary physical parquet and
    registered as such -- the same bridge show_008 uses for its members.
    """
    rows = project.read_output("momentum_score__derived")
    out_path = PROJECT / "momentum_score.parquet"
    con = duckdb.connect()
    try:
        con.execute(
            "CREATE TABLE t (available_at TIMESTAMPTZ, instrument VARCHAR, "
            "score VARCHAR, eligible BOOLEAN)"
        )
        for row in rows:
            con.execute(
                "INSERT INTO t VALUES (?, ?, ?, ?)",
                [
                    row["evaluation_time"],
                    row["instrument_id"],
                    str(row["values"]["score"]),
                    bool(row["values"]["eligible"]),
                ],
            )
        con.execute(
            "COPY (SELECT available_at, instrument, CAST(score AS DOUBLE) AS score, eligible "
            f"FROM t) TO '{out_path.as_posix()}' (FORMAT PARQUET)"
        )
    finally:
        con.close()

    project.register(
        DatasetDeclaration(
            dataset_id="momentum_score",
            path=out_path,
            hive_partitioned=False,
            instrument_field="instrument",
            available_at_field="available_at",
            key_fields=("available_at", "instrument"),
            fields={"score": "score", "eligible": "eligible"},
        )
    )


def _profile_outcome(completed: Any) -> dict[str, Any]:
    """The KRX/Academic comparison, built from ``completed.account``/``completed.fills()`` --
    the public run readback -- rather than from engine internals."""
    account = completed.account
    commission = Decimal("0")
    tax = Decimal("0")
    dealt = 0
    traded_notional = Decimal("0")
    for row in completed.fills():
        if Decimal(row["dealt_quantity"]) == 0:
            continue
        dealt += 1
        commission += Decimal(row["commission"] or 0)
        tax += Decimal(row["tax"] or 0)
        # Notional is a derived value, so the record carries its two factors instead.
        traded_notional += abs(Decimal(row["dealt_quantity"])) * Decimal(row["price"])

    replay_cash = INITIAL_CASH
    replay_positions: dict[str, Decimal] = {}
    for row in completed.fills():
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
    for row in completed.fills():
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
differ only by the declared <code>venues.Academic</code> venue.</p>
<h2>Universe</h2>{universe}
<h2>Outcome</h2>{comparison}
<h2>Cost drag attributable to the KRX profile</h2><pre>{drag}</pre>
<p>Academic charges nothing and trades fractional quantity. The KRX-shaped profile charges 3bp
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

    project = vqapr.open(PROJECT)
    project.register(
        DatasetDeclaration(
            dataset_id="price_daily",
            path=observation_path,
            hive_partitioned=False,
            instrument_field="instrument",
            available_at_field="available_at",
            key_fields=("available_at", "instrument"),
            fields={"close": "close", "is_supervised": "is_supervised"},
        )
    )

    resolver = project.resolver(instruments=universe)
    evaluation_times = tuple(
        datetime.fromisoformat(f"{day.isoformat()}T16:00:00{OFFSET}") for day in score_days
    )
    project.materialize(
        model=models.MomentumModel,
        config={},
        evaluation_times=evaluation_times,
        resolver=resolver,
        output_dataset_id="momentum_score__derived",
    )
    _register_momentum_score(project)

    academic_exchange = Academic(
        listings=tuple(
            Listing(instrument_id=instrument, access=ListingAccess.SIGNED)
            for instrument in universe
        ),
        quantity_step=Decimal("0.00000001"),
        price_step=Decimal("0.01"),
        costs=(),
        # Declared rather than approximated by a tiny step: an academic venue trades
        # unquantized, which is what the legacy hand-written exchange expressed.
        fractional_allowed=True,
    )
    krx_shaped_exchange = Academic(
        listings=tuple(
            Listing(instrument_id=instrument, access=ListingAccess.LONG_ONLY)
            for instrument in universe
        ),
        quantity_step=Decimal("1"),
        price_step=Decimal("0.01"),
        costs=(
            VenueCost(
                side="buy", commission_rate=KRX_COMMISSION_RATE, tax_rate=Decimal("0")
            ),
            VenueCost(
                side="sell", commission_rate=KRX_COMMISSION_RATE, tax_rate=KRX_SALE_TAX_RATE
            ),
        ),
    )

    academic_simulation = _simulation(
        universe=universe, execution_path=execution_path, exchange=academic_exchange,
        callback_days=callback_days,
    )
    krx_simulation = _simulation(
        universe=universe, execution_path=execution_path, exchange=krx_shaped_exchange,
        callback_days=callback_days,
    )

    academic = _profile_outcome(
        project.run_completed(
            definition=academic_simulation, strategy=models.MomentumLongOnly, run_id="academic"
        )
    )
    krx = _profile_outcome(
        project.run_completed(
            definition=krx_simulation, strategy=models.MomentumLongOnly, run_id="krx"
        )
    )

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
                "The two runs share one frozen strategy, dataset and execution input. The NAV "
                "gap therefore combines the declared KRX cost with the whole-share rounding "
                "residual; it is not a separate signal."
            ),
        },
        "academic": {k: str(v) for k, v in academic.items()},
        "krx": {k: str(v) for k, v in krx.items()},
        "exchange_surface_note": (
            "No venues.Krx exists on the supported surface; Simulation.exchange is strictly "
            "venues.Academic. The KRX economics measured here (whole shares, 3bp commission "
            "both sides, 20bp sale tax on sells, long only) are reproduced on Academic's own "
            "fields, which is exact for this fixture (stocks only, no price limit exercised) "
            "but is a documented substitution, not the real KrxExchange engine class."
        ),
    }

    (OUTPUTS / "trace.json").write_text(
        json.dumps(trace, indent=2, default=str, ensure_ascii=False), encoding="utf-8"
    )
    (OUTPUTS / "report.html").write_text(_report(trace), encoding="utf-8")
    print(OUTPUTS / "report.html")


if __name__ == "__main__":
    main()
