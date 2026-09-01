"""One price-derived signal, driven through a real ``run()``, from raw closes to a re-hydrated mark.

    price_daily (KRX, real)  -> RowsLookback(6) -> reversal view
                                                       |
                                                       v
                                              rank            (put it on a common scale)
                                                       |
                                                       v
                                              neutralize       (market column of ones)
                                                       |
                                                       v
                                              signal_weight -> rescale to a small gross budget
                                                       |
                                                       v
                                              EconomicPortfolioIntent -> Academic exchange (SIGNED)

Every occurrence that computes a signal records it — the value **before** weighting (the ranked
reversal view) and the value **after** neutralisation — on a declared recorder table. Nothing here
constructs that table by hand: the rows come from the real callback the Flow actually dispatched.

Two things get proved after the run, neither of them by construction:

* The recorded signal table and the package's own ``vqapr.account`` series are published with
  ``publish_run_record``, read back from the parquet the publication wrote (not from the run's own
  objects), and their row counts are checked against ``result.final_state.recorder_rows`` — the
  same round trip show_006 proves for an allocation, now proved for a diagnostic table.
* The account rows the publication produced are used to key into the run's own committed
  ``mark_history``; each ``Mark``/``MarkBatch`` is rebuilt from primitive ``Decimal(str(...))``
  values — the same string round trip every other table in this package stores decimals with — and
  the rebuilt value is asserted field-for-field equal to what the run actually committed. This is
  the seam the next milestone story's analysis functions depend on: a later reader has only rows,
  never the producing run's objects, and this is the proof that rows are enough.

The fill journal is replayed independently against the committed Account, and the whole pipeline
runs twice into separate projects so the reported outcome and the artifact digests can be compared.

Reproduce::

    uv run python showcases/show_007_signal_measurement/run.py
"""

from __future__ import annotations

import hashlib
import json
import shutil
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
    Mark,
    MarkBatch,
    MonitoringPolicy,
    OperationAgenda,
    OperationOccurrence,
    OperationRole,
    RunDefinition,
    RunRecordSpec,
    SourceSpec,
    StrategyConfig,
    ValuationConfig,
    callback_evidence,
    component_ref,
    preflight_run,
    publish_run_record,
    register_agenda,
    register_component,
    register_dataset,
    register_execution_input,
    register_monitoring_policy,
    register_strategy_config,
    register_valuation_config,
    run,
)

HERE = Path(__file__).resolve().parent
FIXTURE = HERE.parents[1] / "tests" / "fixtures" / "real"
OUTPUTS = HERE / "outputs"

VENUE = "Asia/Seoul"
OFFSET = "+09:00"
INITIAL_CASH = Decimal("1000000000")
LOOKBACK = 6
"""Six closes span a five-session reversal."""

ACTIVE_BUDGET = Decimal("0.02")
"""Total absolute active weight the signal is rescaled to after sizing."""

VERIFIED_AGAINST = "vqapr-0.1.0+show-007-working-tree"
LAST_VERIFIED_AT = "2026-08-18"


def _read_published(path: Path) -> list[dict[str, object]]:
    """Read a published dataset back with no reference to the run that produced it."""
    con = duckdb.connect()
    try:
        cursor = con.execute(
            f"SELECT * FROM read_parquet('{path.as_posix()}') ORDER BY available_at, instrument"
        )
        columns = [description[0] for description in cursor.description]
        return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
    finally:
        con.close()


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


def _universe(path: Path) -> tuple[str, ...]:
    con = duckdb.connect()
    try:
        return tuple(
            row[0]
            for row in con.execute(
                f"SELECT DISTINCT instrument FROM read_parquet('{path.as_posix()}') ORDER BY 1"
            ).fetchall()
        )
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
        provenance="show_007 committed KRX sessions",
    )


_SOURCE_REFS = '''

def _source_refs(context):
    """Exactly the sources this callback read, in first-read order.

    The Flow independently recomputes this from the window and refuses any intent whose provenance
    disagrees, so it must be derived from the accesses rather than declared.
    """
    from vqapr.public import IntentSourceRef

    seen = {}
    for access in context.window.accesses:
        seen.setdefault(access.source_id, access.source_digest)
    return tuple(IntentSourceRef(source, digest) for source, digest in seen.items())
'''


_SIGNAL_SOURCE = (
    '''"""A short-horizon reversal view: ranked, neutralised, sized, and rescaled to a fixed budget.

The signal before weighting (the ranked reversal) and the signal after neutralisation are both
recorded on every occurrence that computes one, so the record a later run reads back is exactly
what this callback saw -- never a value reconstructed after the fact.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import NAMESPACE_URL, uuid5

from vqapr.public import (
    Budget,
    DataRequirement,
    EconomicPortfolioIntent,
    Hold,
    PortfolioDirection,
    PortfolioTarget,
    RowsLookback,
    StrategyModel,
    TableSpec,
    neutralize,
    rank,
    rescale,
    signal_weight,
)

LOOKBACK = '''
    + str(LOOKBACK)
    + '''
ACTIVE_BUDGET = Decimal("'''
    + str(ACTIVE_BUDGET)
    + '''")

BUDGET = Budget(
    PortfolioDirection.SIGNED,
    Decimal("0"),
    Decimal("2"),
    Decimal("-1"),
    Decimal("1"),
)


class ReversalSignalStrategy(StrategyModel):
    """rank(reversal) -> neutralize against a market column of ones -> signal_weight -> rescale."""

    def tables(self):
        return (
            TableSpec(
                "signal.measurement",
                ("instrument", "signal_before_weighting", "neutralized_signal"),
            ),
        )

    def requirements(self):
        return (
            DataRequirement.of(
                "show007-signal", "price_daily", fields=("close",), lookback=RowsLookback(LOOKBACK)
            ),
        )

    def on_occurrence(self, context):
        rows = context.window.observations(self.requirements()[0]).rows
        closes: dict[str, list[Decimal]] = {}
        for row in rows:
            if row["close"] is not None:
                closes.setdefault(str(row["instrument"]), []).append(row["close"])
        eligible = {name: values for name, values in closes.items() if len(values) == LOOKBACK}
        if len(eligible) < 2:
            return Hold(reason="a cross-sectional signal needs at least two names with full history")

        raw = {
            name: -1 * (values[-1] / values[0] - Decimal(1)) for name, values in eligible.items()
        }
        scaled = rank(raw)
        market = dict.fromkeys(scaled, Decimal(1))
        neutralized = neutralize(scaled, exposures={"market": market})

        self.recorder.append_batch(
            "signal.measurement",
            tuple(
                {
                    "instrument": name,
                    "signal_before_weighting": str(scaled[name]),
                    "neutralized_signal": str(neutralized[name]),
                }
                for name in sorted(scaled)
            ),
        )

        if all(value == 0 for value in neutralized.values()):
            return Hold(reason="the neutralised signal is flat")

        sized = signal_weight(neutralized)
        weights = rescale(sized, long=ACTIVE_BUDGET, short=-ACTIVE_BUDGET)

        return EconomicPortfolioIntent(
            uuid5(NAMESPACE_URL, "show007/show007-signal/" + context.occurrence.occurrence_id),
            "show007-signal",
            tuple(PortfolioTarget(name, weight=w) for name, w in sorted(weights.items())),
            Decimal(1) - sum(weights.values()),
            BUDGET,
            _source_refs(context),
            context.account.version,
            None,
        )
'''
    + _SOURCE_REFS
)


def _write_components(project: Path, universe: tuple[str, ...]) -> dict[str, Path]:
    components = project / "components"
    components.mkdir(parents=True, exist_ok=True)

    signal = components / "signal_strategy.py"
    signal.write_text(_SIGNAL_SOURCE, encoding="utf-8")

    academic = components / "academic_exchange.py"
    academic.write_text(
        f'''"""Fractional quantity, zero cost, full fill -- the venue this run trades on."""

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
                    Decimal("0.0001"),
                    Decimal("0.0001"),
                    True,
                    ListingAccess.SIGNED,
                )
                for instrument in UNIVERSE
            }},
            "show007-academic",
        )
''',
        encoding="utf-8",
    )
    return {"signal": signal, "academic": academic}


def _replay(result: Any) -> dict[str, Any]:
    """Rebuild cash and positions from the fill journal and demand an exact match."""
    account = result.final_state.account
    cash = INITIAL_CASH
    positions: dict[str, Decimal] = {}
    commission = Decimal(0)
    tax = Decimal(0)
    dealt = 0
    for row in _recorded_fills(result):
        if Decimal(row["dealt_quantity"]) == 0:
            continue
        dealt += 1
        cash += Decimal(row["cash_delta"])
        commission += Decimal(row["commission"] or 0)
        tax += Decimal(row["tax"] or 0)
        held = positions.get(str(row["instrument"]), Decimal(0)) + Decimal(row["dealt_quantity"])
        if held == 0:
            positions.pop(str(row["instrument"]), None)
        else:
            positions[str(row["instrument"])] = held

    snapshot = account.snapshot
    if cash != snapshot.cash:
        raise AssertionError(f"journal replay cash {cash} != committed {snapshot.cash}")
    if positions != dict(snapshot.positions):
        raise AssertionError("journal replay positions do not match the committed Account")

    marked = account.latest_mark
    return {
        "dealt_fills": dealt,
        "replayed_cash": str(cash),
        "committed_cash": str(snapshot.cash),
        "replayed_positions": {name: str(q) for name, q in sorted(positions.items())},
        "commission": str(commission),
        "sale_tax": str(tax),
        "account_version": snapshot.version,
        "final_nav": None if marked is None else str(marked.nav),
        "any_short": any(quantity < 0 for quantity in snapshot.positions.values()),
    }


def _recorded_fills(result: Any) -> list[dict[str, Any]]:
    """Every committed fill, from the run's own published record.

    The Account no longer carries the whole journal -- it is published to ``vqapr.fill`` and
    dropped -- so replaying its arithmetic reads the record. Rows arrive in commit order, which is
    the order the Account applied them.
    """
    return [dict(row) for row in result.final_state.recorder_rows.get("vqapr.fill", ())]


def _digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _rehydrate_marks(result: Any, replayed_account: list[dict[str, object]]) -> dict[str, Any]:
    """Rebuild the run's valuation from its published table alone.

    A run retains only the marks some consumer declared it would read (canon 7.3), so memory is
    deliberately not the place a later reader reconstructs it from. The published
    ``vqapr.account`` table is, and that is the stronger claim: this rebuilds every mark from
    ``Decimal(str(...))`` primitives read back out of parquet, never from the producing run's own
    objects, and then checks the result against the one mark the account still holds.

    A callback's recorded row is a *pre-trade* snapshot -- what the Strategy saw before deciding --
    while a committed mark is *post-trade*. The two series are therefore offset by one commit, so
    the final trade's mark has no later callback to witness it and is legitimately absent.
    """
    account_rows = [row for row in replayed_account if row["instrument"] == "_ACCOUNT"]
    panel_rows = [row for row in replayed_account if row["instrument"] != "_ACCOUNT"]
    if not account_rows:
        raise AssertionError("the published account table carries no account-level rows")

    # Keyed by (version, event_time) rather than by version alone. The account version is no
    # longer unique per mark: a valuation occurrence measures the book on its own clock without
    # trading, so several marks legitimately share one version and are told apart only by the
    # occurrence that took them. Grouping by version alone re-collects every instrument once per
    # valuation and builds a batch holding the same name several times.
    rehydrated: dict[int, MarkBatch] = {}
    for row in account_rows:
        if row["nav"] is None:
            continue  # before the first commit there is nothing to value
        version = int(row["account_version"])
        event_time = row["event_time"]
        marks = tuple(
            Mark(
                str(panel["instrument"]),
                Decimal(str(panel["quantity"])),
                Decimal(str(panel["price"])),
                Decimal(str(panel["quantity"])) * Decimal(str(panel["price"])),
            )
            for panel in panel_rows
            if int(panel["account_version"]) == version
            and panel["event_time"] == event_time
            and panel["price"] is not None
        )
        if not marks:
            continue
        # The latest occurrence at a version wins, so the retained batch is the most recent
        # measurement of that book rather than the first one taken of it.
        rehydrated[version] = MarkBatch(marks, sum((mark.value for mark in marks), Decimal("0")))

    if not rehydrated:
        raise AssertionError(
            "no published account row carries a valuation; the rehydration seam is unproven"
        )

    # The falsifiable half: the account still holds its current mark, and the table must agree
    # with it wherever the two overlap. A rehydration that invented or dropped a holding fails
    # here rather than merely looking plausible.
    committed = result.final_state.account.latest_mark
    if committed is not None and committed.account_version in rehydrated:
        rebuilt = rehydrated[committed.account_version]
        if rebuilt != committed.marks:
            raise AssertionError(
                f"rehydrated MarkBatch at account_version={committed.account_version} "
                "differs from what the run actually committed"
            )

    return {
        "rehydrated_versions": sorted(rehydrated),
        "rehydrated_mark_count": sum(len(batch.marks) for batch in rehydrated.values()),
        "committed_mark_count": (0 if committed is None else len(committed.marks.marks)),
    }


def _pipeline(project: Path) -> tuple[dict[str, Any], dict[str, str]]:
    manifest = json.loads((FIXTURE / "fixture.json").read_text(encoding="utf-8"))
    observation_path = FIXTURE / str(manifest["observation_path"])
    execution_path = FIXTURE / str(manifest["execution_path"])
    benchmark_path = FIXTURE / str(manifest["benchmark_path"])
    universe = _universe(benchmark_path)
    sessions = _sessions(benchmark_path)
    # The first session is the lookback base; the run's own agenda declines occurrences until the
    # six-close reversal window fills, exactly as canon requires -- nothing here trims the agenda
    # to fit the signal.
    callback_days = sessions[1:]

    register_dataset(
        project,
        DatasetRegistration.of(
            "price_daily",
            "krx-observation",
            instrument_field="instrument",
            available_at="available_at",
            key_fields=("available_at", "instrument"),
            fields={"close": "close"},
        ),
        SourceSpec.of("krx-observation", observation_path),
    )
    register_execution_input(
        project,
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

    paths = _write_components(project, universe)
    signal_ref = component_ref(
        "show007-signal", ComponentKind.STRATEGY_MODEL, paths["signal"], "ReversalSignalStrategy"
    )
    academic_ref = component_ref(
        "show007-academic", ComponentKind.EXCHANGE, paths["academic"], "ShowcaseAcademicExchange"
    )
    for reference in (signal_ref, academic_ref):
        register_component(project, reference)

    signal_agenda = _agenda(
        "show007-signal", OperationRole.STRATEGY_CALLBACK, time(8, 0), callback_days
    )
    valuation_agenda = _agenda(
        "show007-valuation", OperationRole.VALUATION, time(16, 0), callback_days
    )
    monitoring_agenda = _agenda(
        "show007-monitoring", OperationRole.MONITORING, time(16, 30), callback_days
    )
    for agenda in (signal_agenda, valuation_agenda, monitoring_agenda):
        register_agenda(project, agenda)

    signal_config = StrategyConfig(signal_ref, "show007-signal", OperationRole.STRATEGY_CALLBACK)
    valuation_config = ValuationConfig(
        "show007-valuation",
        OperationRole.VALUATION,
    )
    monitoring = MonitoringPolicy("show007-monitoring", OperationRole.MONITORING)
    register_strategy_config(project, signal_config)
    register_valuation_config(project, valuation_config)
    register_monitoring_policy(project, monitoring)

    start = datetime.fromisoformat(f"{callback_days[0].isoformat()}T00:00:00{OFFSET}")
    end = datetime.fromisoformat(f"{callback_days[-1].isoformat()}T23:00:00{OFFSET}")

    definition = RunDefinition(
        signal_config,
        valuation_config,
        ConstraintSet(()),
        monitoring,
        academic_ref,
        "krx-daily",
        start,
        end,
        AccountSnapshot(0, INITIAL_CASH, {}),
        AccountMode.SIGNED,
        instruments=universe,
    )
    result = run(project, preflight_run(project, definition))

    evidence = callback_evidence(result)
    signal_published = publish_run_record(
        project,
        RunRecordSpec.of(
            "signal_measurement",
            table_id="signal.measurement",
            value_fields=(
                "signal_before_weighting",
                "neutralized_signal",
                "run_id",
                "producer_id",
                "stage",
                "event_time",
                "sequence",
            ),
        ),
        result,
    )
    account_published = publish_run_record(
        project,
        RunRecordSpec.of(
            "run_account",
            table_id="vqapr.account",
            value_fields=(
                "cash",
                "nav",
                "quantity",
                "price",
                "observed_at",
                "account_version",
                "run_id",
                "producer_id",
                "stage",
                "event_time",
                "sequence",
            ),
        ),
        result,
    )

    recorded_signal = result.final_state.recorder_rows["signal.measurement"]
    recorded_account = result.final_state.recorder_rows["vqapr.account"]

    # Assertion: published row counts match what the run's own recorder holds.
    if signal_published.row_count != len(recorded_signal):
        raise AssertionError(
            f"published {signal_published.row_count} signal rows from "
            f"{len(recorded_signal)} recorded"
        )
    if account_published.row_count != len(recorded_account):
        raise AssertionError(
            f"published {account_published.row_count} account rows from "
            f"{len(recorded_account)} recorded"
        )

    # Assertion: reading the published parquet back agrees with the recorder rows, row for row.
    replayed_signal = _read_published(signal_published.output_path)
    replayed_account = _read_published(account_published.output_path)
    if len(replayed_signal) != len(recorded_signal):
        raise AssertionError("the published signal table does not read back row for row")
    if len(replayed_account) != len(recorded_account):
        raise AssertionError("the published account series does not read back row for row")

    # Assertion: the neutralised signal is exactly orthogonal to a market column, on every
    # occurrence -- recomputed from the published table alone, never assumed from the transform.
    by_occurrence: dict[object, list[Decimal]] = {}
    for row in replayed_signal:
        by_occurrence.setdefault(row["available_at"], []).append(Decimal(row["neutralized_signal"]))
    if not by_occurrence:
        raise AssertionError("the run never recorded a signal measurement")
    for available_at, values in by_occurrence.items():
        if sum(values) != 0:
            raise AssertionError(
                f"neutralised signal at {available_at} is not orthogonal to the market "
                f"column: sum={sum(values)}"
            )

    # Assertion: at least one occurrence carries a genuinely non-flat signal.
    if all(value == 0 for values in by_occurrence.values() for value in values):
        raise AssertionError("every recorded signal was flat; nothing was ever measured")

    memory = _rehydrate_marks(result, replayed_account)
    replay = _replay(result)
    if replay["replayed_cash"] != replay["committed_cash"]:
        raise AssertionError("fill-journal replay diverged from the committed Account")
    if int(replay["dealt_fills"]) == 0:
        raise AssertionError("the run never dealt a fill; nothing to rehydrate a mark from")

    trace = {
        "status": "current",
        "verified_against": VERIFIED_AGAINST,
        "last_verified_at": LAST_VERIFIED_AT,
        "universe": list(universe),
        "sessions": len(sessions),
        "callbacks": len(callback_days),
        "signal_occurrences": len(by_occurrence),
        "signal_run_record": {
            "dataset": "signal_measurement",
            "rows": signal_published.row_count,
            "read_back": len(replayed_signal),
        },
        "account_run_record": {
            "dataset": "run_account",
            "rows": account_published.row_count,
            "read_back": len(replayed_account),
        },
        "mark_rehydration": memory,
        "execution": {
            "exchange": "Academic (fractional, zero cost)",
            "account_mode": AccountMode.SIGNED.value,
            **replay,
        },
        "callback_evidence_count": len(evidence),
    }
    digests = {
        "signal_measurement.parquet": _digest(signal_published.output_path),
        "signal_measurement.lineage.json": _digest(signal_published.lineage_path),
        "run_account.parquet": _digest(account_published.output_path),
        "run_account.lineage.json": _digest(account_published.lineage_path),
    }
    return trace, digests


def main() -> None:
    if OUTPUTS.exists():
        shutil.rmtree(OUTPUTS)
    OUTPUTS.mkdir(parents=True)

    first, first_digests = _pipeline(OUTPUTS / "replicate-a")
    second, second_digests = _pipeline(OUTPUTS / "replicate-b")
    if first != second:
        raise AssertionError("two clean runs disagreed on their reported outcome")
    if first_digests != second_digests:
        raise AssertionError(f"artifact digests differ: {first_digests} vs {second_digests}")

    trace = {**first, "replicates": 2, "artifacts": first_digests}
    (OUTPUTS / "trace.json").write_text(
        json.dumps(trace, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
    )
    (OUTPUTS / "manifest.json").write_text(
        json.dumps(first_digests, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    execution = trace["execution"]
    print(f"sessions / callbacks         : {trace['sessions']} / {trace['callbacks']}")
    print(f"signal occurrences            : {trace['signal_occurrences']}")
    print(
        f"signal run record             : {trace['signal_run_record']['rows']} rows published "
        f"and read back from a real run"
    )
    print(
        f"account run record            : {trace['account_run_record']['rows']} rows published "
        f"and read back from a real run"
    )
    print(
        f"rehydrated marks               : "
        f"{trace['mark_rehydration']['rehydrated_mark_count']} across "
        f"{len(trace['mark_rehydration']['rehydrated_versions'])} account versions, all field-for-"
        f"field equal to what the run committed"
    )
    print(f"dealt fills                    : {execution['dealt_fills']}")
    print(f"commission / sale tax          : {execution['commission']} / {execution['sale_tax']}")
    print(
        f"replayed == committed cash     : {execution['replayed_cash']} == "
        f"{execution['committed_cash']}"
    )
    print(f"final NAV                      : {execution['final_nav']}")
    print(f"any short position             : {execution['any_short']}")
    print(
        f"artifacts (2 replicates)      : "
        f"{json.dumps(trace['artifacts'], indent=2, sort_keys=True)}"
    )


if __name__ == "__main__":
    main()
