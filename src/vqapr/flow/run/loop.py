"""One loop walks both kinds of run: a part on the strategy clock, tools on the market clock.

Design §3 leaves one difference between a strategy run and a datamodel run -- how many clocks it
walks -- and until record `227` that difference was two loop classes side by side (record `214`
put them in one file and stopped there: *"folding them into one class is a spine change"*). The
spine was that each loop stood on its own receiver, `RunStateRepository` for a strategy and
`RunOutput` for a datamodel. `RunLoop` does not stand on either. It walks the merged clocks and
hands each event to one of two things:

    the part      `Part.dispatch(occurrence)`   the strategy clock: `StrategyModel.decide` or
                                                `DataModel.compute`, and what follows the answer
    the market    `MarketClock.at(event)`        the market clock: ACCRUE -> EXECUTE -> VALUATION ->
                                                COMPLIANCE -> close, the fold of record `226`

A part owns its receiver and its opening and closing (`start`, `finish`); a datamodel run simply
has no market clock. The walk -- start, the events sorted, one `handle` each, finish -- is
`RunLoop.run`, written once; until record `231` it sat in an abstract `EventLoop` whose only
subclass was this class (`docs/issues/097`). The two kinds are assembled by two functions,
`strategy_loop` and `datamodel_loop`: that is where a run's authorities are checked against each
other and its handlers built, and what they return is a `RunLoop` and nothing more specific.

The handlers are the other modules of this package, one per wiring-table row (design §4,
`domain/wiring.py`): on the strategy clock `callback.py` (decide) and `compute.py` (compute); on
the market clock, in the order §3.1 fixes, `accrual.py`, `execution.py`, `valuation.py` (the
framework's own step) and `compliance.py`. `context.py` is what a strategy run's handlers share;
`output.py` is the warehouse door a datamodel run writes through.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from vqapr.component.base import Component
from vqapr.component.compliance.base import Compliance
from vqapr.component.datamodel import DataModel
from vqapr.component.exchange.base import Exchange
from vqapr.component.strategy.base import StrategyModel
from vqapr.component.strategy.history import AccountHistoryInput
from vqapr.data.dataset import DatasetRegistration
from vqapr.data.scan import ScanSession
from vqapr.data.window import ModelWindow
from vqapr.domain.account import Account
from vqapr.domain.fill import ExecutionHorizon
from vqapr.domain.instants import require_tz_aware
from vqapr.domain.instrument import InstrumentRoster
from vqapr.domain.schedule import OperationOccurrence
from vqapr.domain.valuation import ValuationService
from vqapr.flow.declaration.frozen import FrozenDataModel, FrozenRun, FrozenStrategy
from vqapr.flow.engine.artifacts import (
    FinalizationEvidence,
    SimulationStage,
)
from vqapr.flow.engine.loop import MarketEvent, OccurrenceEvent
from vqapr.flow.engine.run_state import RunFinalization, RunStateRepository
from vqapr.flow.run.accrual import AccrualHandler
from vqapr.flow.run.callback import CallbackHandler
from vqapr.flow.run.compliance import ComplianceHandler
from vqapr.flow.run.compute import ComputeHandler, DataModelTrace
from vqapr.flow.run.context import (
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
from vqapr.record.schema import DEFAULT_TABLE_PREFIX

__all__ = [
    "DEFAULT_TABLES",
    "DEFAULT_TABLE_PREFIX",
    "AcceptedIntent",
    "DataModelPart",
    "DataModelResult",
    "DueExecutionResult",
    "DueExecutionTrace",
    "FailedAfterCommit",
    "MarketClock",
    "MonitoringResult",
    "OccurrenceTrace",
    "Part",
    "RunLoop",
    "SimulationResult",
    "StrategyPart",
    "ValuationResult",
    "callback_evidence",
    "datamodel_loop",
    "strategy_loop",
]


def _no_compliance_window(instant: datetime) -> ModelWindow:
    raise RuntimeError("a run that declared no Compliance rule never asks for their window")


class Part[TraceT, ResultT](Protocol):
    """What the strategy clock calls, and what opens and closes the run: the part's own side.

    A part declares the run's clock (design §4.3) and owns the receiver its answers go to -- the
    run state for a strategy, the warehouse door for a datamodel. The loop knows neither; it
    knows that a part starts, is dispatched once per occurrence, and finishes with the traces.
    """

    def start(self, cutoff: datetime) -> None: ...

    def dispatch(self, occurrence: OperationOccurrence) -> TraceT: ...

    def finish(
        self, traces: tuple[TraceT | DueExecutionTrace, ...], *, elapsed: float
    ) -> ResultT: ...


class MarketClock:
    """The market clock of a strategy run: its instants, and what happens at each.

    The instants are every row-instant the execution table has inside the run, read once
    through the horizon (the same read the fill rule bisects, so the instants a decision can
    fill at and the instants the book is valued at are one set). What happens at one is the
    fold of record `226`, in the order design §3.1 fixes and `domain.wiring.MARKET_CLOCK_ORDER`
    states -- written once, in `at`, and held to the table by the wiring test.
    """

    def __init__(
        self,
        context: FlowContext,
        *,
        accrual: AccrualHandler,
        execution: ExecutionHandler,
        valuation: ValuationHandler,
        compliance: ComplianceHandler,
        callback: CallbackHandler,
    ) -> None:
        self._context = context
        self._accrual = accrual
        self._execution = execution
        self._valuation = valuation
        self._compliance = compliance
        self._callback = callback

    def instants(self) -> tuple[datetime, ...]:
        """Every instant of the clock inside the run; none for a run without execution authority.

        Read lazily, so building a loop still opens no physical source.
        """
        execution_table = self._context.frozen_run.execution
        if execution_table is None:
            return ()
        return self._callback.execution_horizon(execution_table).instants

    def at(self, event: MarketEvent) -> DueExecutionTrace:
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
            # A run with a record keeps the instant's outcome, not its evidence (record `256`).
            kept = at.result if self._context.state.keeps_evidence else at.result.outcome()
            return DueExecutionTrace(event, kept, self._context.state.current.version)


class RunLoop[TraceT, ResultT]:
    """The one loop: a part on the strategy clock, and a market clock when the run has one.

    Three sentences say all of it. The walk is `run`: start, the events sorted by clock, one
    `handle` each, finish -- written once and not overridable, because the merge order is what
    makes two runs of the same frozen inputs produce the same traces (architecture 3.2). A
    scheduled event is the part's (`StrategyModel.decide` or `DataModel.compute`); a market event
    is the market clock's fold. Whether the run is a strategy or a datamodel is decided by what
    `strategy_loop`/`datamodel_loop` assembled here, and nowhere below: the loop knows nothing of
    accounts, venues, warehouses or records.
    """

    def __init__(
        self,
        *,
        schedule: Sequence[OperationOccurrence],
        start_cutoff: datetime,
        part: Part[TraceT, ResultT],
        market: MarketClock | None = None,
        on_progress: Callable[[], None] | None = None,
    ) -> None:
        require_tz_aware(start_cutoff, name="start_cutoff")
        if on_progress is not None and not callable(on_progress):
            raise TypeError("on_progress must be callable or None")
        self._schedule = tuple(schedule)
        self._start_cutoff = start_cutoff
        self._on_progress = on_progress
        self._part = part
        self._market = market
        self._started = 0.0

    @property
    def schedule(self) -> tuple[OperationOccurrence, ...]:
        """The strategy-clock events, in dispatch order."""
        return self._schedule

    @property
    def part(self) -> Part[TraceT, ResultT]:
        """The part this loop dispatches to; a test that injects a fault into it reaches it here."""
        return self._part

    def run(self) -> ResultT:
        """Synchronously process every event of the walk."""
        self.start(self._start_cutoff)
        traces: list[TraceT | DueExecutionTrace] = []
        for event in sorted(self.events(), key=lambda item: item.sort_key()):
            # One call per event, for a caller that needs to prove it is still alive while the
            # run is executing. A run's only other outward sign is its result, which arrives
            # minutes later -- long after anything watching would have concluded it had died.
            if self._on_progress is not None:
                self._on_progress()
            traces.append(self.handle(event))
        return self.finish(tuple(traces))

    def start(self, cutoff: datetime) -> None:
        self._started = time.perf_counter()
        self._part.start(cutoff)

    def events(self) -> tuple[OccurrenceEvent | MarketEvent, ...]:
        """The strategy clock, merged with the market clock when the run has one (design §3)."""
        occurrences: tuple[OccurrenceEvent | MarketEvent, ...] = tuple(
            OccurrenceEvent(item) for item in self._schedule
        )
        if self._market is None:
            return occurrences
        return (*occurrences, *(MarketEvent(instant) for instant in self._market.instants()))

    def handle(self, event: OccurrenceEvent | MarketEvent) -> TraceT | DueExecutionTrace:
        if isinstance(event, MarketEvent):
            if self._market is None:
                raise RuntimeError("a market-clock event reached a run without a market clock")
            return self._market.at(event)
        # A scheduled event is the part's, always (record `182`: an occurrence carries no role to
        # branch on).
        return self._part.dispatch(event.occurrence)

    def finish(self, traces: tuple[TraceT | DueExecutionTrace, ...]) -> ResultT:
        # `elapsed` covers the loop itself; the panel build and the record freeze happen outside
        # it and are the caller's to time (`docs/issues/archive/068`).
        return self._part.finish(traces, elapsed=time.perf_counter() - self._started)


class StrategyPart:
    """The strategy clock's side of a strategy run: the callback and the state it publishes to."""

    def __init__(self, context: FlowContext, callback: CallbackHandler) -> None:
        self._context = context
        # Public by name: a test that injects a fault into the callback reaches it here.
        self.callback = callback

    def start(self, cutoff: datetime) -> None:
        with self._context.guard(
            SimulationStage.START,
            cutoff,
            owner=self._context.layer.config,
        ):
            self.callback.load_visible_state()

    def dispatch(self, occurrence: OperationOccurrence) -> OccurrenceTrace:
        # `callback` is the whole scheduled side: the window built for the model and the model's
        # own `decide` (`docs/issues/archive/068`: a user learns their strategy is 5% of the wall
        # clock from the record, not from cProfile).
        with self._context.timed("callback"):
            return self.callback.dispatch(occurrence)

    def finish(
        self, traces: tuple[OccurrenceTrace | DueExecutionTrace, ...], *, elapsed: float
    ) -> SimulationResult:
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
        # The phases the context accumulated, plus the whole: what the record reports as `timing`.
        timing = {**self._context.timing, "total": elapsed}
        return SimulationResult(tuple(traces), root, timing)


def strategy_loop(
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
    horizon: ExecutionHorizon | None = None,
) -> RunLoop[OccurrenceTrace, SimulationResult]:
    """A strategy run, assembled: two clocks -- the strategy's agenda and the market's instants.

    The Flow owns timestamp stamping, exact execution, account mutation, and marking. This is
    where a strategy run's authorities are checked against each other and its handlers built;
    the walk is `RunLoop`'s. A function, not a subclass: what it returns differs from a datamodel
    run only in what was assembled (`docs/issues/097`).
    """
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

    # All handler dependencies exist before the first handler is constructed. The context
    # owns this strategy's runtime and bookkeeping; the loop owns the walk.
    context = FlowContext(
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
        # The execution horizon the verification already cut (record `242`), or `None` and
        # the callback reads it once on the first accepted intent (record `162`).
        horizon=horizon,
    )
    callback = CallbackHandler(context)
    loop = RunLoop(
        schedule=frozen_run.dispatch_order(layer),
        start_cutoff=cutoff,
        part=StrategyPart(context, callback),
        market=MarketClock(
            context,
            accrual=AccrualHandler(context),
            execution=ExecutionHandler(context),
            valuation=ValuationHandler(context),
            compliance=ComplianceHandler(context),
            callback=callback,
        ),
        on_progress=on_progress,
    )
    account.bind(initial)
    return loop


@dataclass(frozen=True, slots=True)
class DataModelResult:
    """A finished datamodel run: one trace per session, and the dataset it registered."""

    occurrences: tuple[DataModelTrace, ...]
    rows: int
    output_path: Path
    registration: DatasetRegistration | None = None


class DataModelPart:
    """The datamodel's side of its run: compute at each session, and the warehouse door."""

    def __init__(self, compute: ComputeHandler, output: RunOutput) -> None:
        self._compute = compute
        self._output = output

    def start(self, cutoff: datetime) -> None:
        self._output.open()

    def dispatch(self, occurrence: OperationOccurrence) -> DataModelTrace:
        return self._compute.dispatch(occurrence)

    def finish(
        self, traces: tuple[DataModelTrace | DueExecutionTrace, ...], *, elapsed: float
    ) -> DataModelResult:
        sessions = tuple(trace for trace in traces if isinstance(trace, DataModelTrace))
        return DataModelResult(
            occurrences=sessions,
            rows=self._output.rows,
            output_path=self._output.directory,
        )


def datamodel_loop(
    frozen_run: FrozenRun,
    layer: FrozenDataModel,
    model: DataModel,
    *,
    window_for_occurrence: Callable[[OperationOccurrence], ModelWindow],
    output: RunOutput,
    on_progress: Callable[[], None] | None = None,
) -> RunLoop[DataModelTrace, DataModelResult]:
    """A datamodel run, assembled: one clock, the agenda where its `DataModel` computes.

    No market clock: a datamodel sees no account and passes through no venue (architecture
    4.4), so nothing happens between two sessions and the walk is the plain sequence of
    occurrences. What it shares with a strategy run is everything else -- the same `RunLoop`.
    """
    if layer is not frozen_run.datamodel:
        raise ValueError("layer must be the frozen run's datamodel")
    if not callable(window_for_occurrence):
        raise TypeError("window_for_occurrence must be callable")
    cutoff = frozen_run.start or frozen_run.end
    if cutoff is None:
        raise RuntimeError("a datamodel run requires a frozen boundary")
    compute = ComputeHandler(
        frozen_run=frozen_run,
        layer=layer,
        model=model,
        window_for_occurrence=window_for_occurrence,
        output=output,
    )
    return RunLoop(
        schedule=frozen_run.dispatch_order(layer),
        start_cutoff=cutoff,
        part=DataModelPart(compute, output),
        on_progress=on_progress,
    )
