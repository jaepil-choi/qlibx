"""A run's walk: the strategy clock, and the market clock when the run has one.

Both loops of the framework live here, side by side, because the difference between them is the
one design §3 leaves: **how many clocks the run walks.** A `StrategyEventLoop` walks two -- the
frozen agenda where its `StrategyModel` decides, and every instant of the execution table inside
the run, where a pending decision fills, the book is valued and the declared `Compliance` rules
observe it. A `DataModelEventLoop` walks one -- the agenda where its `DataModel` computes -- and
nothing happens between two of its sessions, because a datamodel sees no account and passes
through no venue (architecture 4.4). The walk itself is `flow/engine/loop.py`'s `EventLoop`
(record `182`), shared by both; what each loop adds is its clocks and its handlers.

The handlers are the other modules of this package, one per wiring-table row (design §4,
`domain/wiring.py`): on the strategy clock `callback.py` (decide) and `compute.py` (compute); on
the market clock, in the order §3.1 fixes, `accrual.py`, `execution.py`, `valuation.py` (the
framework's own step) and `compliance.py`. `context.py` is what a strategy run's handlers share;
`output.py` is the warehouse door a datamodel run writes through. Record `147` split the loop
from the work; record `214` put the two kinds' work in one package.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

from vqapr.account.account import Account
from vqapr.account.marking import ValuationService
from vqapr.authoring import AccountHistoryInput, Compliance, Component, DataModel, StrategyModel
from vqapr.data.datasets import DatasetRegistration
from vqapr.data.scan import ScanSession
from vqapr.data.windows import ModelWindow
from vqapr.domain.agendas import OperationOccurrence
from vqapr.domain.instruments import InstrumentRoster
from vqapr.exchange.venue import Exchange
from vqapr.flow.declaration.frozen import FrozenDataModel, FrozenRun, FrozenStrategy
from vqapr.flow.engine.artifacts import (
    FinalizationEvidence,
    SimulationStage,
)
from vqapr.flow.engine.loop import EventLoop, MarketEvent, OccurrenceEvent
from vqapr.flow.engine.run_state import (
    RunFinalization,
    RunStateRepository,
)
from vqapr.flow.run.accrual import AccrualHandler
from vqapr.flow.run.callback import CallbackHandler
from vqapr.flow.run.compliance import ComplianceHandler
from vqapr.flow.run.compute import ComputeHandler, DataModelTrace
from vqapr.flow.run.context import (
    DEFAULT_TABLE_PREFIX,
    DEFAULT_TABLES,
    AcceptedIntent,
    DueExecutionResult,
    DueExecutionTrace,
    FailedAfterCommit,
    FlowContext,
    MarketInstant,
    MonitoringResult,
    OccurrenceTrace,
    SimulationResult,
    ValuationResult,
    _require_compliance_identity,
    callback_evidence,
)
from vqapr.flow.run.execution import ExecutionHandler
from vqapr.flow.run.output import RunOutput
from vqapr.flow.run.valuation import ValuationHandler

__all__ = [
    "DEFAULT_TABLES",
    "DEFAULT_TABLE_PREFIX",
    "AcceptedIntent",
    "DataModelEventLoop",
    "DataModelResult",
    "DueExecutionResult",
    "DueExecutionTrace",
    "FailedAfterCommit",
    "MonitoringResult",
    "OccurrenceTrace",
    "SimulationResult",
    "StrategyEventLoop",
    "ValuationResult",
    "callback_evidence",
]


def _no_compliance_window(instant: datetime) -> ModelWindow:
    raise RuntimeError("a run that declared no Compliance rule never asks for their window")


class StrategyEventLoop(
    EventLoop[
        OccurrenceEvent | MarketEvent, OccurrenceTrace | DueExecutionTrace, SimulationResult
    ]
):
    """Walk two clocks -- the strategy clock and the market clock, merged (design §3).

    The Flow owns timestamp stamping, exact execution, account mutation, and marking. The walk
    itself is `EventLoop`'s, shared with a datamodel run (record `148`); what this adds is the
    market clock -- every instant the execution table has inside the run -- and the handlers:
    a market instant accrues, fills the pending intent due there, values the book and has the
    declared Compliance rules observe it; an occurrence asks the strategy to decide.
    """

    def __init__(
        self,
        frozen_run: FrozenRun,
        strategy: StrategyModel,
        state: RunStateRepository,
        *,
        layer: FrozenStrategy | None = None,
        strategy_window_for_occurrence: Callable[[OperationOccurrence], ModelWindow],
        account: Account,
        compliance_window_at: Callable[[datetime], ModelWindow] | None = None,
        exchange: Exchange,
        compliance: tuple[Compliance, ...] = (),
        valuation_service: ValuationService | None = None,
        scan_session: ScanSession | None = None,
        on_progress: Callable[[], None] | None = None,
        registry: InstrumentRoster | None = None,
        record_account_positions: bool = True,
    ) -> None:
        # A run runs ONE strategy (2026-09-09,
        # `docs/design/two-clocks-and-the-wiring-table.md` §2.3), so `layer` is a courtesy the
        # caller may pass and never a choice: the run holds the answer.
        if layer is None:
            layer = frozen_run.strategy
        if layer is None or layer is not frozen_run.strategy:
            raise ValueError("layer must be the frozen run's strategy")
        if not callable(strategy_window_for_occurrence):
            raise TypeError("strategy_window_for_occurrence must be callable")
        if compliance and not callable(compliance_window_at):
            raise TypeError("compliance_window_at must be callable when rules are loaded")
        if not callable(getattr(exchange, "execute", None)):
            raise TypeError("exchange must provide execute")
        _require_compliance_identity(compliance, layer.compliance.rules)
        cutoff = frozen_run.start or frozen_run.end
        if cutoff is None:
            raise RuntimeError("simulation start requires a frozen boundary")
        requirements = tuple(getattr(exchange, "execution_requirements", tuple)())
        prices = {requirement.price for requirement in requirements}
        if len(prices) > 1:
            raise ValueError("an Exchange may require at most one reference execution price")
        declared_history = strategy.account_history()
        if declared_history is not None and not isinstance(declared_history, AccountHistoryInput):
            raise TypeError("account_history must return an AccountHistoryInput or None")
        initial = state.current.account
        if initial is None:
            raise ValueError("state must begin with the frozen AccountState root")
        if frozen_run.initial_account_snapshot != initial.snapshot:
            raise ValueError("state AccountState must match FrozenRun initial account snapshot")
        if frozen_run.initial_account_mode != account.mode:
            raise ValueError("Account mode must match FrozenRun initial account mode")
        carried = set(state.current.component_state_refs)
        stateful = {rule.compliance_id for rule in compliance}
        if isinstance(exchange, Component):
            stateful.add(exchange.exchange_id)
        if carried != stateful:
            raise ValueError(
                "state must carry the initial memory of exactly the loaded components -- every "
                "compliance rule, and the venue when it is a Component (RunStateRepository "
                f"initial_component_memory): carrying {sorted(carried)!r}, loaded "
                f"{sorted(stateful)!r}"
            )

        # All handler dependencies exist before the first handler is constructed. The loop owns
        # its schedule and progress hook; the context owns this strategy's runtime and bookkeeping.
        super().__init__(
            schedule=frozen_run.dispatch_order(layer), start_cutoff=cutoff, on_progress=on_progress
        )
        self._context = FlowContext(
            frozen_run=frozen_run,
            layer=layer,
            state=state,
            account=account,
            exchange=exchange,
            strategy=strategy,
            compliance=compliance,
            valuation_service=valuation_service or ValuationService(),
            strategy_window_for_occurrence=strategy_window_for_occurrence,
            compliance_window_at=compliance_window_at or _no_compliance_window,
            scan_session=scan_session,
            registry=registry,
            reference_price=next(iter(prices), None),
            record_account_positions=record_account_positions,
            account_history_declaration=declared_history,
        )
        self._accrual = AccrualHandler(self._context)
        self._valuation = ValuationHandler(self._context)
        self._compliance = ComplianceHandler(self._context)
        self._callback = CallbackHandler(self._context)
        self._execution = ExecutionHandler(self._context)
        account.bind(initial)

    def run(self) -> SimulationResult:
        """Synchronously process the static merge and all due items in its horizon."""
        started = time.perf_counter()
        result = super().run()
        # The phases the context accumulated, plus the whole: what the record reports as `timing`
        # (`docs/issues/archive/068`). `total` covers the loop itself; the panel build and the
        # record freeze happen outside it and are the caller's to time.
        timing = {**self._context.timing, "total": time.perf_counter() - started}
        return replace(result, timing=timing)

    def start(self, cutoff: datetime) -> None:
        with self._context.guard(
            SimulationStage.START,
            cutoff,
            owner=self._context.layer.config,
        ):
            self._callback.load_visible_state()

    def events(self) -> tuple[OccurrenceEvent | MarketEvent, ...]:
        """The strategy clock merged with the market clock (design §3).

        The market clock is every instant the execution table has inside `[start, end]`, read
        once through the run's horizon -- the same read the fill rule bisects, so the instants a
        decision can fill at and the instants the book is valued at are one set. A run declared
        without execution authority has no market clock and is the plain sequence of decisions.
        """
        occurrences: tuple[OccurrenceEvent | MarketEvent, ...] = tuple(
            OccurrenceEvent(item) for item in self.schedule
        )
        execution_table = self._context.frozen_run.execution
        if execution_table is None:
            return occurrences
        horizon = self._callback.execution_horizon(execution_table)
        return (*occurrences, *(MarketEvent(instant) for instant in horizon.instants))

    def handle(
        self, event: OccurrenceEvent | MarketEvent
    ) -> OccurrenceTrace | DueExecutionTrace:
        if isinstance(event, MarketEvent):
            return self._handle_market(event)
        # A scheduled event is a callback, always (record `182`: an occurrence carries no role to
        # branch on). `callback` is the whole scheduled side: the window built for the model and
        # the model's own `decide` (`docs/issues/archive/068`: a user learns their strategy is 5%
        # of the wall clock from the record, not from cProfile).
        with self._context.timed("callback"):
            return self._callback.dispatch(event.occurrence)

    def _handle_market(self, event: MarketEvent) -> DueExecutionTrace:
        """One instant of the market clock, in the order design §3.1 fixes -- written once, here,
        and held to `domain.wiring.MARKET_CLOCK_ORDER` by the wiring test.

            1. ACCRUE      what the holding period up to now earned         (a place, for now)
            2. EXECUTE     the pending intent whose target is this instant  (when there is one)
            3. VALUATION   the committed book, from the fill's snapshot or a fresh one
            4. COMPLIANCE  the declared Compliance rules observe the committed, marked book
            (5. DECIDE     a decision at this same instant is a separate event, sorted after)

        A pending intent whose target has already passed is a broken invariant, not a late fill:
        targets are selected from this same clock, so the instant was walked.
        """
        instant = event.instant
        with (
            self._context.timed("due"),
            self._context.guard(
                SimulationStage.DUE_SNAPSHOT, instant, owner=self._context.frozen_run.execution
            ),
        ):
            pending = self._context.state.current.pending_accepted_intent
            if pending is not None and not isinstance(pending, AcceptedIntent):
                raise TypeError("run state pending must be an AcceptedIntent")
            if pending is not None and pending.target.target_at < instant:
                raise RuntimeError("a pending intent's target instant was never walked")
            due = pending if pending is not None and pending.target.target_at == instant else None

            # The fold (record `226`): every stage takes the instant as the stages before it
            # left it and returns it with its own field set. The order is these five lines.
            at = MarketInstant(at=instant, due=due)
            at = self._accrual.accrue(at)
            at = self._execution.fill(at)
            at = self._valuation.mark(at)
            at = self._compliance.observe(at)
            at = self._execution.close(at)
            if at.result is None:
                raise RuntimeError("a market-clock instant closed without a result")
            return DueExecutionTrace(event, at.result, self._context.state.current.version)

    def finish(self, traces: tuple[OccurrenceTrace | DueExecutionTrace, ...]) -> SimulationResult:
        if self._context.state.current.pending_accepted_intent is not None:
            raise RuntimeError("simulation finalized with a pending accepted intent")
        if self._context.frozen_run.end is None:
            raise RuntimeError("simulation finalization requires a frozen end")
        account = self._context.state.current.account
        finalization = FinalizationEvidence(
            run_identity=self._context.frozen_run.identity,
            strategy_agenda=self._context.layer.agenda,
            root_version=self._context.state.current.version,
            cutoff=self._context.frozen_run.end,
            account=None if account is None else account.snapshot,
        )
        with self._context.guard(
            SimulationStage.FINALIZE,
            self._context.frozen_run.end,
            owner=finalization,
        ):
            root = self._context.state.finalize(RunFinalization(finalization))
        return SimulationResult(tuple(traces), root)


@dataclass(frozen=True, slots=True)
class DataModelResult:
    """A finished datamodel run: one trace per session, and the dataset it registered."""

    occurrences: tuple[DataModelTrace, ...]
    rows: int
    output_path: Path
    registration: DatasetRegistration | None = None


class DataModelEventLoop(EventLoop[OccurrenceEvent, DataModelTrace, DataModelResult]):
    """Walk one clock: the datamodel's sessions -- compute at each, chunk the rows, register at
    the end.

    No market clock: a datamodel sees no account and passes through no venue (architecture 4.4),
    so nothing happens between two sessions and the walk is the plain sequence of occurrences
    (`EventLoop.events`'s default). What it shares with `StrategyEventLoop` is everything else.
    """

    def __init__(
        self,
        frozen_run: FrozenRun,
        layer: FrozenDataModel,
        model: DataModel,
        *,
        window_for_occurrence: Callable[[OperationOccurrence], ModelWindow],
        output: RunOutput,
        on_progress: Callable[[], None] | None = None,
    ) -> None:
        if layer is not frozen_run.datamodel:
            raise ValueError("layer must be the frozen run's datamodel")
        if not callable(window_for_occurrence):
            raise TypeError("window_for_occurrence must be callable")
        cutoff = frozen_run.start or frozen_run.end
        if cutoff is None:
            raise RuntimeError("a datamodel run requires a frozen boundary")
        super().__init__(
            schedule=frozen_run.dispatch_order(layer), start_cutoff=cutoff, on_progress=on_progress
        )
        self._output = output
        self._phase = ComputeHandler(
            frozen_run=frozen_run,
            layer=layer,
            model=model,
            window_for_occurrence=window_for_occurrence,
            output=output,
        )

    def start(self, cutoff: datetime) -> None:
        self._output.open()

    def handle(self, event: OccurrenceEvent) -> DataModelTrace:
        return self._phase.dispatch(event.occurrence)

    def finish(self, traces: tuple[DataModelTrace, ...]) -> DataModelResult:
        return DataModelResult(
            occurrences=traces,
            rows=self._output.rows,
            output_path=self._output.directory,
        )
