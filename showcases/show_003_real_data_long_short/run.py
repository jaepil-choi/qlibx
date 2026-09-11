"""End-to-end evidence on real KRX warehouse data.

Chain proved here, using only ``vqapr.public``::

    data/DW CSV -> parquet slice -> register_dataset (observations and the venue table)
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
from pydantic import BaseModel

from vqapr.public import (
    AccountMode,
    AccountSnapshot,
    DataModelEntry,
    DatasetRegistration,
    RunSchedule,
    RunDefinition,
    RunExecution,
    RunFill,
    SourceSpec,
    StrategyEntry,
    preflight_run,
    register_compliance,
    register_data_model,
    register_dataset,
    register_exchange,
    register_instruments,
    register_strategy_model,
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
VERIFIED_AGAINST = "vqapr-0.15.0"
LAST_VERIFIED_AT = "2026-09-10"

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


def _write_components() -> dict[str, Path]:
    components = PROJECT / "components"
    components.mkdir(parents=True, exist_ok=True)

    model = components / "model.py"
    model.write_text(
        '''from __future__ import annotations

from vqapr import authoring as va

LOOKBACK = 6


class ReversalModel(va.DataModel):
    """Cross-sectionally demeaned 5-session reversal on real closes."""

    def inputs(self):
        return {
            "prices": va.DatasetInput(
                dataset_id="price_daily", fields=("close",), lookback=va.RowsLookback(rows=LOOKBACK)
            )
        }

    def compute(self, context):
        window = context.read("prices", "close")
        closes = {
            name: [float(v) for v in window.values[name] if v is not None]
            for name in window.instruments
        }
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

    def decide(self, context):
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
        history["last_event"] = context.event.event_id
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

    compliance = components / "compliance.py"
    compliance.write_text(
        '''from __future__ import annotations

from decimal import Decimal

from vqapr.public import Compliance, ComplianceFinding

CAP = Decimal("0.30")


class SingleNameCap(Compliance):
    """An absolute single-name cap, observed on the marked book at every market-clock instant."""

    @property
    def compliance_id(self):
        return "showcase-cap"

    def inputs(self):
        return {}

    def observe(self, call):
        # `call.account.weights()` is each name's marked value over NAV, and NAV is cash plus the
        # marked total. The arithmetic used to be written out here from a MarkBatch; doing it in
        # one place is what keeps every rule measuring the same book the same way.
        weights = call.account.weights() if call.account.nav else {}
        measured = max((abs(w) for w in weights.values()), default=Decimal("0"))
        excess = measured - CAP if measured > CAP else Decimal("0")
        offenders = tuple(sorted(n for n, w in weights.items() if abs(w) > CAP))
        return ComplianceFinding(
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
    return {"model": model, "strategy": strategy, "exchange": exchange, "compliance": compliance}


def _json_value(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: _json_value(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, BaseModel):
        return {name: _json_value(getattr(value, name)) for name in type(value).model_fields}
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
            grain="instrument_instant",
            key_fields=("available_at", "instrument"),
            # The extracted slice stores close as DECIMAL(18, 4), which no field may be declared
            # as (issue 088): cast to DOUBLE here; the model already reads it as float. Volume is
            # a BIGINT in the same slice.
            fields={"close": "CAST(close AS DOUBLE)", "volume": "volume"},
            field_types={"close": "DOUBLE", "volume": "INTEGER"},
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

    paths = _write_components()
    paths["exchange"].write_text(
        paths["exchange"]
        .read_text(encoding="utf-8")
        .replace("__UNIVERSE__", repr(tuple(universe))),
        encoding="utf-8",
    )

    register_data_model(PROJECT, "showcase-model", paths["model"], "ReversalModel")
    # The score is a datamodel RUN (record 148): the same sessions/wall-time shape as the
    # strategy run below, no venue and no account, one registered dataset at the end.
    score_definition = RunDefinition(
        run_id="showcase-score",
        instruments=tuple(universe),
        datamodel=DataModelEntry("showcase-model", ("score",)),
        timezone=VENUE,
        schedule=RunSchedule(every="1d", at=(time(16, 0),), days_from="price_daily"),
        start=datetime.fromisoformat(f"{score_days[0].isoformat()}T00:00:00{OFFSET}"),
        end=datetime.fromisoformat(f"{score_days[-1].isoformat()}T23:00:00{OFFSET}"),
        writes="reversal_score",
    )
    materialization = run(
        PROJECT, preflight_run(PROJECT, score_definition), store_root=PROJECT / ".vqapr"
    ).result()

    register_strategy_model(PROJECT, "showcase-strategy", paths["strategy"], "ReversalLongShort")
    # What each id IS, declared by the project before anything orders it (design §6.2). The
    # universe is index constituents, so every name is a share.
    register_instruments(PROJECT, {name: "stock" for name in universe})
    register_exchange(PROJECT, "showcase-exchange", paths["exchange"], "ShowcaseExchange")
    register_compliance(PROJECT, "showcase-cap", paths["compliance"], "SingleNameCap")


    definition = RunDefinition(
        run_id="show003",
        strategy=StrategyEntry("showcase-strategy"),
        compliance=("showcase-cap",),
        timezone=VENUE,
        schedule=RunSchedule(every="1d", at=(time(8, 30),)),
        exchange="showcase-exchange",
        execution=RunExecution(
            dataset="krx-daily",
            trade_price="close",
            fill=RunFill(at=time(15, 30)),
        ),
        start=datetime.fromisoformat(f"{callback_days[0].isoformat()}T00:00:00{OFFSET}"),
        end=datetime.fromisoformat(f"{callback_days[-1].isoformat()}T23:00:00{OFFSET}"),
        initial_account_snapshot=AccountSnapshot(0, Decimal("1000000000"), {}),
        initial_account_mode=AccountMode.SIGNED,
        instruments=tuple(universe),
        writes="show003-weights",
    )

    frozen = preflight_run(PROJECT, definition)
    result = run(PROJECT, frozen).result()

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
            FROM read_parquet('{materialization.output_path.as_posix()}/*.parquet')
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
            "materialized_score_rows": materialization.rows,
            "materialized_evaluations": len(materialization.events),
            "strategy_callbacks": len(callback_days),
            "events_dispatched": len(result.events),
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
