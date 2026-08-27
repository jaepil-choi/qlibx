"""vqapr의 유일한 documented Python surface.

사용자와 agent는 이 module에서 config 타입과 operation을 가져온다. 내부 module 경로는 공개 계약이
아니다.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from vqapr.account.account import Account, AccountMode
from vqapr.account.history import retained_marks
from vqapr.account.snapshot import AccountSnapshot, AccountState
from vqapr.analysis.performance import drawdown, nav_series, returns
from vqapr.analysis.signal import (
    decay,
    hit_rate,
    information_coefficient,
    rank_information_coefficient,
)
from vqapr.authoring import DatasetInput, Hold, Rebalance, StrategyResult
from vqapr.constraints.builtin import SHIPPED_CONSTRAINTS, shipped_constraint_path
from vqapr.constraints.constraint import Constraint, ConstraintBounds
from vqapr.constraints.evaluation import constraint_requirements as declared_constraint_requirements
from vqapr.constraints.findings import ConstraintFinding, ConstraintReport
from vqapr.constraints.monitoring import MonitoringPolicy
from vqapr.data.datasets import DatasetRegistration, validate
from vqapr.data.lookback import CalendarLookback, RowsLookback
from vqapr.data.requirements import DataRequirement
from vqapr.data.scan import ScanSession
from vqapr.data.sources import SourceSpec
from vqapr.data.store import DuckDbObservationStore
from vqapr.data.windows import ModelWindow
from vqapr.domain.errors import VqaprError
from vqapr.domain.instruments import (
    EtfInstrument,
    FactorInstrument,
    IndexInstrument,
    Instrument,
    InstrumentKind,
    StockInstrument,
    instrument,
    instruments,
)
from vqapr.domain.timestamps import LocalInstantDeclaration, declare_local_instant
from vqapr.evidence.artifacts import SimulationFailure
from vqapr.evidence.tables import TableSpec
from vqapr.exchange.conventions import ExactExecutionTarget, FillConvention, FillSelector
from vqapr.exchange.costs import FillCost, SideCost
from vqapr.exchange.execution_table import (
    ExecutionInputRegistration,
    ExecutionTableSpec,
    validate_execution_input,
)
from vqapr.exchange.fills import ZeroDealtReason
from vqapr.exchange.listings import (
    ExchangeRulesView,
    ExecutionFieldRequirement,
    ListingAccess,
    TradeRule,
    TradeTerms,
    trade_rules_by_kind,
)
from vqapr.exchange.venue import AcademicExchange, Side
from vqapr.exchange.venues.krx import KrxExchange, KrxTradeRule, krx_rules
from vqapr.extension.component import ComponentKind, ComponentRef
from vqapr.extension.fingerprint import fingerprint_component
from vqapr.extension.loading import load_constraint, load_exchange, load_strategy_model
from vqapr.extension.registration import (
    register_constraint,
    register_data_model,
    register_exchange,
    register_strategy_model,
)
from vqapr.flow.materialize import (
    AllocationPublicationResult,
    AllocationPublicationSpec,
    MaterializationResult,
    MaterializationSpec,
    RunRecordResult,
    RunRecordSpec,
    materialize,
    publish_run_allocation,
    publish_run_record,
)
from vqapr.flow.preflight import preflight_run as _preflight_run
from vqapr.flow.run import ConstraintSet, FrozenAgenda, FrozenRun, RunDefinition, StrategyConfig
from vqapr.flow.run_records import RECORD_FIELDS, RunRecordWriter
from vqapr.flow.run_state import RunStateRepository
from vqapr.flow.simulation import SimulationFlow, SimulationResult, callback_evidence
from vqapr.models.contexts import DataModelContext, StrategyModelContext
from vqapr.models.data_model import DataModel
from vqapr.models.memory import normalize_memory
from vqapr.models.strategy_model import NoDecision, StrategyModel
from vqapr.portfolio.allocation import (
    AllocationInvariants,
    AllocationSign,
    AllocationViolation,
    validate_allocation,
)
from vqapr.portfolio.budgets import Budget, PortfolioDirection
from vqapr.portfolio.diagnostics import TickerNetting, net_members
from vqapr.portfolio.intents import EconomicPortfolioIntent, IntentSourceRef, PortfolioTarget
from vqapr.portfolio.optimize import QUANTUM, OptimizeRefusal, OptimizeResult, optimize
from vqapr.portfolio.weighting import (
    WeightingRefusal,
    equal_weight,
    proportional_weight,
    rescale,
    signal_weight,
)
from vqapr.runtime.agendas import (
    OperationAgenda,
    OperationOccurrence,
    OperationRole,
)
from vqapr.testing.conformance import conformance
from vqapr.transforms.cross_section import rank
from vqapr.transforms.fama_french import fama_french_assign, fama_french_cut_points
from vqapr.transforms.neutralize import NeutralizationRefusal, neutralize
from vqapr.valuation.configuration import ValuationConfig
from vqapr.valuation.marks import Mark, MarkBatch
from vqapr.workspace import Workspace

__all__ = (
    "QUANTUM",
    "SHIPPED_CONSTRAINTS",
    "AcademicExchange",
    "AccountMode",
    "AccountSnapshot",
    "AllocationInvariants",
    "AllocationPublicationResult",
    "AllocationPublicationSpec",
    "AllocationSign",
    "AllocationViolation",
    "Budget",
    "CalendarLookback",
    "ComponentKind",
    "ComponentRef",
    "Constraint",
    "ConstraintBounds",
    "ConstraintFinding",
    "ConstraintReport",
    "ConstraintSet",
    "DataModel",
    "DataModelContext",
    "DataRequirement",
    "DatasetInput",
    "DatasetRegistration",
    "EconomicPortfolioIntent",
    "EtfInstrument",
    "ExactExecutionTarget",
    "ExchangeRulesView",
    "ExecutionFieldRequirement",
    "ExecutionInputRegistration",
    "ExecutionTableSpec",
    "FactorInstrument",
    "FillConvention",
    "FillCost",
    "FillSelector",
    "FrozenAgenda",
    "FrozenRun",
    "Hold",
    "IndexInstrument",
    "Instrument",
    "InstrumentKind",
    "IntentSourceRef",
    "KrxExchange",
    "KrxTradeRule",
    "ListingAccess",
    "LocalInstantDeclaration",
    "Mark",
    "MarkBatch",
    "MaterializationResult",
    "MaterializationSpec",
    "MonitoringPolicy",
    "NeutralizationRefusal",
    "NoDecision",
    "OperationAgenda",
    "OperationOccurrence",
    "OperationRole",
    "OptimizeRefusal",
    "OptimizeResult",
    "PortfolioDirection",
    "PortfolioTarget",
    "Rebalance",
    "RowsLookback",
    "RunDefinition",
    "RunRecordResult",
    "RunRecordSpec",
    "Side",
    "SideCost",
    "SimulationFailure",
    "SimulationResult",
    "SourceSpec",
    "StockInstrument",
    "StrategyConfig",
    "StrategyModel",
    "StrategyModelContext",
    "StrategyResult",
    "TableSpec",
    "TickerNetting",
    "TradeRule",
    "TradeTerms",
    "ValuationConfig",
    "VqaprError",
    "WeightingRefusal",
    "ZeroDealtReason",
    "callback_evidence",
    "component_ref",
    "conformance",
    "decay",
    "declare_local_instant",
    "drawdown",
    "equal_weight",
    "fama_french_assign",
    "fama_french_cut_points",
    "hit_rate",
    "information_coefficient",
    "instrument",
    "instruments",
    "krx_rules",
    "materialize",
    "nav_series",
    "net_members",
    "neutralize",
    "optimize",
    "preflight_run",
    "proportional_weight",
    "publish_run_allocation",
    "publish_run_record",
    "rank",
    "rank_information_coefficient",
    "register_agenda",
    "register_component",
    "register_constraint",
    "register_data_model",
    "register_dataset",
    "register_exchange",
    "register_execution_input",
    "register_monitoring_policy",
    "register_strategy_config",
    "register_strategy_model",
    "register_valuation_config",
    "rescale",
    "returns",
    "run",
    "shipped_constraint_path",
    "signal_weight",
    "trade_rules_by_kind",
    "validate_allocation",
)


def register_dataset(
    project_root: str | Path,
    registration: DatasetRegistration,
    source: SourceSpec,
) -> bool:
    """준비된 parquet을 검증하고 project workspace에 등록한다.

    새 등록이면 ``True``, 디스크에 이미 같은 선언이 있으면 ``False``다. 검증이나 persistence가
    실패하면 ``VqaprError``를 발생시키며, 검증 실패는 workspace를 만들거나 바꾸지 않는다.
    """
    diagnosis, _, measured = validate(registration, source)
    diagnosis.raise_if_failed()
    # `measured` is the registration with its span filled in from the scan validation just ran.
    # Registering the caller's copy instead would persist a declaration missing the one fact only
    # a full read can establish, and the next reader would have to read the file again to get it.
    return Workspace.create(project_root).register_dataset(measured, source)


def component_ref(
    component_id: str,
    kind: ComponentKind,
    path: str | Path,
    object_name: str,
    *,
    config: dict[str, object] | None = None,
) -> ComponentRef:
    """Build a source-fingerprinted component declaration for registration."""
    fingerprint = fingerprint_component(
        path,
        kind=kind,
        object_name=object_name,
        config=config,
    )
    return ComponentRef.of(
        component_id,
        kind,
        path,
        object_name,
        config=config,
        fingerprint=fingerprint,
    )


def register_execution_input(
    project_root: str | Path,
    registration: ExecutionInputRegistration,
) -> bool:
    """준비된 execution parquet과 fill binding을 검증하고 project에 등록한다."""
    diagnosis = validate_execution_input(registration)
    diagnosis.raise_if_failed()
    return Workspace.create(project_root).register_execution_input(registration)


def register_agenda(project_root: str | Path, agenda: OperationAgenda) -> bool:
    return Workspace.create(project_root).register_agenda(agenda)


def register_component(project_root: str | Path, component: ComponentRef) -> bool:
    """Register one validated extension component reference."""
    return Workspace.create(project_root).register_component(component)


def register_strategy_config(project_root: str | Path, config: StrategyConfig) -> bool:
    return Workspace.create(project_root).register_strategy_config(config)


def register_valuation_config(project_root: str | Path, config: ValuationConfig) -> bool:
    return Workspace.create(project_root).register_valuation_config(config)


def register_monitoring_policy(project_root: str | Path, policy: MonitoringPolicy) -> bool:
    return Workspace.create(project_root).register_monitoring_policy(policy)


def preflight_run(project_root: str | Path, definition: RunDefinition) -> FrozenRun:
    """Resolve a run definition against registered declarations without running it."""
    if not isinstance(definition, RunDefinition):
        raise TypeError("definition must be a RunDefinition")
    return _preflight_run(Workspace.open(project_root), definition)


class _FrozenCatalog:
    """Read-only data declarations captured by preflight, never a mutable workspace."""

    def __init__(self, frozen: FrozenRun) -> None:
        self._datasets = {str(dataset.dataset_id): dataset for dataset in frozen.datasets}
        self._sources = {str(source.source_id): source for source in frozen.sources}

    def dataset(self, raw_dataset_id: str) -> DatasetRegistration:
        return self._datasets[raw_dataset_id]

    def source(self, raw_source_id: str) -> SourceSpec:
        return self._sources[raw_source_id]


def run(
    project_root: str | Path,
    frozen_run: FrozenRun,
    *,
    store_root: str | Path | None = None,
    run_id: str | None = None,
    replace_record: bool = False,
) -> SimulationResult:
    """Execute exactly one simulation from a preflight-produced frozen authority.

    When `store_root` is given the run freezes its own record beneath it, which is what makes the
    result readable by any later process -- including `show run` from a cold one, and including the
    other four of five concurrent runs. Omitted, the run keeps its results in memory exactly as
    before: an in-process caller that already holds the result should not be made to write it to
    disk to get it.
    """
    if not isinstance(frozen_run, FrozenRun):
        raise TypeError("frozen_run must be a FrozenRun returned by preflight_run")
    root_path = Path(project_root)
    frozen = frozen_run
    if frozen.initial_account_snapshot is None or frozen.initial_account_mode is None:
        raise ValueError("public run requires frozen initial account authority")
    if frozen.exchange is None:
        raise ValueError("public run requires a frozen Exchange authority")
    if frozen.execution_input is None:
        raise ValueError("public run requires a frozen execution input")
    validate_execution_input(frozen.execution_input).raise_if_failed()

    strategy = load_strategy_model(frozen.strategy.component, project_root=root_path)
    exchange = load_exchange(frozen.exchange, project_root=root_path)
    constraints = tuple(
        load_constraint(ref, project_root=root_path) for ref in frozen.constraints.constraints
    )
    catalog = _FrozenCatalog(frozen)
    # One physical handle for the whole run. duckdb caches parquet metadata for a connection's
    # lifetime, and closing per query threw that away on every observation.
    session = ScanSession()
    store = DuckDbObservationStore(catalog, session=session)
    strategy_requirements = strategy.requirements()
    if strategy_requirements != frozen.strategy_requirements:
        raise ValueError("loaded Strategy requirements drifted from FrozenRun")
    constraint_requirements = declared_constraint_requirements(constraints)
    if constraint_requirements != frozen.constraint_requirements:
        raise ValueError("loaded Constraint requirements drifted from FrozenRun")
    root = AccountState(frozen.initial_account_snapshot)
    strategy.memory = normalize_memory(frozen.initial_model_memory)
    strategy.load_payload(BytesIO(frozen.initial_payload))
    state = RunStateRepository(
        initial_account=root,
        initial_model_memory=frozen.initial_model_memory,
        initial_payload=frozen.initial_payload,
    )
    if state.root.current_model_state_ref != frozen.initial_model_state_ref:
        raise RuntimeError("initial Model state does not match frozen run authority")
    initial_ref = state.root.current_model_state_ref
    if initial_ref is None or state.load_payload(initial_ref) != frozen.initial_payload:
        raise RuntimeError("initial Strategy payload does not match frozen run authority")
    writer = None
    if store_root is not None:
        writer = RunRecordWriter(Path(store_root), run_id or str(frozen.identity))
        writer.open(replace=replace_record)
    flow = SimulationFlow(
        frozen,
        strategy,
        state,
        strategy_window_for_occurrence=lambda occurrence: ModelWindow(
            evaluation_time=occurrence.evaluation_time,
            instruments=frozen.instruments,
            store=store,
            allowed_requirements=frozen.strategy_requirements,
        ),
        constraint_window_for_occurrence=lambda occurrence: ModelWindow(
            evaluation_time=occurrence.evaluation_time,
            instruments=frozen.instruments,
            store=store,
            allowed_requirements=frozen.constraint_requirements,
        ),
        # A run retains exactly the marks somebody declared they would read. Declaring nothing
        # keeps one, so a Strategy that never looks at its own path costs nothing to carry it.
        account=Account(
            mode=frozen.initial_account_mode,
            retained_marks=retained_marks(
                tuple(getattr(strategy, "account_requirements", tuple)())
            ),
        ),
        exchange=exchange,
        constraints=constraints,
        scan_session=session,
        # The run's liveness signal. Without it the record's lock is stamped once at `open` and
        # never touched again until the run ends -- so any run longer than `LOCK_STALE_AFTER`
        # reads as dead WHILE STILL EXECUTING, and a peer takes its id and deletes its tables. A
        # factor run here takes three to six minutes against a two-minute window, so that is every
        # real run, not an edge case.
        on_progress=writer.heartbeat if writer is not None else None,
    )
    try:
        result = flow.run()
        if writer is not None:
            _freeze_record(writer, result, frozen)
    except BaseException:
        # A run that died still holds its id. Releasing here turns a crash into an ordinary
        # retry instead of stranding the id until the lock goes stale. `_freeze_record` is inside
        # the guard for the same reason: a failure while writing the record is still a failure
        # that must not keep the id.
        if writer is not None:
            writer.release()
        raise
    finally:
        session.close()
    return result


def _freeze_record(writer: RunRecordWriter, result: SimulationResult, frozen: FrozenRun) -> None:
    """Write the run's rows and its own facts, so a later process can answer questions about it.

    The rows go first and the record last, because `record.json` existing is what marks the record
    complete. A reader that finds one knows the run reached its end; a run killed midway leaves its
    rows and no record, which `run_ids` correctly declines to list as a finished run.
    """
    recorded = result.final_state.recorder_rows
    for table_id, rows in sorted(recorded.items()):
        writer.append(table_id, rows)

    account = result.final_state.account
    snapshot = None if account is None else account.snapshot

    # AC-R3's five: the facts a later reader cannot reconstruct from the rows alone. Each is built
    # by the function `RECORD_FIELDS` names, so the field set is genuinely ONE list rather than two
    # with a comparison between them -- a field added here without a builder is a KeyError at the
    # comprehension below, not a drift that reaches disk and waits to be noticed.
    builders = {
        "account": lambda: None
        if snapshot is None
        else {
            "version": snapshot.version,
            "cash": snapshot.cash,
            "positions": dict(snapshot.positions),
        },
        "tables": lambda: {
            table_id: {
                "rows": len(rows),
                # Formations, not just rows: a diagnostic table's row count says how much was
                # written, and the distinct event_time count says how often. Research asks the
                # second question and the first cannot answer it.
                "formations": len({str(row.get("event_time")) for row in rows}),
            }
            for table_id, rows in sorted(recorded.items())
        },
        "contract": lambda: _contract_report(result),
        "source_digest": lambda: str(frozen.identity),
        "period": lambda: {
            "start": frozen.start,
            "end": frozen.end,
            "occurrences": len(result.occurrences),
        },
    }

    # `run_id` is stamped by the writer itself, so it is the one field this does not supply.
    writer.finish({field: builders[field]() for field in RECORD_FIELDS if field != "run_id"})


def _contract_report(result: SimulationResult) -> dict[str, object]:
    """What the run's constraints promised, and how often each was actually checked.

    `held` and `checked` are two different numbers, and conflating them hides the case that matters
    most: a declaration checked zero times is not a declaration that held. It is one nobody asked
    about, and reporting that as `ok` would be the strongest false assurance this record could
    carry. So a constraint with `checked == 0` reports `ok: false` with a `cause` saying exactly
    that.

    Scope, stated rather than implied: this reports the CONSTRAINTS a run declared. AC-R6 also
    names `weights`/`forms`/`records`, which are the authoring contract's declarations -- they do
    not exist yet, and inventing entries for them here would report a promise nobody made. They
    join this block when that contract lands.
    """
    from vqapr.flow.run_state import LifecycleKind

    findings: dict[str, dict[str, int]] = {}
    for entry in getattr(result.final_state, "lifecycle_trace", ()):
        evidence = getattr(entry, "evidence", None)
        for item in getattr(evidence, "intended", ()) or ():
            finding = getattr(item, "finding", None)
            constraint_id = str(getattr(finding, "constraint_id", "") or "")
            if not constraint_id:
                continue
            counts = findings.setdefault(constraint_id, {"held": 0, "checked": 0})
            counts["checked"] += 1
            if getattr(finding, "passed", False):
                counts["held"] += 1

    accepted = sum(
        1
        for entry in getattr(result.final_state, "lifecycle_trace", ())
        if getattr(entry, "kind", None) is LifecycleKind.ACCEPTED_INTENT
    )
    report: dict[str, object] = {}
    for constraint_id, counts in sorted(findings.items()):
        violations = counts["checked"] - counts["held"]
        entry: dict[str, object] = {
            "held": counts["held"],
            "checked": counts["checked"],
            "ok": violations == 0 and counts["checked"] > 0,
        }
        if violations:
            entry["cause"] = f"{violations} of {counts['checked']} check(s) did not hold"
            entry["fix"] = (
                f"loosen {constraint_id} to a bound the strategy can meet, or change the "
                "strategy so its intents satisfy it"
            )
        elif counts["checked"] == 0:
            entry["cause"] = "declared but never checked, so nothing was proven about it"
            entry["fix"] = "remove the declaration, or run over a period where it is exercised"
        report[constraint_id] = entry

    # A run that accepted intents while checking no constraint is not a clean run; it is a run
    # nobody constrained. Saying so is the point of reporting counts rather than a verdict.
    report["accepted_intents"] = accepted
    return report
