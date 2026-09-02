"""Register the sample panel and run it end to end.

The point of the sample is that it executes. A reader can run this once and see a real result
before writing anything, and the panel it runs on is deliberately unbalanced so the result also
shows what happens when an instrument lists late or stops trading mid-run.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path

from vqapr.agent.sample.build import SamplePanel, build
from vqapr.extension.fingerprint import fingerprint_component
from vqapr.public import (
    AccountMode,
    AccountSnapshot,
    ComponentKind,
    ComponentRef,
    ConstraintSet,
    DatasetRegistration,
    ExecutionInputRegistration,
    ExecutionTableSpec,
    FillConvention,
    FillSelector,
    LocalInstantDeclaration,
    MonitoringPolicy,
    OperationAgenda,
    OperationOccurrence,
    OperationRole,
    RunDefinition,
    SourceSpec,
    StrategyConfig,
    ValuationConfig,
    Workspace,
    preflight_run,
    register_agenda,
    register_component,
    register_dataset,
    register_execution_input,
    register_monitoring_policy,
    register_strategy_config,
    register_strategy_model,
    register_valuation_config,
    run,
)

VENUE = "Asia/Seoul"
OFFSET = "+09:00"

CALLBACK = time(8, 0)
"""The decision is made before the session opens, reading only closes already published."""
CLOSE = time(15, 30)
"""The fill happens at the close, after the decision, never at the same instant."""
VALUATION = time(16, 0)
MONITORING = time(16, 30)

DATASET_ID = "sample-prices"
EXECUTION_ID = "sample-execution"
STRATEGY_ID = "sample-reversal-5d"
EXCHANGE_ID = "sample-exchange"
STRATEGY_AGENDA = "sample-callback"
VALUATION_AGENDA = "sample-valuation"
MONITORING_AGENDA = "sample-monitoring"

STRATEGY_SOURCE = Path(__file__).with_name("reversal_5d.py")
EXCHANGE_SOURCE = Path(__file__).with_name("exchange.py")

OPENING_CASH = Decimal("100000000")
"""The book starts in cash, so the first rebalance is a plain set of purchases."""


@dataclass(frozen=True, slots=True)
class SampleResult:
    panel: SamplePanel
    occurrences: int
    run_state_version: int
    """How many times the run published state, which is not the Account's version.

    These were conflated while every state publication came from a callback. They are two
    different counters: the Account advances only when a fill commits, while the run state also
    advances when a valuation records a mark without trading. Naming this one for the Account
    made a valuation-clock change look like an accounting change.
    """

    account_version: int


def _sessions(panel: SamplePanel) -> list[date]:
    return [date(int(v[:4]), int(v[4:6]), int(v[6:8])) for v in panel.sessions]


def _agenda(
    agenda_id: str, role: OperationRole, at: time, days: list[date]
) -> OperationAgenda:
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
        provenance="vqapr sample panel sessions",
    )


def _valuation() -> ValuationConfig:
    return ValuationConfig(
        VALUATION_AGENDA,
        OperationRole.VALUATION,
    )


def _strategy(project_root: Path) -> StrategyConfig:
    return StrategyConfig(
        component=Workspace.open(project_root).component(STRATEGY_ID),
        agenda_id=STRATEGY_AGENDA,
        agenda_role=OperationRole.STRATEGY_CALLBACK,
    )


def install(project_root: Path) -> SamplePanel:
    """Create the panel and register every declaration a run needs."""
    panel = build(project_root)
    register_dataset(
        project_root,
        DatasetRegistration.of(
            DATASET_ID,
            "sample-prices-source",
            instrument_field="instrument",
            available_at="available_at",
            grain="instrument_instant",
            key_fields=("available_at", "instrument"),
            fields={name: name for name in ("open", "high", "low", "close", "volume")},
        ),
        SourceSpec.of("sample-prices-source", panel.observations),
    )
    register_execution_input(
        project_root,
        ExecutionInputRegistration.of(
            EXECUTION_ID,
            ExecutionTableSpec(
                source=SourceSpec.of("sample-execution-source", panel.execution),
                trade_at_field="trade_at",
                instrument_field="instrument",
                is_tradable_field="is_tradable",
                price_fields={"close": "close"},
            ),
            FillConvention(FillSelector.SAME_DAY, CLOSE, VENUE, "close"),
        ),
    )
    register_strategy_model(project_root, STRATEGY_ID, STRATEGY_SOURCE, "SampleReversal5d")
    register_component(
        project_root,
        ComponentRef.of(
            EXCHANGE_ID,
            ComponentKind.EXCHANGE,
            EXCHANGE_SOURCE,
            "SampleExchange",
            config={"instruments": list(panel.instruments)},
            fingerprint=fingerprint_component(
                EXCHANGE_SOURCE,
                kind=ComponentKind.EXCHANGE,
                object_name="SampleExchange",
                config={"instruments": list(panel.instruments)},
            ),
        ),
    )

    sessions = _sessions(panel)
    for agenda_id, role, at in (
        (STRATEGY_AGENDA, OperationRole.STRATEGY_CALLBACK, CALLBACK),
        (VALUATION_AGENDA, OperationRole.VALUATION, VALUATION),
        (MONITORING_AGENDA, OperationRole.MONITORING, MONITORING),
    ):
        register_agenda(project_root, _agenda(agenda_id, role, at, sessions))

    register_strategy_config(project_root, _strategy(project_root))
    register_valuation_config(project_root, _valuation())
    register_monitoring_policy(
        project_root, MonitoringPolicy(MONITORING_AGENDA, OperationRole.MONITORING)
    )
    return panel


def execute(project_root: Path, panel: SamplePanel) -> SampleResult:
    """Freeze the registered declarations and run them."""
    sessions = _sessions(panel)
    definition = RunDefinition(
        strategy=_strategy(project_root),
        valuation=_valuation(),
        constraints=ConstraintSet(()),
        monitoring=MonitoringPolicy(MONITORING_AGENDA, OperationRole.MONITORING),
        exchange=Workspace.open(project_root).component(EXCHANGE_ID),
        execution_input_id=EXECUTION_ID,
        start=datetime.fromisoformat(f"{sessions[0].isoformat()}T00:00:00{OFFSET}"),
        end=datetime.fromisoformat(f"{sessions[-1].isoformat()}T23:59:59{OFFSET}"),
        initial_account_snapshot=AccountSnapshot(version=0, cash=OPENING_CASH, positions={}),
        initial_account_mode=AccountMode.LONG_ONLY,
        instruments=panel.instruments,
    )
    result = run(project_root, preflight_run(project_root, definition))
    return SampleResult(
        panel,
        len(result.occurrences),
        result.final_state.version,
        result.final_state.account.snapshot.version,
    )


__all__ = ["SampleResult", "execute", "install"]
