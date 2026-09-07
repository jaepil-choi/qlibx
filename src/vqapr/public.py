"""vqapr의 유일한 documented Python surface.

사용자와 agent는 이 module에서 config 타입과 operation을 가져온다. 내부 module 경로는 공개 계약이
아니다.
"""

from __future__ import annotations

from pathlib import Path

from vqapr.account.account import AccountMode
from vqapr.account.snapshot import AccountSnapshot
from vqapr.analysis.performance import drawdown, nav_series, returns
from vqapr.analysis.signal import (
    decay,
    hit_rate,
    information_coefficient,
    rank_information_coefficient,
)
from vqapr.authoring import (
    Constraint,
    ConstraintBounds,
    ConstraintFinding,
    DataModel,
    DatasetInput,
    Hold,
    Rebalance,
    StrategyModel,
)
from vqapr.calls import DataModelContext, StrategyModelContext
from vqapr.constraints.builtin import SHIPPED_CONSTRAINTS, shipped_constraint_path
from vqapr.constraints.evaluation import ConstraintReport
from vqapr.data.datasets import DatasetRegistration, Grain
from vqapr.data.lookback import CalendarLookback, InstantsLookback, RowsLookback
from vqapr.data.panel import PanelWindow
from vqapr.data.requirements import DataRequirement
from vqapr.data.sources import SourceSpec
from vqapr.data.store import ObservationBatch
from vqapr.data.windows import ModelWindow
from vqapr.declarations import register_dataset as register_dataset
from vqapr.declarations import register_execution_input as register_execution_input
from vqapr.domain.agendas import (
    OperationOccurrence,
    OperationRole,
)
from vqapr.domain.errors import VqaprError
from vqapr.domain.instruments import (
    EtfInstrument,
    FactorInstrument,
    IndexInstrument,
    Instrument,
    InstrumentKind,
    InstrumentRoster,
    StockInstrument,
    build_roster,
    export_roster,
    instrument,
    instruments,
)
from vqapr.domain.values import LocalInstantDeclaration, Mark, MarkBatch, declare_local_instant
from vqapr.evidence.artifacts import SimulationFailure
from vqapr.evidence.tables import TableSpec
from vqapr.exchange.conventions import ExactExecutionTarget, FillConvention, FillSelector
from vqapr.exchange.costs import FillCost, SideCost
from vqapr.exchange.execution_table import (
    ExecutionInputRegistration,
    ExecutionTableSpec,
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
from vqapr.exchange.venues.krx import KrxExchange, KrxTradeRule, krx_listings, krx_rules
from vqapr.extension.component import ComponentKind, ComponentRef
from vqapr.extension.fingerprint import fingerprint_component

# One door into the extension authorities: `vqapr.extension.*`, never `vqapr._internal.*`.
# The adapters below are transitional and scheduled for deletion, and that is the reason to use
# them rather than a reason to route around them -- a deletion whose callers all name one path is
# four files removed and imports breaking loudly, while one reached by two paths has to be found
# by grep. `as_loaded_fingerprint` was the exception that proved it: this file imported it from
# `_internal` and the three names below from the adapter, and two later modules copied the
# bypass without the reasoning (`docs/issues/029`; the rule is in
# `docs/design/agent-first-surface.md`, and `tests/boundaries/test_internal_has_one_door.py`
# enforces it).
from vqapr.extension.registration import (
    register_constraint,
    register_data_model,
    register_exchange,
    register_strategy_model,
)
from vqapr.flow.datamodel import DataModelResult
from vqapr.flow.frozen import FrozenAgenda, FrozenDataModel, FrozenRun, FrozenStrategy
from vqapr.flow.orchestration import RunResult, StrategyOutcome, preflight_run, run
from vqapr.flow.record import (
    RunRecordMissing,
    read_run_record,
    read_strategy_record,
    run_ids,
    strategy_refs,
)

# Orchestration, evidence and roster reading moved to their owning layers by record `111`.
# Re-exported unchanged so every caller and every emitted scaffold keeps working. The `as` form is
# deliberate: it marks these as intentional re-exports, which is both what they are and what stops
# a lint autofix from deleting them as unused.
from vqapr.flow.record import contract_report as contract_report
from vqapr.flow.record import freeze_strategy_record as freeze_strategy_record
from vqapr.flow.record import read_typed_table as read_strategy_table
from vqapr.flow.roster import registered_roster as registered_roster
from vqapr.flow.roster import roster_report as roster_report
from vqapr.flow.run import ConstraintSet, DataModelEntry, RunDefinition, StrategyEntry
from vqapr.flow.simulation import SimulationResult, callback_evidence
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
from vqapr.report.document import RunReport, StrategyReport
from vqapr.report.record import run_report, strategy_report
from vqapr.testing.conformance import conformance
from vqapr.transforms.cross_section import rank
from vqapr.transforms.fama_french import fama_french_assign, fama_french_cut_points
from vqapr.transforms.neutralize import NeutralizationRefusal, neutralize
from vqapr.workspace import Workspace

__all__ = (
    "QUANTUM",
    "SHIPPED_CONSTRAINTS",
    "AcademicExchange",
    "AccountMode",
    "AccountSnapshot",
    "AllocationInvariants",
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
    "DataModelEntry",
    "DataModelResult",
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
    "FrozenDataModel",
    "FrozenRun",
    "FrozenStrategy",
    "Grain",
    "Hold",
    "IndexInstrument",
    "InstantsLookback",
    "Instrument",
    "InstrumentKind",
    "InstrumentRoster",
    "IntentSourceRef",
    "KrxExchange",
    "KrxTradeRule",
    "ListingAccess",
    "LocalInstantDeclaration",
    "Mark",
    "MarkBatch",
    "ModelWindow",
    "NeutralizationRefusal",
    # The two halves of what a Model is handed. `ObservationBatch` is the return type of the one
    # method a DataModel author can call, and it was reachable only by opening installed source:
    # not in `__all__`, absent from the skill, and with no docstring naming its row keys or
    # ordering (`docs/issues/031`). `ModelWindow` was importable but undeclared, while the
    # constraint scaffold has always emitted `from vqapr.public import ... ModelWindow`.
    "ObservationBatch",
    "OperationOccurrence",
    "OperationRole",
    "OptimizeRefusal",
    "OptimizeResult",
    "PanelWindow",
    "PortfolioDirection",
    "PortfolioTarget",
    "Rebalance",
    "RowsLookback",
    "RunDefinition",
    "RunRecordMissing",
    "RunReport",
    "RunResult",
    "Side",
    "SideCost",
    "SimulationFailure",
    "SimulationResult",
    "SourceSpec",
    "StockInstrument",
    "StrategyEntry",
    "StrategyModel",
    "StrategyModelContext",
    "StrategyOutcome",
    "StrategyReport",
    "TableSpec",
    "TickerNetting",
    "TradeRule",
    "TradeTerms",
    "VqaprError",
    "WeightingRefusal",
    "ZeroDealtReason",
    "build_roster",
    "callback_evidence",
    "component_ref",
    "conformance",
    "decay",
    "declare_local_instant",
    "drawdown",
    "equal_weight",
    "export_roster",
    "fama_french_assign",
    "fama_french_cut_points",
    "hit_rate",
    "information_coefficient",
    "instrument",
    "instruments",
    "krx_listings",
    "krx_rules",
    "nav_series",
    "net_members",
    "neutralize",
    "optimize",
    "preflight_run",
    "proportional_weight",
    "rank",
    "rank_information_coefficient",
    "read_run_record",
    "read_strategy_record",
    "read_strategy_table",
    "register_component",
    "register_constraint",
    "register_data_model",
    "register_dataset",
    "register_exchange",
    "register_execution_input",
    "register_run",
    "register_strategy_model",
    "rescale",
    "returns",
    "run",
    "run_ids",
    "run_report",
    "shipped_constraint_path",
    "signal_weight",
    "strategy_refs",
    "strategy_report",
    "trade_rules_by_kind",
    "validate_allocation",
)




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




def register_component(project_root: str | Path, component: ComponentRef) -> bool:
    """Register one validated extension component reference."""
    with Workspace.transaction(project_root) as transaction:
        return transaction.register_component(component)


def register_run(project_root: str | Path, definition: RunDefinition) -> bool:
    """Register a run: the reusable configuration `vqapr run <run-id>` executes (record `139`)."""
    with Workspace.transaction(project_root) as transaction:
        return transaction.register_run(definition)
