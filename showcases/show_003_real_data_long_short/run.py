"""End-to-end evidence on real KRX warehouse data.

Chain proved here, using only ``vqapr.public``::

    data/DW CSV -> parquet slice -> register_dataset / register_execution_input
      -> DataModel -> materialize reversal_score (derived dataset)
      -> StrategyModel reads the derived dataset -> signed long/short intent
      -> AcademicExchange fills -> Account commit -> mark -> monitoring -> finalize

Nothing is mocked. Prices, trading days and tradability come from the local warehouse.

Reproduce::

    uv run python showcases/show_003_real_data_long_short/run.py
"""

from __future__ import annotations

import html
import json
import shutil
import sys
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
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
    Rebalance,
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
VERIFIED_AGAINST = "vqapr-0.1.0+show-003-working-tree"
LAST_VERIFIED_AT = "2026-08-17"

SPEC = FixtureSpec(asof="20260331", start="20260401", end="20260529", universe_size=6)


def _reset_outputs() -> None:
    if OUTPUTS.exists():
        shutil.rmtree(OUTPUTS)
    OUTPUTS.mkdir(parents=True)


def _sessions(observation_path: Path) -> list[date]:
    con = duckdb.connect()
    try:
        rows = con.execute(
            f"""
            SELECT DISTINCT CAST(available_at AT TIME ZONE '{VENUE}' AS DATE) AS session
            FROM read_parquet('{observation_path.as_posix()}')
            ORDER BY session
            """
        ).fetchall()
    finally:
        con.close()
    return [row[0] for row in rows]


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
        provenance="show_003 real KRX trading sessions",
    )


def _write_components() -> dict[str, Path]:
    components = PROJECT / "components"
    components.mkdir(parents=True, exist_ok=True)

    model = components / "model.py"
    model.write_text(
        '''from __future__ import annotations

from vqapr.public import DataModel, DataRequirement, Rebalance, RowsLookback

LOOKBACK = 6


class ReversalModel(DataModel):
    """Cross-sectionally demeaned 5-session reversal on real closes."""

    def requirements(self):
        return (
            DataRequirement.of('price_daily', 'close', lookback=RowsLookback(LOOKBACK)),
        )

    def compute(self, context):
        observations = context.window.observations(self.requirements()[0]).rows
        closes: dict[str, list[float]] = {}
        for row in observations:
            if row["close"] is not None:
                closes.setdefault(str(row["instrument"]), []).append(float(row["close"]))
        raw = {
            instrument: -(values[-1] / values[0] - 1.0)
            for instrument, values in closes.items()
            if len(values) == LOOKBACK and values[0] > 0.0
        }
        if not raw:
            return ()
        mean = sum(raw.values()) / len(raw)
        return tuple(
            {"instrument": instrument, "score": value - mean}
            for instrument, value in sorted(raw.items())
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
    Hold,
    IntentSourceRef,
    PortfolioDirection,
    Rebalance,
    RowsLookback,
    StrategyModel,
)

SIDE_WEIGHT = Decimal("0.25")
BUDGET = Budget(
    PortfolioDirection.SIGNED,
    Decimal("0"),
    Decimal("1"),
    Decimal("-1"),
    Decimal("1"),
)


class ReversalLongShort(StrategyModel):
    """Dollar-neutral top/bottom-2 book rebuilt from the derived reversal score."""

    def requirements(self):
        return (
            DataRequirement.of('reversal_score', 'score', lookback=RowsLookback(1)),
        )

    def on_occurrence(self, context):
        batch = context.window.observations(self.requirements()[0])
        latest = {
            str(row["instrument"]): float(row["score"])
            for row in batch.rows
            if row["score"] is not None
        }
        if len(latest) < 4:
            return Hold(reason="cross-section is too small to build both sides")

        ranked = sorted(latest.items(), key=lambda item: (item[1], item[0]))
        book = {instrument: -SIDE_WEIGHT for instrument, _ in ranked[:2]}
        book.update({instrument: SIDE_WEIGHT for instrument, _ in ranked[-2:]})
        weights = {
            instrument: book.get(instrument, Decimal("0")) for instrument in sorted(latest)
        }

        history = dict(self.memory or {})
        history["rebalances"] = int(history.get("rebalances", 0)) + 1
        history["last_occurrence"] = context.occurrence.occurrence_id
        self.memory = history

        return Rebalance(
            target_weights=weights,
            cash_weight=Decimal("1"),
            budget=BUDGET,
        )
''',
        encoding="utf-8",
    )

    exchange = components / "exchange.py"
    exchange.write_text(
        '''from __future__ import annotations

from decimal import Decimal

from vqapr.public import AcademicExchange, ListingAccess, Rebalance, TradeRule

UNIVERSE = __UNIVERSE__


class ShowcaseExchange(AcademicExchange):
    """Academic listings: fractional signed quantity, zero cost, full fill."""

    def __init__(self):
        listings = {
            instrument: TradeRule(
                instrument,
                Decimal("0.0001"),
                Decimal("0.0001"),
                True,
                ListingAccess.SIGNED,
            )
            for instrument in UNIVERSE
        }
        super().__init__(listings, "showcase-academic")
''',
        encoding="utf-8",
    )

    constraint = components / "constraint.py"
    constraint.write_text(
        '''from __future__ import annotations

from decimal import Decimal

from vqapr.public import Constraint, ConstraintBounds, ConstraintFinding, Rebalance

CAP = Decimal("0.30")


class SingleNameCap(Constraint):
    """One shared absolute single-name cap for projection, intent and monitoring."""

    @property
    def constraint_id(self):
        return "showcase-constraint"

    def inputs(self):
        return {}

    def project(self, call):
        return ConstraintBounds(
            lower_weights={instrument: -CAP for instrument in call.instruments},
            upper_weights={instrument: CAP for instrument in call.instruments},
        )

    def monitor(self, call, account, bounds):
        # `account.weights()` is each name's marked value over NAV, and NAV is cash plus the
        # marked total. The arithmetic used to be written out here from a MarkBatch; doing it in
        # one place is what keeps every rule measuring the same book the same way.
        weights = account.weights() if account.nav else {}
        measured = max((abs(w) for w in weights.values()), default=Decimal("0"))
        excess = measured - CAP if measured > CAP else Decimal("0")
        offenders = tuple(sorted(n for n, w in weights.items() if abs(w) > CAP))
        return ConstraintFinding(
            passed=not offenders,
            measured=measured,
            bound=CAP,
            excess=excess,
            details={"marked": len(weights)},
            offenders=offenders,
        )
''',
        encoding="utf-8",
    )
    return {"model": model, "strategy": strategy, "exchange": exchange, "constraint": constraint}


def _json_value(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: _json_value(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, (Decimal, datetime, date, time, Path)):
        return str(value)
    if hasattr(value, "__dict__") and not isinstance(value, (str, int, float, bool)):
        return {
            key: _json_value(item) for key, item in vars(value).items() if not key.startswith("_")
        }
    return value


def _table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "<p>No rows.</p>"
    columns = list(rows[0])
    head = "".join(f"<th>{html.escape(str(key))}</th>" for key in columns)
    body = "".join(
        "<tr>" + "".join(f"<td>{html.escape(str(row[key]))}</td>" for key in columns) + "</tr>"
        for row in rows
    )
    return f"<table><tr>{head}</tr>{body}</table>"


def _report(trace: dict[str, Any]) -> str:
    universe = _table(trace["universe"])
    scores = _table(trace["score_sample"])
    fills = _table(trace["fill_sample"])
    lifecycle = _table(trace["lifecycle_counts"])
    account = html.escape(
        json.dumps(trace["final_account"], indent=2, ensure_ascii=False, default=str)
    )
    summary = html.escape(json.dumps(trace["summary"], indent=2, ensure_ascii=False, default=str))
    return f"""<!doctype html><meta charset="utf-8"><title>vqapr real-data long/short</title>
<style>
body{{font-family:system-ui;max-width:1200px;margin:2rem auto;line-height:1.5}}
pre,table{{border:1px solid #ccc;padding:1rem;overflow:auto}}
td,th{{padding:.35rem .6rem;border:1px solid #ddd;text-align:right}}
td:first-child,th:first-child{{text-align:left}}
</style>
<h1>Real KRX data → DataModel → Strategy → Academic long/short</h1>
<p>Every price, trading day and tradability flag below comes from the local
<code>data/DW</code> warehouse. No fixture value is invented.</p>
<h2>Run summary</h2><pre>{summary}</pre>
<h2>Universe (KOSPI 200 weights at membership date)</h2>{universe}
<h2>Derived reversal_score (materialized dataset sample)</h2>{scores}
<h2>Executed fills (sample)</h2>{fills}
<h2>Lifecycle transitions</h2>{lifecycle}
<h2>Final account</h2><pre>{account}</pre>
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
    universe = [str(row["ticker"]) for row in fixture["universe"]]
    sessions = _sessions(observation_path)

    score_days = sessions[5:-1]
    callback_days = sessions[6:]
    if len(callback_days) < 5:
        raise AssertionError("real slice is too short to demonstrate a rebalancing book")

    register_dataset(
        PROJECT,
        DatasetRegistration.of(
            "price_daily",
            "krx-observation",
            instrument_field="instrument",
            available_at="available_at",
            key_fields=("available_at", "instrument"),
            fields={"close": "close", "volume": "volume"},
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

    paths = _write_components()
    paths["exchange"].write_text(
        paths["exchange"]
        .read_text(encoding="utf-8")
        .replace("__UNIVERSE__", repr(tuple(universe))),
        encoding="utf-8",
    )

    register_data_model(PROJECT, "showcase-model", paths["model"], "ReversalModel")
    materialization = materialize(
        PROJECT,
        "showcase-model",
        MaterializationSpec.of("reversal_score", value_fields=("score",)),
        evaluation_times=tuple(
            datetime.fromisoformat(f"{day.isoformat()}T16:00:00{OFFSET}") for day in score_days
        ),
        instruments=tuple(universe),
    )

    strategy_ref = component_ref(
        "showcase-strategy", ComponentKind.STRATEGY_MODEL, paths["strategy"], "ReversalLongShort"
    )
    exchange_ref = component_ref(
        "showcase-exchange", ComponentKind.EXCHANGE, paths["exchange"], "ShowcaseExchange"
    )
    constraint_ref = component_ref(
        "showcase-constraint", ComponentKind.CONSTRAINT, paths["constraint"], "SingleNameCap"
    )
    for reference in (strategy_ref, exchange_ref, constraint_ref):
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
        exchange_ref,
        "krx-daily",
        datetime.fromisoformat(f"{callback_days[0].isoformat()}T00:00:00{OFFSET}"),
        datetime.fromisoformat(f"{callback_days[-1].isoformat()}T23:00:00{OFFSET}"),
        AccountSnapshot(0, Decimal("1000000000"), {}),
        AccountMode.SIGNED,
        instruments=tuple(universe),
    )

    frozen = preflight_run(PROJECT, definition)
    result = run(PROJECT, frozen)

    final_state = result.final_state
    account = final_state.account
    lifecycle: dict[str, int] = {}
    for entry in final_state.lifecycle_trace:
        lifecycle[entry.kind.value] = lifecycle.get(entry.kind.value, 0) + 1

    dealt: list[dict[str, Any]] = []
    for row in _recorded_fills(result):
        if Decimal(row["dealt_quantity"]) == 0:
            continue
        dealt.append(
            {
                "account_version": int(row["account_version"]),
                "instrument": str(row["instrument"]),
                "dealt_quantity": str(Decimal(row["dealt_quantity"])),
                "price": str(Decimal(row["price"])),
                "side": "BUY" if Decimal(row["dealt_quantity"]) > 0 else "SELL",
            }
        )

    con = duckdb.connect()
    try:
        score_rows = con.execute(
            f"""
            SELECT available_at, instrument, score
            FROM read_parquet('{materialization.output_path.as_posix()}')
            ORDER BY available_at, instrument
            LIMIT 12
            """
        ).fetchall()
    finally:
        con.close()

    marked = account.latest_mark
    nav = None if marked is None else marked.nav

    # Independent replay of Account arithmetic from the published fill journal alone.
    replay_cash = Decimal("1000000000")
    replay_positions: dict[str, Decimal] = {}
    for row in _recorded_fills(result):
        if Decimal(row["dealt_quantity"]) == 0:
            continue
        replay_cash -= Decimal(row["dealt_quantity"]) * Decimal(row["price"])
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
    replay_nav = replay_cash + sum((mark.value for mark in marked.marks.marks), Decimal("0"))
    if marked is not None and replay_nav != marked.nav:
        raise AssertionError(f"NAV replay {replay_nav} != published {marked.nav}")
    long_names = sorted(i for i, q in account.snapshot.positions.items() if q > 0)
    short_names = sorted(i for i, q in account.snapshot.positions.items() if q < 0)

    trace = {
        "status": "current",
        "verified_against": VERIFIED_AGAINST,
        "last_verified_at": LAST_VERIFIED_AT,
        "fixture": fixture,
        "summary": {
            "warehouse_rows": fixture["rows"],
            "trading_sessions": fixture["sessions"],
            "first_session": fixture["first_session"],
            "last_session": fixture["last_session"],
            "materialized_score_rows": sum(
                invocation.row_count for invocation in materialization.invocations
            ),
            "materialized_evaluations": len(materialization.invocations),
            "strategy_callbacks": len(callback_days),
            "occurrences_dispatched": len(result.occurrences),
            "dealt_fills": len(dealt),
            "final_nav": None if nav is None else str(nav),
            "final_cash": str(account.snapshot.cash),
            "long_positions": long_names,
            "short_positions": short_names,
            "account_version": account.snapshot.version,
            "independent_replay": {
                "cash_matches_committed": True,
                "positions_match_committed": True,
                "nav_matches_published": True,
                "replayed_nav": str(replay_nav),
            },
            "pending_after_finalize": final_state.pending_accepted_intent,
            "frozen_run_identity": frozen.identity,
        },
        "universe": [
            {
                "ticker": row["ticker"],
                "name": row["name"],
                "index_weight": row["index_weight"],
            }
            for row in fixture["universe"]
        ],
        "score_sample": [
            {"available_at": str(r[0]), "instrument": r[1], "score": str(r[2])} for r in score_rows
        ],
        "fill_sample": dealt[:12],
        "lifecycle_counts": [
            {"transition": key, "count": value} for key, value in sorted(lifecycle.items())
        ],
        "final_account": _json_value(account.snapshot),
    }

    (OUTPUTS / "trace.json").write_text(
        json.dumps(trace, indent=2, default=str, ensure_ascii=False), encoding="utf-8"
    )
    (OUTPUTS / "report.html").write_text(_report(trace), encoding="utf-8")
    print(OUTPUTS / "report.html")


if __name__ == "__main__":
    main()
