"""vqapr의 유일한 documented Python surface.

사용자와 agent는 이 module에서 config 타입과 operation을 가져온다. 내부 module 경로는 공개 계약이
아니다.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from io import BytesIO
from pathlib import Path

from vqapr.account.account import Account, AccountMode
from vqapr.account.snapshot import AccountSnapshot, AccountState
from vqapr.constraints.builtin import SHIPPED_CONSTRAINTS, shipped_constraint_path
from vqapr.constraints.constraint import Constraint, ConstraintBounds
from vqapr.constraints.evaluation import constraint_requirements as declared_constraint_requirements
from vqapr.constraints.findings import ConstraintFinding, ConstraintReport
from vqapr.constraints.monitoring import MonitoringPolicy
from vqapr.data.datasets import DatasetRegistration, validate
from vqapr.data.lookback import CalendarLookback, RowsLookback
from vqapr.data.requirements import DataRequirement
from vqapr.data.sources import SourceSpec
from vqapr.data.store import DuckDbObservationStore
from vqapr.data.windows import ModelWindow
from vqapr.domain.errors import VqaprError
from vqapr.domain.timestamps import LocalInstantDeclaration
from vqapr.evidence.artifacts import SimulationFailure
from vqapr.evidence.tables import TableSpec
from vqapr.exchange.conventions import ExactExecutionTarget, FillConvention, FillSelector
from vqapr.exchange.costs import CostRule, FillCost
from vqapr.exchange.execution_table import (
    ExecutionInputRegistration,
    ExecutionTableSpec,
    validate_execution_input,
)
from vqapr.exchange.fills import ZeroDealtReason
from vqapr.exchange.listings import ExchangeRulesView, ListingRule
from vqapr.exchange.venue import AcademicExchange, Side
from vqapr.exchange.venues.krx import KrxExchange
from vqapr.extension.component import ComponentKind, ComponentRef
from vqapr.extension.fingerprint import fingerprint_component
from vqapr.extension.loading import load_constraint, load_exchange, load_strategy_model
from vqapr.extension.registration import register_data_model
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
from vqapr.valuation.configuration import ValuationConfig
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
    "CostRule",
    "DataModel",
    "DataModelContext",
    "DataRequirement",
    "DatasetRegistration",
    "EconomicPortfolioIntent",
    "ExactExecutionTarget",
    "ExchangeRulesView",
    "ExecutionInputRegistration",
    "ExecutionTableSpec",
    "FillConvention",
    "FillCost",
    "FillSelector",
    "FrozenAgenda",
    "FrozenRun",
    "IntentSourceRef",
    "KrxExchange",
    "ListingRule",
    "LocalInstantDeclaration",
    "MaterializationResult",
    "MaterializationSpec",
    "MonitoringPolicy",
    "NoDecision",
    "OperationAgenda",
    "OperationOccurrence",
    "OperationRole",
    "OptimizeRefusal",
    "OptimizeResult",
    "PortfolioDirection",
    "PortfolioTarget",
    "RowsLookback",
    "RunDefinition",
    "RunRecordResult",
    "RunRecordSpec",
    "Side",
    "SimulationFailure",
    "SimulationResult",
    "SourceSpec",
    "StrategyConfig",
    "StrategyModel",
    "StrategyModelContext",
    "TableSpec",
    "TickerNetting",
    "ValuationConfig",
    "VqaprError",
    "WeightingRefusal",
    "ZeroDealtReason",
    "callback_evidence",
    "component_ref",
    "equal_weight",
    "materialize",
    "net_members",
    "optimize",
    "preflight_run",
    "proportional_weight",
    "publish_run_allocation",
    "publish_run_record",
    "register_agenda",
    "register_component",
    "register_data_model",
    "register_dataset",
    "register_execution_input",
    "register_monitoring_policy",
    "register_strategy_config",
    "register_valuation_config",
    "rescale",
    "run",
    "shipped_constraint_path",
    "signal_weight",
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
    diagnosis, _ = validate(registration, source)
    diagnosis.raise_if_failed()
    return Workspace.create(project_root).register_dataset(registration, source)


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


def _marks_for_occurrence(
    store: DuckDbObservationStore,
    frozen: FrozenRun,
    cutoff: datetime,
    account: object,
) -> Mapping[str, Decimal]:
    from vqapr.account.snapshot import AccountSnapshot

    if not isinstance(account, AccountSnapshot):
        raise TypeError("mark provider requires an AccountSnapshot")
    held = tuple(
        sorted(instrument for instrument, quantity in account.positions.items() if quantity)
    )
    if not held:
        return {}
    requirement = frozen.valuation.mark_requirement
    batch = store.query(
        requirement,
        evaluation_time=cutoff,
        instruments=held,
    )
    field = requirement.fields[0]
    marks: dict[str, Decimal] = {}
    for row in batch.rows:
        value = row[field]
        if value is not None:
            if not isinstance(value, Decimal):
                raise TypeError("valuation mark field must contain Decimal values")
            marks[row["instrument"]] = value
    return marks


def run(
    project_root: str | Path,
    frozen_run: FrozenRun,
) -> SimulationResult:
    """Execute exactly one simulation from a preflight-produced frozen authority."""
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
    store = DuckDbObservationStore(catalog)
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
        account=Account(mode=frozen.initial_account_mode),
        exchange=exchange,
        constraints=constraints,
        marks_for_occurrence=lambda valuation, cutoff, account: _marks_for_occurrence(
            store, frozen, cutoff, account
        ),
    )
    return flow.run()
