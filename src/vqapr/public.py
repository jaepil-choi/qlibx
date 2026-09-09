"""vqapr의 유일한 documented Python surface.

사용자와 agent는 이 module에서 config 타입과 operation을 가져온다. 내부 module 경로는 공개 계약이
아니다.
"""

from __future__ import annotations

from pathlib import Path

from vqapr.account.account import AccountMode
from vqapr.analysis.performance import drawdown, nav_series, returns
from vqapr.analysis.signal import (
    decay,
    hit_rate,
    information_coefficient,
    rank_information_coefficient,
)
from vqapr.authoring import (
    Compliance,
    ComplianceCall,
    ComplianceFinding,
    Component,
    DataModel,
    DatasetInput,
    Hold,
    Part,
    Rebalance,
    StrategyModel,
    Tool,
)
from vqapr.authoring.context import DataModelContext, StrategyModelContext
from vqapr.authoring.records import TableSpec
from vqapr.compliance.builtin import SHIPPED_COMPLIANCE, shipped_compliance_path
from vqapr.compliance.evaluation import ComplianceReport
from vqapr.data.datasets import DatasetRegistration, ExecutionRole
from vqapr.data.lookback import CalendarLookback, InstantsLookback, RowsLookback
from vqapr.data.panel import PanelWindow
from vqapr.data.requirements import DataRequirement
from vqapr.data.sources import SourceSpec
from vqapr.data.store import ObservationBatch
from vqapr.data.windows import ModelWindow
from vqapr.domain.account_state import AccountSnapshot
from vqapr.domain.agendas import (
    OperationOccurrence,
)
from vqapr.domain.costs import FillCost, SideCost
from vqapr.domain.errors import Stage, Status, VqaprError
from vqapr.domain.fills import ZeroDealtReason
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
from vqapr.domain.shapes import CrossSection, Grain, Series
from vqapr.domain.values import (
    LocalInstantDeclaration,
    Mark,
    MarkBatch,
    Side,
    declare_local_instant,
)
from vqapr.exchange.conventions import ExactExecutionTarget, FillRule
from vqapr.exchange.execution_table import (
    ExecutionTable,
    ExecutionTableSpec,
)
from vqapr.exchange.listings import (
    ExchangeRulesView,
    ExecutionFieldRequirement,
    ListingAccess,
    TradeRule,
    TradeTerms,
    trade_rules_by_kind,
)
from vqapr.exchange.venue import AcademicExchange, ExecutionCall
from vqapr.exchange.venues.krx import (
    KrxExchange,
    KrxSettings,
    KrxTradeRule,
    krx_listings,
    krx_rules,
)
from vqapr.extension.component import ComponentKind, ComponentRef
from vqapr.extension.conformance import conformance
from vqapr.flow.declaration.frozen import FrozenAgenda, FrozenDataModel, FrozenRun, FrozenStrategy
from vqapr.flow.engine.artifacts import SimulationFailure

# Orchestration, evidence and roster reading moved to their owning layers by record `111`.
# Re-exported unchanged so every caller and every emitted scaffold keeps working. The `as` form is
# deliberate: it marks these as intentional re-exports, which is both what they are and what stops
# a lint autofix from deleting them as unused.
from vqapr.flow.freeze import contract_report as contract_report
from vqapr.flow.freeze import freeze_strategy_record as freeze_strategy_record
from vqapr.flow.orchestration import RunResult, StrategyOutcome, preflight_run, run
from vqapr.flow.roster import registered_roster as registered_roster
from vqapr.flow.roster import roster_report as roster_report
from vqapr.flow.run.loop import DataModelResult, SimulationResult, callback_evidence
from vqapr.portfolio.allocation import (
    AllocationInvariants,
    AllocationSign,
    AllocationViolation,
    validate_allocation,
)
from vqapr.portfolio.bounds import intersect, no_short, single_name_cap
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

# One door into the extension authorities: `vqapr.extension.*`, never `vqapr._internal.*`.
# (The four `register_*` below left `extension/` for `project/` at record `196` -- the write
# half is the workspace's -- but they are still reached by one path, which is the rule here.)
# The adapters below are transitional and scheduled for deletion, and that is the reason to use
# them rather than a reason to route around them -- a deletion whose callers all name one path is
# four files removed and imports breaking loudly, while one reached by two paths has to be found
# by grep. `as_loaded_fingerprint` was the exception that proved it: this file imported it from
# `_internal` and the three names below from the adapter, and two later modules copied the
# bypass without the reasoning (`docs/issues/archive/029`; the rule is in
# `docs/design/agent-first-surface.md`, and `tests/boundaries/test_internal_has_one_door.py`
# enforces it).
from vqapr.project.registration import (
    register_compliance,
    register_data_model,
    register_exchange,
    register_instruments,
    register_strategy_model,
)
from vqapr.project.registration import register_dataset as register_dataset
from vqapr.project.run import (
    ComplianceSet,
    DataModelEntry,
    RunAgenda,
    RunDefinition,
    RunExecution,
    RunFill,
    StrategyEntry,
)
from vqapr.project.store import Workspace
from vqapr.record import (
    RunRecordMissing,
    read_run_record,
    read_strategy_record,
    run_ids,
    strategy_refs,
)
from vqapr.record import read_typed_table as read_strategy_table
from vqapr.report.document import RunReport, StrategyReport
from vqapr.report.record import run_report, strategy_report
from vqapr.transforms.cross_section import rank
from vqapr.transforms.fama_french import fama_french_assign, fama_french_cut_points
from vqapr.transforms.neutralize import NeutralizationRefusal, neutralize

__all__ = (
    "QUANTUM",
    "SHIPPED_COMPLIANCE",
    "AcademicExchange",
    "AccountMode",
    "AccountSnapshot",
    "AllocationInvariants",
    "AllocationSign",
    "AllocationViolation",
    "Budget",
    "CalendarLookback",
    "Compliance",
    "ComplianceCall",
    "ComplianceFinding",
    "ComplianceReport",
    "ComplianceSet",
    "Component",
    "ComponentKind",
    "ComponentRef",
    "CrossSection",
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
    "ExecutionCall",
    "ExecutionFieldRequirement",
    "ExecutionRole",
    "ExecutionTable",
    "ExecutionTableSpec",
    "FactorInstrument",
    "FillCost",
    "FillRule",
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
    "KrxSettings",
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
    # ordering (`docs/issues/archive/031`). `ModelWindow` was importable but undeclared, while the
    # component scaffolds have always emitted `from vqapr.public import ... ModelWindow`.
    "ObservationBatch",
    "OperationOccurrence",
    "OptimizeRefusal",
    "OptimizeResult",
    "PanelWindow",
    "Part",
    "PortfolioDirection",
    "PortfolioTarget",
    "Rebalance",
    "RowsLookback",
    "RunAgenda",
    "RunDefinition",
    "RunExecution",
    "RunFill",
    "RunRecordMissing",
    "RunReport",
    "RunResult",
    "Series",
    "Side",
    "SideCost",
    "SimulationFailure",
    "SimulationResult",
    "SourceSpec",
    "Stage",
    "Status",
    "StockInstrument",
    "StrategyEntry",
    "StrategyModel",
    "StrategyModelContext",
    "StrategyOutcome",
    "StrategyReport",
    "TableSpec",
    "TickerNetting",
    "Tool",
    "TradeRule",
    "TradeTerms",
    "VqaprError",
    "WeightingRefusal",
    "ZeroDealtReason",
    "build_roster",
    "callback_evidence",
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
    "intersect",
    "krx_listings",
    "krx_rules",
    "nav_series",
    "net_members",
    "neutralize",
    "no_short",
    "optimize",
    "preflight_run",
    "proportional_weight",
    "rank",
    "rank_information_coefficient",
    "read_run_record",
    "read_strategy_record",
    "read_strategy_table",
    "register_compliance",
    "register_data_model",
    "register_dataset",
    "register_exchange",
    "register_instruments",
    "register_run",
    "register_strategy_model",
    "rescale",
    "returns",
    "run",
    "run_ids",
    "run_report",
    "shipped_compliance_path",
    "signal_weight",
    "single_name_cap",
    "strategy_refs",
    "strategy_report",
    "trade_rules_by_kind",
    "validate_allocation",
)




def register_run(project_root: str | Path, definition: RunDefinition) -> bool:
    """Register a run: the reusable configuration `vqapr run <run-id>` executes (record `139`)."""
    with Workspace.transaction(project_root) as transaction:
        return transaction.register_run(definition)
