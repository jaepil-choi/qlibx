"""Deterministic next-session-close simulation flow."""

import hashlib
import math
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import Field, model_validator

from qlibx.account import (
    Account,
    AccountCheckpoint,
    AccountCommitRejected,
    AccountSnapshot,
    FillBatch,
    Mark,
    MarkBatch,
    MemorySnapshot,
    StrategyMemoryStore,
)
from qlibx.context import StateAccessRecord, StateHolding, ViewGate
from qlibx.data import (
    ComponentRequirement,
    ObservationStore,
    RegistrySnapshot,
    RequirementResolver,
)
from qlibx.domain import Fill, Side
from qlibx.errors import CommitStatus, OperationError, OperationOutcome, OutcomeStatus
from qlibx.evidence import (
    ArtifactContract,
    ArtifactEnvelope,
    DependencyEdge,
    LocalArtifactBackend,
)
from qlibx.execution import FillDiagnostic, KrxExchange, MarketQuote, Order
from qlibx.flow.recovery import (
    SIMULATION_RECOVERY_POINT_CONTRACT,
    PendingExecutionRecovery,
    RecoveryPublication,
    SimulationRecoveryPoint,
)
from qlibx.flow.research import ResearchFlow, StrategyRunResult
from qlibx.kernel import BacktestClock, Event
from qlibx.kernel.clock import require_aware
from qlibx.models import QlibxModel
from qlibx.operations import (
    DecisionAction,
    StrategyInvocation,
    StrategyOperation,
    StrategyResult,
)

DECISION_PRIORITY = 0
EXECUTION_PRIORITY = 10
MARK_PRIORITY = 20
MONITOR_PRIORITY = 30


class DecisionTarget(QlibxModel):
    instrument_id: str = Field(min_length=1)
    weight: float = Field(ge=0)


class DecisionIntent(QlibxModel):
    intent_schema_version: int = 1
    decision_id: str = Field(min_length=1)
    strategy_id: str = Field(min_length=1)
    strategy_artifact_id: str = Field(min_length=1)
    decision_time: datetime
    account_id: str = Field(min_length=1)
    account_version: int = Field(ge=0)
    feedback_cursor: int = Field(ge=0)
    targets: tuple[DecisionTarget, ...]

    @model_validator(mode="after")
    def validate_targets(self) -> "DecisionIntent":
        instruments = [target.instrument_id for target in self.targets]
        if len(instruments) != len(set(instruments)):
            raise ValueError("decision targets must have unique instruments")
        if sum(target.weight for target in self.targets) > 1 + 1e-10:
            raise ValueError("daily physical targets cannot exceed long-only capital")
        return self


class OrderEvidence(QlibxModel):
    instrument_id: str
    side: Side
    quantity: float


class FillEvidence(QlibxModel):
    fill_id: str
    instrument_id: str
    side: Side
    requested_quantity: float
    dealt_quantity: float
    price: float
    trade_value: float
    total_cost: float
    cost_rule_id: str
    schedule_version: str
    reference_price: float | None = None
    price_impact_rate: float = Field(default=0, ge=0)


class FillDiagnosticEvidence(QlibxModel):
    instrument_id: str
    requested_quantity: float
    dealt_quantity: float
    reasons: tuple[str, ...]


class ExecutionEvidence(QlibxModel):
    execution_schema_version: int = 1
    event_id: str
    decision_id: str
    event_time: datetime
    profile_id: str
    convention_id: str
    sizing_nav: float
    sizing_price_role: str
    orders: tuple[OrderEvidence, ...]
    fills: tuple[FillEvidence, ...]
    diagnostics: tuple[FillDiagnosticEvidence, ...]
    account_before: StateAccessRecord
    account_after: StateAccessRecord
    limitations: tuple[str, ...]


class MarkEvidence(QlibxModel):
    event_id: str
    event_time: datetime
    marks: tuple[tuple[str, float], ...]
    account_before: StateAccessRecord
    account_after: StateAccessRecord


class SessionPerformanceEvidence(QlibxModel):
    performance_schema_version: Literal[1] = 1
    event_id: str
    event_time: datetime
    account_id: str
    source_mark_event_id: str
    source_execution_event_ids: tuple[str, ...]
    opening_account_version: int = Field(ge=0)
    closing_account_version: int = Field(ge=0)
    feedback_cursor: int = Field(ge=0)
    opening_nav: float = Field(ge=0)
    closing_nav: float = Field(ge=0)
    closing_cash: float
    trade_value: float = Field(ge=0)
    transaction_cost: float = Field(ge=0)
    turnover: float | None
    transaction_cost_rate: float | None
    gross_return: float | None
    portfolio_return: float | None

    @model_validator(mode="after")
    def validate_reconciliation(self) -> "SessionPerformanceEvidence":
        ratios = (
            self.turnover,
            self.transaction_cost_rate,
            self.gross_return,
            self.portfolio_return,
        )
        if self.opening_nav == 0:
            if any(value is not None for value in ratios):
                raise ValueError("zero opening NAV requires undefined return ratios")
            return self
        if any(value is None or not math.isfinite(value) for value in ratios):
            raise ValueError("positive opening NAV requires finite return ratios")
        expected_net = self.closing_nav / self.opening_nav - 1
        expected_cost = self.transaction_cost / self.opening_nav
        expected_turnover = self.trade_value / self.opening_nav
        assert self.portfolio_return is not None
        assert self.transaction_cost_rate is not None
        assert self.gross_return is not None
        assert self.turnover is not None
        if not math.isclose(self.portfolio_return, expected_net, rel_tol=0, abs_tol=1e-12):
            raise ValueError("portfolio return does not reconcile to NAV")
        if not math.isclose(
            self.transaction_cost_rate,
            expected_cost,
            rel_tol=0,
            abs_tol=1e-12,
        ):
            raise ValueError("transaction cost rate does not reconcile")
        if not math.isclose(self.turnover, expected_turnover, rel_tol=0, abs_tol=1e-12):
            raise ValueError("turnover does not reconcile")
        if not math.isclose(
            self.gross_return - self.transaction_cost_rate,
            self.portfolio_return,
            rel_tol=0,
            abs_tol=1e-12,
        ):
            raise ValueError("gross and net return do not reconcile")
        return self


class MonitorEvidence(QlibxModel):
    event_id: str
    event_time: datetime
    account: StateAccessRecord
    account_version_after_callback: int = Field(ge=0)


class MemoryCommitEvidence(QlibxModel):
    strategy_id: str
    source_artifact_id: str
    previous_version: int = Field(ge=0)
    version: int = Field(ge=0)
    feedback_cursor: int = Field(ge=0)
    update_kind: Literal["INITIALIZATION", "FEEDBACK_UPDATE"]
    value: dict[str, object]


class SimulationCheckpoint(QlibxModel):
    checkpoint_schema_version: Literal[2] = 2
    run_id: str
    request_fingerprint: str
    config_fingerprint: str
    profile_fingerprint: str
    registry_fingerprint: str
    strategy_id: str | None
    event_time: datetime
    account: StateAccessRecord
    account_checkpoint: AccountCheckpoint
    memory_snapshots: tuple[MemorySnapshot, ...] = ()
    event_trace: tuple[str, ...]
    completed_decision_ids: tuple[str, ...]


DECISION_INTENT_CONTRACT = ArtifactContract(
    artifact_type="decision_intent",
    artifact_schema_version=1,
    payload_model=DecisionIntent,
)

STRATEGY_RESULT_RECOVERY_CONTRACT = ArtifactContract(
    artifact_type="strategy_result",
    artifact_schema_version=1,
    payload_model=StrategyResult,
)


class DailyExecutionProfile(QlibxModel):
    profile_id: str = "daily.next-session-close.v1"
    convention_id: str = "close-price.v1"
    market_dataset_id: str
    execution_price_role: str = "execution_price"
    valuation_price_role: str = "valuation_price"
    volume_role: str | None = None
    session_timezone: str = "Asia/Seoul"
    feedback_entry_limit: int = Field(default=256, gt=0)
    limitations: tuple[str, ...] = (
        "single close price for the full cross-sectional batch",
        "intraday path and market impact are not modelled",
        "partial fill is not modelled unless the Exchange has a participation policy",
    )


class DailyRunRequest(QlibxModel):
    run_id: str = Field(min_length=1)
    config_fingerprint: str = Field(min_length=1)
    decision_times: tuple[datetime, ...]
    session_closes: tuple[datetime, ...]

    @model_validator(mode="after")
    def validate_schedule(self) -> "DailyRunRequest":
        decisions = tuple(require_aware(value) for value in self.decision_times)
        sessions = tuple(require_aware(value) for value in self.session_closes)
        if decisions != tuple(sorted(set(decisions))):
            raise ValueError("decision_times must be unique and sorted")
        if sessions != tuple(sorted(set(sessions))):
            raise ValueError("session_closes must be unique and sorted")
        if not sessions:
            raise ValueError("daily flow requires at least one session close")
        return self


@dataclass(frozen=True, slots=True)
class DailyRunResult:
    strategy_results: tuple[StrategyResult, ...]
    decision_intents: tuple[DecisionIntent, ...]
    executions: tuple[ExecutionEvidence, ...]
    marks: tuple[MarkEvidence, ...]
    session_performance: tuple[SessionPerformanceEvidence, ...]
    monitors: tuple[MonitorEvidence, ...]
    memory_commits: tuple[MemoryCommitEvidence, ...]
    checkpoint: SimulationCheckpoint
    final_account: AccountSnapshot
    artifacts: tuple[ArtifactEnvelope, ...]


@dataclass(frozen=True, slots=True)
class _PendingExecution:
    intent: DecisionIntent
    intent_artifact: ArtifactEnvelope
    strategy_result: StrategyResult | None = None


@dataclass(frozen=True, slots=True)
class _AuthorityCommit:
    event_name: str
    event_time: datetime
    authority: str
    event_id: str
    version: int

    def context(self) -> dict[str, object]:
        return {
            "event_name": self.event_name,
            "event_time": self.event_time.isoformat(),
            "authority": self.authority,
            "event_id": self.event_id,
            "version": self.version,
        }


@dataclass(frozen=True, slots=True)
class _PublishedSessionPerformance:
    artifact_id: str
    record: SessionPerformanceEvidence


@dataclass(frozen=True, slots=True)
class _MemoryPlan:
    strategy_id: str
    value: dict[str, object]
    feedback_cursor: int
    expected_version: int
    commit_id: str
    initialization: bool
    source_artifact_id: str


@dataclass(frozen=True, slots=True)
class FrozenDecision:
    """A parent decision artifact reused by one isolated execution child."""

    intent: DecisionIntent
    artifact: ArtifactEnvelope


class NextSessionCloseExecutor:
    """Plan exactly one execution at the first eligible later session close."""

    def __init__(self, profile: DailyExecutionProfile, sessions: tuple[datetime, ...]) -> None:
        self.profile = profile
        self._sessions = tuple(require_aware(value) for value in sessions)

    def plan(self, decision: DecisionIntent) -> datetime | None:
        return next(
            (session for session in self._sessions if session > decision.decision_time),
            None,
        )


def _state(snapshot: AccountSnapshot) -> StateAccessRecord:
    return StateAccessRecord(
        account_id=snapshot.account_id,
        version=snapshot.version,
        feedback_cursor=snapshot.feedback_cursor,
        cash=snapshot.cash,
        nav=snapshot.nav,
        valuation_status=snapshot.valuation_status.value,
        as_of=snapshot.as_of,
        realized_pnl=snapshot.realized_pnl,
        holdings=tuple(
            StateHolding(
                instrument_id=position.instrument_id,
                quantity=position.quantity,
                mark=position.mark,
                marked_at=position.marked_at,
            )
            for position in snapshot.positions
        ),
    )


def _fill(fill: Fill) -> FillEvidence:
    return FillEvidence(
        fill_id=fill.fill_id,
        instrument_id=fill.instrument_id,
        side=fill.side,
        requested_quantity=fill.requested_quantity,
        dealt_quantity=fill.dealt_quantity,
        price=fill.price,
        trade_value=fill.trade_value,
        total_cost=fill.total_cost,
        cost_rule_id=fill.cost_rule_id,
        schedule_version=fill.schedule_version,
        reference_price=(fill.reference_price if fill.reference_price is not None else fill.price),
        price_impact_rate=fill.price_impact_rate,
    )


def _diagnostic(diagnostic: FillDiagnostic) -> FillDiagnosticEvidence:
    return FillDiagnosticEvidence(
        instrument_id=diagnostic.instrument_id,
        requested_quantity=diagnostic.requested_quantity,
        dealt_quantity=diagnostic.dealt_quantity,
        reasons=diagnostic.reasons,
    )


class DailyExecutionFlow:
    """Own callback order, Account commits, and portable evidence publication."""

    def __init__(
        self,
        *,
        clock: BacktestClock,
        registry: RegistrySnapshot,
        artifacts: LocalArtifactBackend,
        exchange: KrxExchange,
        account: Account,
        profile: DailyExecutionProfile,
        resolver: RequirementResolver | None = None,
        store: ObservationStore | None = None,
        memory: StrategyMemoryStore | None = None,
    ) -> None:
        self._clock = clock
        self._registry = registry
        self._artifacts = artifacts
        self._exchange = exchange
        self._account = account
        self._profile = profile
        self._resolver = resolver or RequirementResolver()
        self._store = store or ObservationStore()
        self._memory = memory or StrategyMemoryStore()
        self._gate = ViewGate(registry, self._store)
        self._research = ResearchFlow(
            registry=registry,
            artifacts=artifacts,
            resolver=self._resolver,
            store=self._store,
        )
        self._request: DailyRunRequest | None = None
        self._strategy: StrategyOperation | None = None
        self._executor: NextSessionCloseExecutor | None = None
        self._strategy_results: list[StrategyResult] = []
        self._intents: list[DecisionIntent] = []
        self._executions: list[ExecutionEvidence] = []
        self._marks: list[MarkEvidence] = []
        self._session_performance: list[_PublishedSessionPerformance] = []
        self._monitors: list[MonitorEvidence] = []
        self._memory_commits: list[MemoryCommitEvidence] = []
        self._published: list[ArtifactEnvelope] = []
        self._trace: list[str] = []
        self._completed_decisions: list[str] = []
        self._errors: list[OperationError] = []
        self._authority_commits: list[_AuthorityCommit] = []
        self._pending_executions: dict[str, _PendingExecution] = {}
        self._recovery_sequence = 0
        self._resume_position: tuple[datetime, int] | None = None
        self._request_fingerprint = ""
        self._profile_fingerprint = ""
        self._registry_fingerprint = ""

    def run(
        self,
        strategy: StrategyOperation,
        request: DailyRunRequest,
        *,
        resume: bool = False,
    ) -> OperationOutcome:
        self._prepare(request, strategy=strategy, resume=resume)
        if not self._errors:
            for timestamp in request.decision_times:
                normalized = require_aware(timestamp)
                event = Event("DECISION", normalized, DECISION_PRIORITY)
                if self._should_schedule(event):
                    self._clock.schedule(event, self._on_decision)
        return self._drain(request)

    def execute_frozen(
        self,
        decisions: tuple[FrozenDecision, ...],
        request: DailyRunRequest,
    ) -> OperationOutcome:
        """Execute parent artifacts without importing or rerunning their Strategy."""

        self._prepare(request)
        assert self._executor is not None
        for frozen in decisions:
            if (
                frozen.artifact.artifact_type != "decision_intent"
                or frozen.artifact.logical_identity
                != f"decision-intent:{frozen.intent.decision_id}"
            ):
                self._fail(
                    Event(
                        "EXECUTION",
                        frozen.intent.decision_time,
                        EXECUTION_PRIORITY,
                    ),
                    "execution_plan",
                    "PARENT_ARTIFACT_ID_MISMATCH",
                )
                break
            execution_time = self._executor.plan(frozen.intent)
            if execution_time is None:
                self._fail(
                    Event(
                        "EXECUTION",
                        frozen.intent.decision_time,
                        EXECUTION_PRIORITY,
                    ),
                    "execution_plan",
                    "NEXT_SESSION_NOT_AVAILABLE",
                )
                break
            self._intents.append(frozen.intent)
            pending = _PendingExecution(
                intent=frozen.intent,
                intent_artifact=frozen.artifact,
            )
            self._pending_executions[frozen.intent.decision_id] = pending
            if self._publish_recovery_point(
                event=Event("DECISION", frozen.intent.decision_time, DECISION_PRIORITY)
            ) is None:
                break
            self._clock.schedule(
                Event(
                    "EXECUTION",
                    execution_time,
                    EXECUTION_PRIORITY,
                    pending,
                ),
                self._on_execution,
            )
        return self._drain(request)

    def _prepare(
        self,
        request: DailyRunRequest,
        *,
        strategy: StrategyOperation | None = None,
        resume: bool = False,
    ) -> None:
        if self._request is not None:
            raise RuntimeError("DailyExecutionFlow instances are single-use")
        self._request = request
        self._strategy = strategy
        self._executor = NextSessionCloseExecutor(self._profile, request.session_closes)
        self._request_fingerprint = self._fingerprint(request.model_dump_json())
        self._profile_fingerprint = self._fingerprint(self._profile.model_dump_json())
        self._registry_fingerprint = self._fingerprint(
            "|".join(
                item.registration_identity
                for item in sorted(self._registry.datasets, key=lambda value: value.dataset_id)
            )
        )
        if resume:
            self._restore_recovery_point(strategy_id=strategy.strategy_id if strategy else None)
        else:
            self._publish_recovery_point(event=None)
        if self._errors:
            return
        for timestamp in request.session_closes:
            normalized = require_aware(timestamp)
            mark = Event("MARK", normalized, MARK_PRIORITY)
            monitor = Event("MONITOR", normalized, MONITOR_PRIORITY)
            if self._should_schedule(mark):
                self._clock.schedule(mark, self._on_mark)
            if self._should_schedule(monitor):
                self._clock.schedule(monitor, self._on_monitor)
        for pending in self._pending_executions.values():
            execution_time = self._executor.plan(pending.intent)
            if execution_time is None:
                self._fail(
                    Event("RESUME", self._clock.now, EXECUTION_PRIORITY),
                    "resume",
                    "NEXT_SESSION_NOT_AVAILABLE",
                )
                return
            execution = Event(
                "EXECUTION",
                execution_time,
                EXECUTION_PRIORITY,
                pending,
            )
            if self._should_schedule(execution):
                self._clock.schedule(execution, self._on_execution)

    def _drain(self, request: DailyRunRequest) -> OperationOutcome:

        while not self._clock.is_finished() and not self._errors:
            for handler in self._clock.advance_to_next():
                self._trace.append(
                    f"{handler.event.ts.isoformat()}|{handler.event.priority}|"
                    f"{handler.event.name}"
                )
                handler.callback(handler.event)
                if self._errors:
                    break

        if not self._errors:
            self._hydrate_run_evidence()
        if self._errors:
            return OperationOutcome(
                status=OutcomeStatus.FAILED,
                diagnostics=tuple(self._published),
                errors=tuple(self._errors),
            )

        final_account = self._account.snapshot(evaluation_time=self._clock.now)
        checkpoint = SimulationCheckpoint(
            run_id=request.run_id,
            request_fingerprint=self._request_fingerprint,
            config_fingerprint=request.config_fingerprint,
            profile_fingerprint=self._profile_fingerprint,
            registry_fingerprint=self._registry_fingerprint,
            strategy_id=self._strategy.strategy_id if self._strategy is not None else None,
            event_time=self._clock.now,
            account=_state(final_account),
            account_checkpoint=self._account.checkpoint(),
            memory_snapshots=self._memory.checkpoint(),
            event_trace=tuple(self._trace),
            completed_decision_ids=tuple(self._completed_decisions),
        )
        checkpoint_artifact = self._publish_model(
            event=None,
            stage="checkpoint.artifact",
            logical_identity=f"simulation-checkpoint:{request.run_id}",
            artifact_type="simulation_checkpoint",
            artifact_schema_version=2,
            producer_id=self._profile.profile_id,
            payload=checkpoint,
            dependencies=(
                DependencyEdge(
                    dependency_kind="state",
                    dependency_id=(
                        f"account:{final_account.account_id}:v{final_account.version}:"
                        f"cursor{final_account.feedback_cursor}"
                    ),
                    consumer_role="actual_account_checkpoint",
                ),
            ),
        )
        if checkpoint_artifact is None:
            return OperationOutcome(
                status=OutcomeStatus.FAILED,
                diagnostics=tuple(self._published),
                errors=tuple(self._errors),
            )
        return OperationOutcome(
            status=OutcomeStatus.COMPLETE,
            result=DailyRunResult(
                strategy_results=tuple(self._strategy_results),
                decision_intents=tuple(self._intents),
                executions=tuple(self._executions),
                marks=tuple(self._marks),
                session_performance=tuple(
                    item.record for item in self._session_performance
                ),
                monitors=tuple(self._monitors),
                memory_commits=tuple(self._memory_commits),
                checkpoint=checkpoint,
                final_account=final_account,
                artifacts=tuple(self._published),
            ),
        )

    def _on_decision(self, event: Event) -> None:
        assert self._request is not None
        assert self._strategy is not None
        assert self._executor is not None
        decision_id = (
            f"{self._request.run_id}:decision:"
            f"{event.ts.isoformat().replace('+00:00', 'Z')}"
        )
        invocation = StrategyInvocation(
            invocation_id=decision_id,
            evaluation_time=event.ts,
            config_fingerprint=self._request.config_fingerprint,
        )
        account_state = self._account.snapshot(evaluation_time=event.ts)
        memory_state = self._memory.snapshot(self._strategy.strategy_id)
        try:
            account_feedback = self._account.feedback(
                memory_state.feedback_cursor,
                self._profile.feedback_entry_limit,
            )
        except ValueError as exc:
            self._fail(
                event,
                "decision.feedback",
                "ACCOUNT_FEEDBACK_CURSOR_INVALID",
                context={"message": str(exc)},
            )
            return
        if account_feedback.next_cursor != account_state.feedback_cursor:
            self._fail(
                event,
                "decision.feedback",
                "ACCOUNT_FEEDBACK_WINDOW_EXCEEDED",
                context={
                    "after_cursor": account_feedback.after_cursor,
                    "next_cursor": account_feedback.next_cursor,
                    "account_cursor": account_state.feedback_cursor,
                    "entry_limit": self._profile.feedback_entry_limit,
                },
            )
            return
        outcome = self._research.invoke_strategy(
            self._strategy,
            invocation,
            account_state=account_state,
            account_feedback=account_feedback,
            session_performance=(
                self._session_performance[-1]
                if self._session_performance
                else None
            ),
            memory_state=memory_state,
        )
        if outcome.status is not OutcomeStatus.COMPLETE:
            self._errors.extend(outcome.errors)
            return
        run_result = outcome.result
        if not isinstance(run_result, StrategyRunResult):
            self._fail(event, "decision", "STRATEGY_RESULT_INVALID")
            return
        self._strategy_results.append(run_result.result)
        self._published.append(run_result.artifact)
        if run_result.result.decision_action is not DecisionAction.TARGET:
            plan = self._plan_memory(
                event,
                run_result.result,
                run_result.artifact.artifact_id,
            )
            if self._errors:
                return
            candidate_memory = StrategyMemoryStore.from_checkpoint(
                self._memory.checkpoint()
            )
            if plan is not None:
                self._apply_memory_plan(
                    event,
                    plan,
                    run_result.result,
                    store=candidate_memory,
                    publish=False,
                )
                if self._errors:
                    return
            completed = (*self._completed_decisions, decision_id)
            if self._publish_recovery_point(
                event=event,
                memory_snapshots=candidate_memory.checkpoint(),
                completed_decision_ids=completed,
                pending_publications=(
                    (self._memory_recovery_publication(plan, run_result.result),)
                    if plan is not None
                    else ()
                ),
            ) is None:
                return
            if plan is not None:
                self._apply_memory_plan(
                    event,
                    plan,
                    run_result.result,
                    store=self._memory,
                    publish=True,
                )
                if self._errors:
                    return
            self._completed_decisions.append(decision_id)
            return
        if any(weight.weight < 0 for weight in run_result.result.weights):
            self._fail(event, "decision", "SIGNED_TARGET_REQUIRES_CONSTRUCTION")
            return

        snapshot = self._account.snapshot(evaluation_time=event.ts)
        intent = DecisionIntent(
            decision_id=decision_id,
            strategy_id=run_result.result.strategy_id,
            strategy_artifact_id=run_result.artifact.artifact_id,
            decision_time=event.ts,
            account_id=snapshot.account_id,
            account_version=snapshot.version,
            feedback_cursor=snapshot.feedback_cursor,
            targets=tuple(
                DecisionTarget(instrument_id=weight.instrument, weight=weight.weight)
                for weight in sorted(
                    run_result.result.weights,
                    key=lambda value: value.instrument,
                )
            ),
        )
        intent_artifact = self._publish_model(
            event=event,
            stage="decision.artifact",
            logical_identity=f"decision-intent:{decision_id}",
            artifact_type="decision_intent",
            producer_id=run_result.result.strategy_id,
            payload=intent,
            dependencies=(
                DependencyEdge(
                    dependency_kind="artifact",
                    dependency_id=run_result.artifact.artifact_id,
                    consumer_role="strategy_result",
                ),
                DependencyEdge(
                    dependency_kind="state",
                    dependency_id=(
                        f"account:{snapshot.account_id}:v{snapshot.version}:"
                        f"cursor{snapshot.feedback_cursor}"
                    ),
                    consumer_role="decision_actual_state",
                ),
            ),
        )
        if intent_artifact is None:
            return
        self._intents.append(intent)
        execution_time = self._executor.plan(intent)
        if execution_time is None:
            self._fail(event, "execution_plan", "NEXT_SESSION_NOT_AVAILABLE")
            return
        pending = _PendingExecution(
            intent=intent,
            intent_artifact=intent_artifact,
            strategy_result=run_result.result,
        )
        self._pending_executions[intent.decision_id] = pending
        if self._publish_recovery_point(event=event) is None:
            return
        self._clock.schedule(
            Event(
                "EXECUTION",
                execution_time,
                EXECUTION_PRIORITY,
                pending,
            ),
            self._on_execution,
        )

    def _on_execution(self, event: Event) -> None:
        if not isinstance(event.payload, _PendingExecution):
            self._fail(event, "execution", "EXECUTION_PAYLOAD_INVALID")
            return
        pending = event.payload
        execution_id = self._event_id(
            event,
            f"execution:{pending.intent.decision_id}",
        )
        binding = self._resolve(
            event,
            "execution",
            ComponentRequirement(
                requirement_id="executor.daily.execution_price",
                semantic_role=self._profile.execution_price_role,
                dataset_id=self._profile.market_dataset_id,
            ),
        )
        if binding is None:
            return
        volume_binding = None
        if self._profile.volume_role is not None:
            volume_binding = self._resolve(
                event,
                "execution",
                ComponentRequirement(
                    requirement_id="executor.daily.available_volume",
                    semantic_role=self._profile.volume_role,
                    dataset_id=self._profile.market_dataset_id,
                ),
            )
            if volume_binding is None:
                return
        before = self._account.snapshot(evaluation_time=event.ts)
        if before.positions and before.valuation_status.value == "INCOMPLETE":
            self._fail(event, "execution", "ACCOUNT_VALUATION_INCOMPLETE")
            return
        view = self._gate.execution_view(
            self._clock,
            (binding, *((volume_binding,) if volume_binding is not None else ())),
            account_state=before,
        )
        session_date = event.ts.astimezone(ZoneInfo(self._profile.session_timezone)).date()
        frame = view.session(self._profile.execution_price_role, session_date)
        prices = {
            str(row.instrument): float(getattr(row, self._profile.execution_price_role))
            for row in frame.itertuples()
            if math.isfinite(float(getattr(row, self._profile.execution_price_role)))
            and float(getattr(row, self._profile.execution_price_role)) > 0
        }
        volumes: dict[str, float] = {}
        if volume_binding is not None and self._profile.volume_role is not None:
            volume_frame = view.session(self._profile.volume_role, session_date)
            volumes = {
                str(row.instrument): float(getattr(row, self._profile.volume_role))
                for row in volume_frame.itertuples()
                if math.isfinite(float(getattr(row, self._profile.volume_role)))
                and float(getattr(row, self._profile.volume_role)) >= 0
            }
        target_weights = {
            target.instrument_id: target.weight for target in pending.intent.targets
        }
        required_instruments = sorted(set(target_weights) | set(before.holdings()))
        missing = tuple(
            instrument for instrument in required_instruments if instrument not in prices
        )
        if missing:
            self._fail(
                event,
                "execution",
                "EXECUTION_SESSION_PRICE_MISSING",
                context={"session": str(session_date), "instruments": list(missing[:20])},
            )
            return

        orders: list[Order] = []
        holdings = before.holdings()
        sizing_nav = before.cash + sum(
            holdings[instrument] * prices[instrument] for instrument in holdings
        )
        if not math.isfinite(sizing_nav) or sizing_nav <= 0:
            self._fail(
                event,
                "execution",
                "EXECUTION_SIZING_NAV_INVALID",
                context={"sizing_nav": sizing_nav},
            )
            return
        for instrument in required_instruments:
            target_quantity = (
                target_weights.get(instrument, 0) * sizing_nav / prices[instrument]
            )
            actual_quantity = holdings.get(instrument, 0)
            delta = target_quantity - actual_quantity
            if delta > 1e-12:
                orders.append(Order(instrument, Side.BUY, delta))
            elif delta < -1e-12:
                orders.append(Order(instrument, Side.SELL, -delta))
        orders.sort(key=lambda order: (0 if order.side is Side.SELL else 1, order.instrument_id))
        match = self._exchange.match_batch(
            event_id=execution_id,
            event_time=event.ts,
            orders=tuple(orders),
            quotes=tuple(
                MarketQuote(
                    instrument_id=instrument,
                    price=prices[instrument],
                    available_volume=volumes.get(instrument),
                )
                for instrument in required_instruments
            ),
            cash=before.cash,
            holdings=holdings,
        )
        if match.status is not OutcomeStatus.COMPLETE:
            self._errors.extend(match.errors)
            return
        committed_fills = tuple(
            fill for fill in match.result.fills if fill.dealt_quantity > 1e-12
        )
        fill_batch = (
            FillBatch(
                account_id=before.account_id,
                event_id=f"{execution_id}:fill",
                as_of=event.ts,
                fills=committed_fills,
            )
            if committed_fills
            else None
        )
        candidate_account = Account.from_checkpoint(self._account.checkpoint())
        if fill_batch is not None:
            try:
                candidate_commit = candidate_account.commit(
                    fill_batch,
                    expected_version=before.version,
                )
            except AccountCommitRejected as exc:
                self._fail(
                    event,
                    "execution.prepare",
                    exc.code,
                    context={"message": str(exc)},
                )
                return
            candidate_after = candidate_commit.snapshot
        else:
            candidate_after = before

        memory_plan = None
        candidate_memory = StrategyMemoryStore.from_checkpoint(self._memory.checkpoint())
        if pending.strategy_result is not None:
            memory_plan = self._plan_memory(
                event,
                pending.strategy_result,
                pending.intent.strategy_artifact_id,
            )
            if self._errors:
                return
            if memory_plan is not None:
                self._apply_memory_plan(
                    event,
                    memory_plan,
                    pending.strategy_result,
                    store=candidate_memory,
                    publish=False,
                )
                if self._errors:
                    return
        pending_after = dict(self._pending_executions)
        pending_after.pop(pending.intent.decision_id, None)
        completed_after = (*self._completed_decisions, pending.intent.decision_id)
        evidence_candidate = ExecutionEvidence(
            event_id=execution_id,
            decision_id=pending.intent.decision_id,
            event_time=event.ts,
            profile_id=self._profile.profile_id,
            convention_id=self._profile.convention_id,
            sizing_nav=sizing_nav,
            sizing_price_role=self._profile.execution_price_role,
            orders=tuple(
                OrderEvidence(
                    instrument_id=order.instrument_id,
                    side=order.side,
                    quantity=order.quantity,
                )
                for order in orders
            ),
            fills=tuple(_fill(fill) for fill in match.result.fills),
            diagnostics=tuple(
                _diagnostic(diagnostic) for diagnostic in match.result.diagnostics
            ),
            account_before=_state(before),
            account_after=_state(candidate_after),
            limitations=self._profile.limitations,
        )
        execution_dependencies = (
            DependencyEdge(
                dependency_kind="artifact",
                dependency_id=pending.intent_artifact.artifact_id,
                consumer_role="decision_intent",
            ),
            DependencyEdge(
                dependency_kind="dataset",
                dependency_id=binding.registration_identity,
                consumer_role=self._profile.execution_price_role,
                selected_fields=(binding.field,),
            ),
            *(
                (
                    DependencyEdge(
                        dependency_kind="dataset",
                        dependency_id=volume_binding.registration_identity,
                        consumer_role=self._profile.volume_role or "available_volume",
                        selected_fields=(volume_binding.field,),
                    ),
                )
                if volume_binding is not None
                else ()
            ),
            DependencyEdge(
                dependency_kind="state",
                dependency_id=(
                    f"account:{before.account_id}:v{before.version}:"
                    f"cursor{before.feedback_cursor}"
                ),
                consumer_role="pre_execution_actual_state",
            ),
        )
        recovery_publications = [
            self._recovery_publication(
                artifact_type="execution_result",
                logical_identity=f"execution-result:{evidence_candidate.event_id}",
                producer_id=self._profile.profile_id,
                payload=evidence_candidate,
                dependencies=execution_dependencies,
            )
        ]
        if memory_plan is not None and pending.strategy_result is not None:
            recovery_publications.append(
                self._memory_recovery_publication(
                    memory_plan,
                    pending.strategy_result,
                )
            )
        if self._publish_recovery_point(
            event=event,
            account_checkpoint=candidate_account.checkpoint(),
            memory_snapshots=candidate_memory.checkpoint(),
            completed_decision_ids=completed_after,
            pending_executions=pending_after,
            pending_publications=tuple(recovery_publications),
        ) is None:
            return

        if fill_batch is not None:
            try:
                commit = self._account.commit(
                    fill_batch,
                    expected_version=before.version,
                )
            except AccountCommitRejected as exc:
                self._fail(
                    event,
                    "execution.commit",
                    exc.code,
                    context={"message": str(exc)},
                )
                return
            self._record_authority_commit(
                event,
                authority="account",
                event_id=commit.event_id,
                version=commit.version,
            )
            after = commit.snapshot
        else:
            after = before
        if after != candidate_after:
            self._fail(event, "execution.commit", "RECOVERY_CANDIDATE_DIVERGED")
            return
        evidence = evidence_candidate
        published = self._publish_model(
            event=event,
            stage="execution.artifact",
            logical_identity=f"execution-result:{evidence.event_id}",
            artifact_type="execution_result",
            producer_id=self._profile.profile_id,
            payload=evidence,
            dependencies=execution_dependencies,
        )
        if published is None:
            return
        if pending.strategy_result is not None and memory_plan is not None:
            committed_memory = self._apply_memory_plan(
                event,
                memory_plan,
                pending.strategy_result,
                store=self._memory,
                publish=True,
            )
            if self._errors or committed_memory is None:
                return
            if committed_memory != candidate_memory.snapshot(memory_plan.strategy_id):
                self._fail(event, "memory.commit", "RECOVERY_CANDIDATE_DIVERGED")
                return
        self._executions.append(evidence)
        self._completed_decisions.append(pending.intent.decision_id)
        self._pending_executions.pop(pending.intent.decision_id, None)

    def _on_mark(self, event: Event) -> None:
        before = self._account.snapshot(evaluation_time=event.ts)
        held = tuple(sorted(before.holdings()))
        if not held:
            evidence = MarkEvidence(
                event_id=self._event_id(event, "mark"),
                event_time=event.ts,
                marks=(),
                account_before=_state(before),
                account_after=_state(before),
            )
            self._marks.append(evidence)
            self._publish_model(
                event=event,
                stage="mark.artifact",
                logical_identity=f"mark-result:{evidence.event_id}",
                artifact_type="mark_result",
                producer_id=self._profile.profile_id,
                payload=evidence,
            )
            return
        binding = self._resolve(
            event,
            "mark",
            ComponentRequirement(
                requirement_id="executor.daily.valuation_price",
                semantic_role=self._profile.valuation_price_role,
                dataset_id=self._profile.market_dataset_id,
            ),
        )
        if binding is None:
            return
        view = self._gate.execution_view(
            self._clock,
            (binding,),
            account_state=before,
        )
        session_date = event.ts.astimezone(ZoneInfo(self._profile.session_timezone)).date()
        frame = view.session(self._profile.valuation_price_role, session_date)
        price_by_instrument = {
            str(row.instrument): float(getattr(row, self._profile.valuation_price_role))
            for row in frame.itertuples()
        }
        invalid = tuple(
            instrument
            for instrument in held
            if instrument not in price_by_instrument
            or not math.isfinite(price_by_instrument[instrument])
            or price_by_instrument[instrument] <= 0
        )
        if invalid:
            self._fail(
                event,
                "mark",
                "VALUATION_PRICE_MISSING",
                context={"session": str(session_date), "instruments": list(invalid[:20])},
            )
            return
        marks = tuple(Mark(instrument, price_by_instrument[instrument]) for instrument in held)
        mark_batch = MarkBatch(
            account_id=before.account_id,
            event_id=self._event_id(event, "mark"),
            as_of=event.ts,
            marks=marks,
        )
        candidate_account = Account.from_checkpoint(self._account.checkpoint())
        try:
            candidate_commit = candidate_account.commit(
                mark_batch,
                expected_version=before.version,
            )
        except AccountCommitRejected as exc:
            self._fail(event, "mark.prepare", exc.code, context={"message": str(exc)})
            return
        evidence_candidate = MarkEvidence(
            event_id=self._event_id(event, "mark"),
            event_time=event.ts,
            marks=tuple((mark.instrument_id, mark.price) for mark in marks),
            account_before=_state(before),
            account_after=_state(candidate_commit.snapshot),
        )
        mark_dependencies = (
            DependencyEdge(
                dependency_kind="dataset",
                dependency_id=binding.registration_identity,
                consumer_role=self._profile.valuation_price_role,
                selected_fields=(binding.field,),
            ),
        )
        if self._publish_recovery_point(
            event=event,
            account_checkpoint=candidate_account.checkpoint(),
            pending_publications=(
                self._recovery_publication(
                    artifact_type="mark_result",
                    logical_identity=f"mark-result:{evidence_candidate.event_id}",
                    producer_id=self._profile.profile_id,
                    payload=evidence_candidate,
                    dependencies=mark_dependencies,
                ),
            ),
        ) is None:
            return
        try:
            commit = self._account.commit(
                mark_batch,
                expected_version=before.version,
            )
        except AccountCommitRejected as exc:
            self._fail(event, "mark.commit", exc.code, context={"message": str(exc)})
            return
        self._record_authority_commit(
            event,
            authority="account",
            event_id=commit.event_id,
            version=commit.version,
        )
        if commit.snapshot != candidate_commit.snapshot:
            self._fail(event, "mark.commit", "RECOVERY_CANDIDATE_DIVERGED")
            return
        evidence = evidence_candidate
        published = self._publish_model(
            event=event,
            stage="mark.artifact",
            logical_identity=f"mark-result:{evidence.event_id}",
            artifact_type="mark_result",
            producer_id=self._profile.profile_id,
            payload=evidence,
            dependencies=mark_dependencies,
        )
        if published is not None:
            self._marks.append(evidence)

    def _on_monitor(self, event: Event) -> None:
        mark = next(
            (item for item in reversed(self._marks) if item.event_time == event.ts),
            None,
        )
        if mark is None:
            self._fail(event, "session_performance", "SESSION_MARK_EVIDENCE_MISSING")
            return
        executions = tuple(
            item for item in self._executions if item.event_time == event.ts
        )
        opening = executions[0].account_before if executions else mark.account_before
        closing = mark.account_after
        trade_value = sum(
            abs(fill.trade_value)
            for execution in executions
            for fill in execution.fills
        )
        transaction_cost = sum(
            fill.total_cost
            for execution in executions
            for fill in execution.fills
        )
        if opening.nav == 0:
            turnover = None
            transaction_cost_rate = None
            gross_return = None
            portfolio_return = None
        else:
            turnover = trade_value / opening.nav
            transaction_cost_rate = transaction_cost / opening.nav
            portfolio_return = closing.nav / opening.nav - 1
            gross_return = portfolio_return + transaction_cost_rate
        performance = SessionPerformanceEvidence(
            event_id=self._event_id(event, "session-performance"),
            event_time=event.ts,
            account_id=closing.account_id,
            source_mark_event_id=mark.event_id,
            source_execution_event_ids=tuple(
                item.event_id for item in executions
            ),
            opening_account_version=opening.version,
            closing_account_version=closing.version,
            feedback_cursor=closing.feedback_cursor,
            opening_nav=opening.nav,
            closing_nav=closing.nav,
            closing_cash=closing.cash,
            trade_value=trade_value,
            transaction_cost=transaction_cost,
            turnover=turnover,
            transaction_cost_rate=transaction_cost_rate,
            gross_return=gross_return,
            portfolio_return=portfolio_return,
        )
        source_logical_identities = (
            f"mark-result:{mark.event_id}",
            *(
                f"execution-result:{execution.event_id}"
                for execution in executions
            ),
        )
        source_artifacts = {
            envelope.logical_identity: envelope
            for envelope in self._published
            if envelope.logical_identity in source_logical_identities
        }
        missing_sources = tuple(
            logical_identity
            for logical_identity in source_logical_identities
            if logical_identity not in source_artifacts
        )
        if missing_sources:
            self._fail(
                event,
                "session_performance",
                "SESSION_SOURCE_ARTIFACT_MISSING",
                context={"logical_identities": list(missing_sources)},
            )
            return
        performance_artifact = self._publish_model(
            event=event,
            stage="session_performance.artifact",
            logical_identity=f"session-performance:{performance.event_id}",
            artifact_type="session_performance",
            producer_id=self._profile.profile_id,
            payload=performance,
            dependencies=tuple(
                DependencyEdge(
                    dependency_kind="artifact",
                    dependency_id=source_artifacts[logical_identity].artifact_id,
                    consumer_role=(
                        "committed_mark"
                        if logical_identity.startswith("mark-result:")
                        else "committed_execution"
                    ),
                )
                for logical_identity in source_logical_identities
            ),
        )
        if performance_artifact is None:
            return
        self._session_performance.append(
            _PublishedSessionPerformance(
                artifact_id=performance_artifact.artifact_id,
                record=performance,
            )
        )

        before = self._account.snapshot(evaluation_time=event.ts)
        evidence = MonitorEvidence(
            event_id=self._event_id(event, "monitor"),
            event_time=event.ts,
            account=_state(before),
            account_version_after_callback=self._account.snapshot(
                evaluation_time=event.ts
            ).version,
        )
        published = self._publish_model(
            event=event,
            stage="monitor.artifact",
            logical_identity=f"monitor-result:{evidence.event_id}",
            artifact_type="monitor_observation",
            producer_id=self._profile.profile_id,
            payload=evidence,
            dependencies=(
                DependencyEdge(
                    dependency_kind="state",
                    dependency_id=(
                        f"account:{before.account_id}:v{before.version}:"
                        f"cursor{before.feedback_cursor}"
                    ),
                    consumer_role="committed_account_snapshot",
                ),
            ),
        )
        if published is not None:
            self._monitors.append(evidence)

    def _plan_memory(
        self,
        event: Event,
        result: StrategyResult,
        source_artifact_id: str,
    ) -> _MemoryPlan | None:
        assert self._request is not None
        if result.proposed_memory is None:
            return None
        if result.expected_memory_version is None or not result.memory_accesses:
            self._fail(event, "memory", "MEMORY_PROPOSAL_WITHOUT_PRIOR_STATE")
            return None
        prior = result.memory_accesses[-1]
        current = self._memory.snapshot(result.strategy_id)
        if (
            prior.strategy_id != result.strategy_id
            or prior.version != result.expected_memory_version
            or current.version != result.expected_memory_version
        ):
            self._fail(
                event,
                "memory",
                "MEMORY_CAS_MISMATCH",
                context={
                    "expected_version": result.expected_memory_version,
                    "current_version": current.version,
                },
            )
            return None
        if not result.state_accesses:
            self._fail(event, "memory", "MEMORY_PROPOSAL_WITHOUT_ACTUAL_FEEDBACK")
            return None
        state_access = result.state_accesses[-1]
        initialization_feedback = (
            not result.feedback_accesses
            or (
                result.feedback_accesses[-1].after_cursor == 0
                and result.feedback_accesses[-1].next_cursor == 0
            )
        )
        initialization = (
            current.version == 0
            and current.value is None
            and current.feedback_cursor == 0
            and state_access.feedback_cursor == 0
            and initialization_feedback
        )
        if initialization:
            feedback_cursor = 0
        else:
            if not result.feedback_accesses:
                self._fail(event, "memory", "MEMORY_PROPOSAL_WITHOUT_ACTUAL_FEEDBACK")
                return None
            feedback_access = result.feedback_accesses[-1]
            if (
                feedback_access.account_id != state_access.account_id
                or feedback_access.after_cursor != current.feedback_cursor
                or feedback_access.next_cursor > state_access.feedback_cursor
            ):
                self._fail(
                    event,
                    "memory",
                    "MEMORY_FEEDBACK_CURSOR_MISMATCH",
                    context={
                        "feedback_account_id": feedback_access.account_id,
                        "state_account_id": state_access.account_id,
                        "after_cursor": feedback_access.after_cursor,
                        "memory_feedback_cursor": current.feedback_cursor,
                        "next_cursor": feedback_access.next_cursor,
                        "state_feedback_cursor": state_access.feedback_cursor,
                    },
                )
                return None
            feedback_cursor = feedback_access.next_cursor
        if feedback_cursor <= current.feedback_cursor and not initialization:
            self._fail(
                event,
                "memory",
                "MEMORY_FEEDBACK_NOT_ADVANCED",
                context={
                    "consumed_feedback_cursor": feedback_cursor,
                    "memory_feedback_cursor": current.feedback_cursor,
                },
            )
            return None
        commit_seed = (
            f"{self._request.run_id}:{result.strategy_id}:{source_artifact_id}:"
            f"v{result.expected_memory_version + 1}"
        )
        return _MemoryPlan(
            strategy_id=result.strategy_id,
            value=dict(result.proposed_memory),
            feedback_cursor=feedback_cursor,
            expected_version=result.expected_memory_version,
            commit_id=f"memory-{self._fingerprint(commit_seed)[:24]}",
            initialization=initialization,
            source_artifact_id=source_artifact_id,
        )

    @staticmethod
    def _recovery_publication(
        *,
        artifact_type: Literal["execution_result", "mark_result", "memory_commit"],
        logical_identity: str,
        producer_id: str,
        payload: QlibxModel,
        dependencies: tuple[DependencyEdge, ...] = (),
    ) -> RecoveryPublication:
        return RecoveryPublication(
            artifact_type=artifact_type,
            logical_identity=logical_identity,
            producer_id=producer_id,
            artifact_schema_version=1,
            payload_json=payload.model_dump_json(),
            dependencies=dependencies,
        )

    def _memory_evidence(self, plan: _MemoryPlan) -> MemoryCommitEvidence:
        return MemoryCommitEvidence(
            strategy_id=plan.strategy_id,
            source_artifact_id=plan.source_artifact_id,
            previous_version=plan.expected_version,
            version=plan.expected_version + 1,
            feedback_cursor=plan.feedback_cursor,
            update_kind="INITIALIZATION" if plan.initialization else "FEEDBACK_UPDATE",
            value=plan.value,
        )

    @staticmethod
    def _memory_dependencies(
        plan: _MemoryPlan,
        result: StrategyResult,
    ) -> tuple[DependencyEdge, ...]:
        return (
            DependencyEdge(
                dependency_kind="artifact",
                dependency_id=plan.source_artifact_id,
                consumer_role="proposed_memory",
            ),
            DependencyEdge(
                dependency_kind="state",
                dependency_id=(
                    f"account:{result.state_accesses[-1].account_id}:"
                    f"v{result.state_accesses[-1].version}:"
                    f"cursor{plan.feedback_cursor}"
                ),
                consumer_role=(
                    "initial_actual_state"
                    if plan.initialization
                    else "confirmed_feedback"
                ),
            ),
        )

    def _memory_recovery_publication(
        self,
        plan: _MemoryPlan,
        result: StrategyResult,
    ) -> RecoveryPublication:
        assert self._request is not None
        return self._recovery_publication(
            artifact_type="memory_commit",
            logical_identity=(
                f"memory-commit:{self._request.run_id}:{plan.strategy_id}:"
                f"v{plan.expected_version + 1}"
            ),
            producer_id=plan.strategy_id,
            payload=self._memory_evidence(plan),
            dependencies=self._memory_dependencies(plan, result),
        )

    def _apply_memory_plan(
        self,
        event: Event,
        plan: _MemoryPlan,
        result: StrategyResult,
        *,
        store: StrategyMemoryStore,
        publish: bool,
    ) -> MemorySnapshot | None:
        assert self._request is not None
        try:
            committed = store.commit(
                strategy_id=plan.strategy_id,
                value=plan.value,
                feedback_cursor=plan.feedback_cursor,
                expected_version=plan.expected_version,
                commit_id=plan.commit_id,
            )
        except ValueError as exc:
            self._fail(
                event,
                "memory.commit",
                "MEMORY_COMMIT_REJECTED",
                context={"message": str(exc)},
            )
            return None
        if not publish:
            return committed
        self._record_authority_commit(
            event,
            authority="memory",
            event_id=plan.commit_id,
            version=committed.version,
        )
        evidence = self._memory_evidence(plan)
        if committed.version != evidence.version:
            self._fail(event, "memory.commit", "RECOVERY_CANDIDATE_DIVERGED")
            return None
        published = self._publish_model(
            event=event,
            stage="memory.artifact",
            logical_identity=(
                f"memory-commit:{self._request.run_id}:{plan.strategy_id}:"
                f"v{committed.version}"
            ),
            artifact_type="memory_commit",
            producer_id=plan.strategy_id,
            payload=evidence,
            dependencies=self._memory_dependencies(plan, result),
        )
        if published is not None:
            self._memory_commits.append(evidence)
        return committed

    @staticmethod
    def _fingerprint(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def _should_schedule(self, event: Event) -> bool:
        return self._resume_position is None or (
            event.ts,
            event.priority,
        ) > self._resume_position

    def _pending_recovery(
        self,
        pending: dict[str, _PendingExecution] | None = None,
    ) -> tuple[PendingExecutionRecovery, ...]:
        assert self._executor is not None
        selected = pending if pending is not None else self._pending_executions
        recovered: list[PendingExecutionRecovery] = []
        for decision_id in sorted(selected):
            item = selected[decision_id]
            execution_time = self._executor.plan(item.intent)
            if execution_time is None:
                raise ValueError("pending decision has no eligible execution session")
            recovered.append(
                PendingExecutionRecovery(
                    decision_id=decision_id,
                    intent_artifact_id=item.intent_artifact.artifact_id,
                    execution_time=execution_time,
                    commit_strategy_memory=item.strategy_result is not None,
                )
            )
        return tuple(recovered)

    def _publish_recovery_point(
        self,
        *,
        event: Event | None,
        account_checkpoint: AccountCheckpoint | None = None,
        memory_snapshots: tuple[MemorySnapshot, ...] | None = None,
        completed_decision_ids: tuple[str, ...] | None = None,
        pending_executions: dict[str, _PendingExecution] | None = None,
        pending_publications: tuple[RecoveryPublication, ...] = (),
    ) -> SimulationRecoveryPoint | None:
        assert self._request is not None
        sequence = self._recovery_sequence + 1 if event is not None else 0
        point = SimulationRecoveryPoint(
            run_id=self._request.run_id,
            request_fingerprint=self._request_fingerprint,
            config_fingerprint=self._request.config_fingerprint,
            profile_fingerprint=self._profile_fingerprint,
            registry_fingerprint=self._registry_fingerprint,
            strategy_id=self._strategy.strategy_id if self._strategy is not None else None,
            sequence=sequence,
            last_event_time=event.ts if event is not None else None,
            last_event_priority=event.priority if event is not None else None,
            last_event_name=event.name if event is not None else None,
            account_checkpoint=account_checkpoint or self._account.checkpoint(),
            memory_snapshots=(
                memory_snapshots
                if memory_snapshots is not None
                else self._memory.checkpoint()
            ),
            event_trace=tuple(self._trace),
            completed_decision_ids=(
                completed_decision_ids
                if completed_decision_ids is not None
                else tuple(self._completed_decisions)
            ),
            pending_executions=self._pending_recovery(pending_executions),
            pending_publications=pending_publications,
        )
        suffix = (
            "initial"
            if event is None
            else (
                f"{event.ts.isoformat().replace('+00:00', 'Z')}:"
                f"{event.priority}:{event.name.lower()}"
            )
        )
        publication = self._artifacts.publish_model(
            logical_identity=(
                f"simulation-recovery:{self._request.run_id}:{sequence:08d}:{suffix}"
            ),
            artifact_type="simulation_recovery_point",
            artifact_schema_version=1,
            producer_id=self._profile.profile_id,
            payload=point,
            dependencies=(
                DependencyEdge(
                    dependency_kind="state",
                    dependency_id=(
                        f"account:{point.account_checkpoint.account_id}:"
                        f"v{point.account_checkpoint.version}"
                    ),
                    consumer_role="recoverable_actual_state",
                ),
            ),
        )
        if publication.status is not OutcomeStatus.COMPLETE:
            failure_event = event or Event(
                "RECOVERY",
                self._clock.now,
                DECISION_PRIORITY,
            )
            self._fail(
                failure_event,
                "recovery.publish",
                "RECOVERY_POINT_PUBLICATION_FAILED",
                context={
                    "publication_errors": [
                        error.model_dump(mode="json")
                        for error in publication.errors[:5]
                    ],
                },
            )
            return None
        self._recovery_sequence = sequence
        return point

    def _restore_recovery_point(self, *, strategy_id: str | None) -> None:
        assert self._request is not None
        prefix = f"simulation-recovery:{self._request.run_id}:"
        envelopes = tuple(
            envelope
            for envelope in self._artifacts.list_envelopes()
            if envelope.logical_identity.startswith(prefix)
            and envelope.artifact_type == "simulation_recovery_point"
        )
        resume_event = Event("RESUME", self._clock.now, DECISION_PRIORITY)
        if not envelopes:
            self._fail(
                resume_event,
                "resume",
                "RECOVERY_POINT_NOT_FOUND",
                context={"run_id": self._request.run_id},
            )
            return
        loaded_points: list[tuple[ArtifactEnvelope, SimulationRecoveryPoint]] = []
        for envelope in envelopes:
            loaded = self._artifacts.load_model(
                envelope.artifact_id,
                SIMULATION_RECOVERY_POINT_CONTRACT,
            )
            if loaded.status is not OutcomeStatus.COMPLETE:
                self._errors.extend(loaded.errors)
                return
            loaded_points.append((loaded.result.envelope, loaded.result.payload))
        _, point = max(loaded_points, key=lambda item: item[1].sequence)
        expected = {
            "request_fingerprint": self._request_fingerprint,
            "config_fingerprint": self._request.config_fingerprint,
            "profile_fingerprint": self._profile_fingerprint,
            "registry_fingerprint": self._registry_fingerprint,
            "strategy_id": strategy_id,
        }
        actual = {
            "request_fingerprint": point.request_fingerprint,
            "config_fingerprint": point.config_fingerprint,
            "profile_fingerprint": point.profile_fingerprint,
            "registry_fingerprint": point.registry_fingerprint,
            "strategy_id": point.strategy_id,
        }
        mismatches = {
            key: {"expected": expected[key], "actual": actual[key]}
            for key in expected
            if expected[key] != actual[key]
        }
        if mismatches:
            self._fail(
                resume_event,
                "resume.identity",
                "RESUME_BRANCH_REQUIRED",
                context={"mismatches": mismatches},
            )
            return

        restored_account = Account.from_checkpoint(point.account_checkpoint)
        restored_memory = StrategyMemoryStore.from_checkpoint(point.memory_snapshots)
        restored_pending: dict[str, _PendingExecution] = {}
        for pending in point.pending_executions:
            loaded_intent = self._artifacts.load_model(
                pending.intent_artifact_id,
                DECISION_INTENT_CONTRACT,
            )
            if loaded_intent.status is not OutcomeStatus.COMPLETE:
                self._errors.extend(loaded_intent.errors)
                return
            intent = loaded_intent.result.payload
            if intent.decision_id != pending.decision_id:
                self._fail(
                    resume_event,
                    "resume.pending",
                    "RECOVERY_PENDING_DECISION_MISMATCH",
                )
                return
            strategy_result = None
            if pending.commit_strategy_memory:
                loaded_strategy = self._artifacts.load_model(
                    intent.strategy_artifact_id,
                    STRATEGY_RESULT_RECOVERY_CONTRACT,
                )
                if loaded_strategy.status is not OutcomeStatus.COMPLETE:
                    self._errors.extend(loaded_strategy.errors)
                    return
                strategy_result = loaded_strategy.result.payload
                self._strategy_results.append(strategy_result)
                self._published.append(loaded_strategy.result.envelope)
            restored_pending[pending.decision_id] = _PendingExecution(
                intent=intent,
                intent_artifact=loaded_intent.result.envelope,
                strategy_result=strategy_result,
            )
            self._intents.append(intent)
            self._published.append(loaded_intent.result.envelope)

        self._account = restored_account
        self._memory = restored_memory
        self._trace = list(point.event_trace)
        self._completed_decisions = list(point.completed_decision_ids)
        self._pending_executions = restored_pending
        self._recovery_sequence = point.sequence
        self._resume_position = (
            (point.last_event_time, point.last_event_priority)
            if point.last_event_time is not None
            and point.last_event_priority is not None
            else None
        )
        publication_models: dict[str, type[QlibxModel]] = {
            "execution_result": ExecutionEvidence,
            "mark_result": MarkEvidence,
            "memory_commit": MemoryCommitEvidence,
        }
        for pending_publication in point.pending_publications:
            payload_model = publication_models[pending_publication.artifact_type]
            try:
                payload = payload_model.model_validate_json(
                    pending_publication.payload_json
                )
            except Exception as exc:
                self._fail(
                    resume_event,
                    "resume.publication",
                    "RECOVERY_PUBLICATION_INVALID",
                    context={
                        "artifact_type": pending_publication.artifact_type,
                        "message": str(exc)[:500],
                    },
                )
                return
            publication = self._artifacts.publish_model(
                logical_identity=pending_publication.logical_identity,
                artifact_type=pending_publication.artifact_type,
                artifact_schema_version=(
                    pending_publication.artifact_schema_version
                ),
                producer_id=pending_publication.producer_id,
                payload=payload,
                dependencies=pending_publication.dependencies,
            )
            if publication.status is not OutcomeStatus.COMPLETE:
                self._errors.extend(publication.errors)
                return
            self._published.append(publication.result)
            if isinstance(payload, ExecutionEvidence):
                self._executions.append(payload)
            elif isinstance(payload, MarkEvidence):
                self._marks.append(payload)
            elif isinstance(payload, MemoryCommitEvidence):
                self._memory_commits.append(payload)
        self._hydrate_run_evidence()

    def _hydrate_run_evidence(self) -> None:
        assert self._request is not None
        contracts: dict[str, ArtifactContract[QlibxModel]] = {
            "strategy_result": ArtifactContract(
                artifact_type="strategy_result",
                artifact_schema_version=1,
                payload_model=StrategyResult,
            ),
            "decision_intent": DECISION_INTENT_CONTRACT,
            "execution_result": ArtifactContract(
                artifact_type="execution_result",
                artifact_schema_version=1,
                payload_model=ExecutionEvidence,
            ),
            "mark_result": ArtifactContract(
                artifact_type="mark_result",
                artifact_schema_version=1,
                payload_model=MarkEvidence,
            ),
            "monitor_observation": ArtifactContract(
                artifact_type="monitor_observation",
                artifact_schema_version=1,
                payload_model=MonitorEvidence,
            ),
            "session_performance": ArtifactContract(
                artifact_type="session_performance",
                artifact_schema_version=1,
                payload_model=SessionPerformanceEvidence,
            ),
            "memory_commit": ArtifactContract(
                artifact_type="memory_commit",
                artifact_schema_version=1,
                payload_model=MemoryCommitEvidence,
            ),
        }
        marker = f":{self._request.run_id}:"
        envelopes = tuple(
            envelope
            for envelope in self._artifacts.list_envelopes()
            if marker in envelope.logical_identity
            and envelope.artifact_type in contracts
        )
        strategy_results: dict[str, StrategyResult] = {
            item.invocation_id: item for item in self._strategy_results
        }
        intents: dict[str, DecisionIntent] = {
            item.decision_id: item for item in self._intents
        }
        executions: dict[str, ExecutionEvidence] = {
            item.event_id: item for item in self._executions
        }
        marks: dict[str, MarkEvidence] = {
            item.event_id: item for item in self._marks
        }
        monitors: dict[str, MonitorEvidence] = {
            item.event_id: item for item in self._monitors
        }
        session_performance: dict[str, _PublishedSessionPerformance] = {
            item.record.event_id: item for item in self._session_performance
        }
        memory_commits: dict[tuple[str, int], MemoryCommitEvidence] = {
            (item.strategy_id, item.version): item for item in self._memory_commits
        }
        published = {item.artifact_id: item for item in self._published}
        for envelope in envelopes:
            loaded = self._artifacts.load_model(
                envelope.artifact_id,
                contracts[envelope.artifact_type],
            )
            if loaded.status is not OutcomeStatus.COMPLETE:
                self._errors.extend(loaded.errors)
                return
            payload = loaded.result.payload
            published[envelope.artifact_id] = envelope
            if isinstance(payload, StrategyResult):
                strategy_results[payload.invocation_id] = payload
            elif isinstance(payload, DecisionIntent):
                intents[payload.decision_id] = payload
            elif isinstance(payload, ExecutionEvidence):
                executions[payload.event_id] = payload
            elif isinstance(payload, MarkEvidence):
                marks[payload.event_id] = payload
            elif isinstance(payload, MonitorEvidence):
                monitors[payload.event_id] = payload
            elif isinstance(payload, SessionPerformanceEvidence):
                session_performance[payload.event_id] = _PublishedSessionPerformance(
                    artifact_id=envelope.artifact_id,
                    record=payload,
                )
            elif isinstance(payload, MemoryCommitEvidence):
                memory_commits[(payload.strategy_id, payload.version)] = payload

        self._strategy_results = sorted(
            strategy_results.values(),
            key=lambda item: (item.evaluation_time, item.invocation_id),
        )
        self._intents = sorted(
            intents.values(),
            key=lambda item: (item.decision_time, item.decision_id),
        )
        self._executions = sorted(
            executions.values(),
            key=lambda item: (item.event_time, item.event_id),
        )
        self._marks = sorted(
            marks.values(),
            key=lambda item: (item.event_time, item.event_id),
        )
        self._monitors = sorted(
            monitors.values(),
            key=lambda item: (item.event_time, item.event_id),
        )
        self._session_performance = sorted(
            session_performance.values(),
            key=lambda item: (item.record.event_time, item.record.event_id),
        )
        self._memory_commits = sorted(
            memory_commits.values(),
            key=lambda item: (item.strategy_id, item.version),
        )
        self._published = list(published.values())

    def _resolve(
        self,
        event: Event,
        stage: str,
        requirement: ComponentRequirement,
    ):
        assert self._request is not None
        resolution = self._resolver.resolve(
            operation=f"daily_flow.{stage}",
            idempotency_identity=self._event_id(event, stage),
            requirements=(requirement,),
            registry=self._registry,
        )
        if resolution.failed:
            for error in resolution.errors:
                publication = self._artifacts.publish_failure(error)
                if publication.status is OutcomeStatus.COMPLETE:
                    self._published.append(publication.result)
            self._errors.extend(resolution.errors)
            return None
        return resolution.bindings[0]

    def _publish_model(
        self,
        *,
        event: Event | None,
        stage: str,
        logical_identity: str,
        artifact_type: str,
        producer_id: str,
        artifact_schema_version: int = 1,
        payload: QlibxModel,
        dependencies: tuple[DependencyEdge, ...] = (),
    ) -> ArtifactEnvelope | None:
        publication = self._artifacts.publish_model(
            logical_identity=logical_identity,
            artifact_type=artifact_type,
            artifact_schema_version=artifact_schema_version,
            producer_id=producer_id,
            payload=payload,
            dependencies=dependencies,
        )
        if publication.status is not OutcomeStatus.COMPLETE:
            failure_event = event or Event(
                "FINALIZE",
                self._clock.now,
                MONITOR_PRIORITY,
            )
            committed = (
                self._event_commits(event)
                if event is not None
                else tuple(self._authority_commits)
            )
            self._fail(
                failure_event,
                stage,
                "ARTIFACT_PUBLICATION_FAILED",
                context={
                    "artifact_type": artifact_type,
                    "logical_identity": logical_identity,
                    "publication_errors": [
                        error.model_dump(mode="json") for error in publication.errors[:5]
                    ],
                },
                committed=committed,
            )
            return None
        self._published.append(publication.result)
        return publication.result

    def _record_authority_commit(
        self,
        event: Event,
        *,
        authority: str,
        event_id: str,
        version: int,
    ) -> None:
        self._authority_commits.append(
            _AuthorityCommit(
                event_name=event.name,
                event_time=event.ts,
                authority=authority,
                event_id=event_id,
                version=version,
            )
        )

    def _event_commits(self, event: Event) -> tuple[_AuthorityCommit, ...]:
        return tuple(
            commit
            for commit in self._authority_commits
            if commit.event_name == event.name and commit.event_time == event.ts
        )

    def _fail(
        self,
        event: Event,
        stage: str,
        code: str,
        *,
        context: dict[str, object] | None = None,
        committed: tuple[_AuthorityCommit, ...] | None = None,
    ) -> None:
        assert self._request is not None
        authoritative_commits = self._event_commits(event) if committed is None else committed
        crossed_commit = bool(authoritative_commits)
        identity = self._event_id(event, stage)
        seed = hashlib.sha256(f"{identity}:{code}".encode()).hexdigest()[:24]
        retry_precondition = (
            "resume from authoritative state at or after the listed committed identities; "
            "do not replay them"
            if crossed_commit
            else "correct the selected profile input and retry from a checkpoint"
        )
        error = OperationError(
            operation="daily_flow.run",
            stage_path=f"daily_flow.{stage}",
            error_code=code,
            context={
                "event_name": event.name,
                "event_time": event.ts.isoformat(),
                "account_version": self._account.snapshot().version,
                "authoritative_commits": [
                    commit.context() for commit in authoritative_commits
                ],
                **(context or {}),
            },
            commit_status=(CommitStatus.COMMITTED if crossed_commit else CommitStatus.NONE),
            retry_preconditions=(retry_precondition,),
            idempotency_identity=identity,
            error_id=f"error-{seed}",
        )
        publication = self._artifacts.publish_failure(error)
        if publication.status is OutcomeStatus.COMPLETE:
            self._published.append(publication.result)
        self._errors.append(error)

    def _event_id(self, event: Event, suffix: str) -> str:
        assert self._request is not None
        timestamp = event.ts.isoformat().replace("+00:00", "Z")
        return f"{self._request.run_id}:{suffix}:{timestamp}"
