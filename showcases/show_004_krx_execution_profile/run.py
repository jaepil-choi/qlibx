"""The same real signal executed through two profiles.

One frozen strategy, one real KRX price history, two execution profiles::

    Academic   fractional quantity, zero cost, full fill
    KRX        whole shares, 3bp commission both sides, 20bp sale tax on sells, long only

The two runs differ **only** by the registered Exchange component. Everything downstream — the
derived score, the callback agenda, the execution input, the account authority — is identical, so
the difference in outcome is exactly the declared venue friction.

Reproduce::

    uv run python showcases/show_004_krx_execution_profile/run.py
"""

from __future__ import annotations

import html
import json
import shutil
import sys
from collections.abc import Mapping
from dataclasses import replace
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb

from vqapr.public import (
    AccountMode,
    AccountSnapshot,
    ComponentKind,
    ConstraintSet,
    DatasetRegistration,
    ExecutionInputRegistration,
    ExecutionTableSpec,
    FillConvention,
    FillSelector,
    LocalInstantDeclaration,
    MaterializationSpec,
    MonitoringPolicy,
    OperationAgenda,
    OperationOccurrence,
    OperationRole,
    RunDefinition,
    SourceSpec,
    StrategyConfig,
    ValuationConfig,
    component_ref,
    materialize,
    preflight_run,
    register_agenda,
    register_component,
    register_data_model,
    register_dataset,
    register_execution_input,
    register_monitoring_policy,
    register_strategy_config,
    register_valuation_config,
    run,
)

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
LAST_VERIFIED_AT = "2026-08-17"

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


def _agenda(agenda_id: str, role: OperationRole, at: time, days: list[date]) -> OperationAgenda:
    return OperationAgenda.from_occurrences(
        agenda_id=agenda_id,
        role=role,
        timezone=VENUE,
        occurrences=tuple(
            OperationOccurrence(
                f"{agenda_id}-{day.isoformat()}",
                role,
                LocalInstantDeclaration(day, at, VENUE, 0, OFFSET),
            )
            for day in days
        ),
        provenance="show_004 real KRX trading sessions",
    )


def _write_components(universe: tuple[str, ...]) -> dict[str, Path]:
    components = PROJECT / "components"
    components.mkdir(parents=True, exist_ok=True)

    model = components / "model.py"
    model.write_text(
        '''from __future__ import annotations

from vqapr.public import DataModel, DataRequirement, RowsLookback

LOOKBACK = 6


class MomentumModel(DataModel):
    """5-session momentum on real closes, skipping supervised names."""

    def requirements(self):
        return (
            DataRequirement.of(
                "showcase-model",
                "price_daily",
                fields=("close", "is_supervised"),
                lookback=RowsLookback(LOOKBACK),
            ),
        )

    def compute(self, context):
        observations = context.window.observations(self.requirements()[0]).rows
        closes: dict[str, list[float]] = {}
        supervised: dict[str, bool] = {}
        for row in observations:
            instrument = str(row["instrument"])
            if row["close"] is not None:
                closes.setdefault(instrument, []).append(float(row["close"]))
            supervised[instrument] = bool(row["is_supervised"])
        return tuple(
            {
                "instrument": instrument,
                "score": values[-1] / values[0] - 1.0,
                "eligible": not supervised.get(instrument, False),
            }
            for instrument, values in sorted(closes.items())
            if len(values) == LOOKBACK and values[0] > 0.0
        )
''',
        encoding="utf-8",
    )

    strategy = components / "strategy.py"
    strategy.write_text(
        '''from __future__ import annotations

from decimal import Decimal
from uuid import NAMESPACE_URL, uuid5

from vqapr.public import (
    Budget,
    DataRequirement,
    EconomicPortfolioIntent,
    IntentSourceRef,
    NoDecision,
    PortfolioDirection,
    PortfolioTarget,
    RowsLookback,
    StrategyModel,
)

BOOK = 2
INVESTED = Decimal("0.98")
CASH_TARGET = Decimal("1") - INVESTED
BUDGET = Budget(
    PortfolioDirection.LONG_ONLY,
    Decimal("0"),
    Decimal("1"),
    Decimal("0"),
    Decimal("1"),
)


class MomentumLongOnly(StrategyModel):
    """Equal-weight top-2 momentum book, long only so both profiles can execute it."""

    def requirements(self):
        return (
            DataRequirement.of(
                "showcase-strategy",
                "momentum_score",
                fields=("score", "eligible"),
                lookback=RowsLookback(1),
            ),
        )

    def on_occurrence(self, context):
        batch = context.window.observations(self.requirements()[0])
        latest = {
            str(row["instrument"]): float(row["score"])
            for row in batch.rows
            if row["score"] is not None and bool(row["eligible"])
        }
        if len(latest) < BOOK:
            return NoDecision("not enough eligible names to fill the book")

        ranked = sorted(latest.items(), key=lambda item: (-item[1], item[0]))
        chosen = {instrument for instrument, _ in ranked[:BOOK]}
        weight = INVESTED / Decimal(BOOK)
        targets = tuple(
            PortfolioTarget(
                instrument, weight=weight if instrument in chosen else Decimal("0")
            )
            for instrument in sorted(latest)
        )

        source_refs = []
        seen = set()
        for access in context.window.accesses:
            if access.source_id in seen:
                continue
            seen.add(access.source_id)
            source_refs.append(IntentSourceRef(access.source_id, access.source_digest))

        history = dict(self.memory or {})
        history["rebalances"] = int(history.get("rebalances", 0)) + 1
        self.memory = history

        return EconomicPortfolioIntent(
            uuid5(NAMESPACE_URL, f"show004/{context.occurrence.occurrence_id}"),
            "showcase-strategy",
            targets,
            CASH_TARGET,
            BUDGET,
            tuple(source_refs),
            context.account.version,
            None,
        )
''',
        encoding="utf-8",
    )

    academic = components / "academic_exchange.py"
    academic.write_text(
        f'''from __future__ import annotations

from decimal import Decimal

from vqapr.public import AcademicExchange, ListingAccess, TradeRule

UNIVERSE = {universe!r}


class ShowcaseAcademicExchange(AcademicExchange):
    """Fractional quantity, zero cost, full fill."""

    def __init__(self):
        super().__init__(
            {{
                instrument: TradeRule(
                    instrument,
                    Decimal("0.0001"),
                    Decimal("0.0001"),
                    True,
                    ListingAccess.SIGNED,
                )
                for instrument in UNIVERSE
            }},
            "showcase-academic",
        )
''',
        encoding="utf-8",
    )

    krx = components / "krx_exchange.py"
    krx.write_text(
        f'''from __future__ import annotations

from vqapr.public import KrxExchange

UNIVERSE = {universe!r}


class ShowcaseKrxExchange(KrxExchange):
    """Whole shares, 3bp commission on both sides, 20bp sale tax, long only."""

    def __init__(self):
        super().__init__(UNIVERSE, "showcase-krx")
''',
        encoding="utf-8",
    )

    constraint = components / "constraint.py"
    constraint.write_text(
        """from __future__ import annotations

from decimal import Decimal

from vqapr.public import Constraint, ConstraintBounds, ConstraintFinding

CAP = Decimal("0.75")


class SingleNameCap(Constraint):
    def __init__(self, constraint_id="showcase-constraint"):
        self._constraint_id = constraint_id

    @property
    def constraint_id(self):
        return self._constraint_id

    def requirements(self):
        return ()

    def project(self, window, instruments):
        return ConstraintBounds(
            {instrument: Decimal("0") for instrument in instruments},
            {instrument: CAP for instrument in instruments},
        )

    def validate_intended(self, intent, bounds):
        measured = max(
            (abs(t.weight) for t in intent.targets if t.weight is not None),
            default=Decimal("0"),
        )
        return ConstraintFinding(
            self.constraint_id, measured <= CAP, measured, CAP, Decimal("0"), {}
        )

    def evaluate(self, window, account, marks, bounds):
        nav = marks.total_value + account.cash
        measured = Decimal("0")
        if nav > 0:
            measured = max((abs(m.value) / nav for m in marks.marks), default=Decimal("0"))
        return ConstraintFinding(
            self.constraint_id, measured <= CAP, measured, CAP, Decimal("0"), {}
        )
""",
        encoding="utf-8",
    )
    return {
        "model": model,
        "strategy": strategy,
        "academic": academic,
        "krx": krx,
        "constraint": constraint,
    }


def _profile_outcome(result: Any) -> dict[str, Any]:
    account = result.final_state.account
    marked = account.latest_mark
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
    if replay_cash != account.snapshot.cash:
        raise AssertionError(f"cash replay {replay_cash} != committed {account.snapshot.cash}")
    if replay_positions != dict(account.snapshot.positions):
        raise AssertionError("position replay does not match the committed Account")

    whole_shares = all(
        quantity == quantity.to_integral_value() for quantity in account.snapshot.positions.values()
    )
    return {
        "final_nav": None if marked is None else marked.nav,
        "final_cash": account.snapshot.cash,
        "positions": {k: str(v) for k, v in sorted(account.snapshot.positions.items())},
        "dealt_fills": dealt,
        "traded_notional": traded_notional,
        "commission": commission,
        "tax": tax,
        "total_cost": commission + tax,
        "account_version": account.snapshot.version,
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
differ only by the registered Exchange component.</p>
<h2>Universe</h2>{universe}
<h2>Outcome</h2>{comparison}
<h2>Cost drag attributable to the KRX profile</h2><pre>{drag}</pre>
<p>Academic charges nothing and trades fractional quantity. KRX charges 3bp commission on both
sides, 20bp sale tax on sells, trades whole shares only and refuses short positions. Neither
profile models price ticks, price limits, queue position, liquidity or borrow.</p>
<p>Verified against {VERIFIED_AGAINST}; last verified {LAST_VERIFIED_AT}.</p>"""


def _recorded_fills(result: Any) -> list[dict[str, Any]]:
    """Every committed fill, from the run's own published record.

    The Account no longer carries the whole journal -- it is published to ``vqapr.fill`` and
    dropped -- so replaying its arithmetic reads the record. Rows arrive in commit order, which is
    the order the Account applied them.
    """
    return [dict(row) for row in result.final_state.recorder_rows.get("vqapr.fill", ())]


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
            key_fields=("available_at", "instrument"),
            fields={"close": "close", "is_supervised": "is_supervised"},
        ),
        SourceSpec.of("krx-observation", observation_path),
    )
    register_execution_input(
        PROJECT,
        ExecutionInputRegistration.of(
            "krx-daily",
            ExecutionTableSpec(
                source=SourceSpec.of("krx-execution", execution_path),
                trade_at_field="trade_at",
                instrument_field="instrument",
                is_tradable_field="is_tradable",
                price_fields={"close": "close"},
            ),
            FillConvention(FillSelector.SAME_DAY, time(15, 30), VENUE, "close"),
        ),
    )

    paths = _write_components(universe)
    register_data_model(PROJECT, "showcase-model", paths["model"], "MomentumModel")
    materialize(
        PROJECT,
        "showcase-model",
        MaterializationSpec.of("momentum_score", value_fields=("score", "eligible")),
        evaluation_times=tuple(
            datetime.fromisoformat(f"{day.isoformat()}T16:00:00{OFFSET}") for day in score_days
        ),
        instruments=universe,
    )

    strategy_ref = component_ref(
        "showcase-strategy", ComponentKind.STRATEGY_MODEL, paths["strategy"], "MomentumLongOnly"
    )
    academic_ref = component_ref(
        "showcase-academic", ComponentKind.EXCHANGE, paths["academic"], "ShowcaseAcademicExchange"
    )
    krx_ref = component_ref(
        "showcase-krx", ComponentKind.EXCHANGE, paths["krx"], "ShowcaseKrxExchange"
    )
    constraint_ref = component_ref(
        "showcase-constraint", ComponentKind.CONSTRAINT, paths["constraint"], "SingleNameCap"
    )
    for reference in (strategy_ref, academic_ref, krx_ref, constraint_ref):
        register_component(PROJECT, reference)

    strategy_agenda = _agenda(
        "showcase-strategy", OperationRole.STRATEGY_CALLBACK, time(8, 30), callback_days
    )
    valuation_agenda = _agenda(
        "showcase-valuation", OperationRole.VALUATION, time(16, 0), callback_days
    )
    monitoring_agenda = _agenda(
        "showcase-monitoring", OperationRole.MONITORING, time(16, 30), callback_days
    )
    for agenda in (strategy_agenda, valuation_agenda, monitoring_agenda):
        register_agenda(PROJECT, agenda)

    strategy_config = StrategyConfig(
        strategy_ref, "showcase-strategy", OperationRole.STRATEGY_CALLBACK
    )
    valuation_config = ValuationConfig(
        "showcase-valuation",
        OperationRole.VALUATION,
    )
    monitoring = MonitoringPolicy("showcase-monitoring", OperationRole.MONITORING)
    register_strategy_config(PROJECT, strategy_config)
    register_valuation_config(PROJECT, valuation_config)
    register_monitoring_policy(PROJECT, monitoring)

    definition = RunDefinition(
        strategy_config,
        valuation_config,
        ConstraintSet((constraint_ref,)),
        monitoring,
        academic_ref,
        "krx-daily",
        datetime.fromisoformat(f"{callback_days[0].isoformat()}T00:00:00{OFFSET}"),
        datetime.fromisoformat(f"{callback_days[-1].isoformat()}T23:00:00{OFFSET}"),
        AccountSnapshot(0, INITIAL_CASH, {}),
        AccountMode.LONG_ONLY,
        instruments=universe,
    )

    academic_frozen = preflight_run(PROJECT, definition)
    krx_frozen = preflight_run(PROJECT, replace(definition, exchange=krx_ref))
    academic = _profile_outcome(run(PROJECT, academic_frozen))
    krx = _profile_outcome(run(PROJECT, krx_frozen))

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
                "The two runs share one frozen strategy, dataset, agenda set and execution input. "
                "The NAV gap therefore combines the declared KRX cost with the whole-share "
                "rounding residual; it is not a separate signal."
            ),
        },
        "academic": {k: str(v) for k, v in academic.items()},
        "krx": {k: str(v) for k, v in krx.items()},
    }

    (OUTPUTS / "trace.json").write_text(
        json.dumps(trace, indent=2, default=str, ensure_ascii=False), encoding="utf-8"
    )
    (OUTPUTS / "report.html").write_text(_report(trace), encoding="utf-8")
    print(OUTPUTS / "report.html")


if __name__ == "__main__":
    main()
