"""Deterministic daily simulation flow."""

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
)
from qlibx.analysis import (
    AnalysisError,
    SessionExecutionInput,
    SessionPerformanceEvidence,
    SessionPerformanceInput,
    SessionPerformanceRequest,
    compute_session_performance,
)
from qlibx.contracts import (
    AccountHistoryRecordingSpec,
    AccountHistoryRequirement,
    DecisionAction,
    EveryCandidate,
    StrategyArtifactBinding,
    StrategyInvocation,
    StrategyOperation,
    TriggerContext,
    TriggerPolicy,
)
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
from qlibx.execution import (
    BaseExchange,
    FillDiagnostic,
    KrxBatchRequest,
    MarketQuote,
    MatchBatchResult,
    SizingPrice,
    SizingTarget,
)
from qlibx.execution.preparation import (
    KRX_PREPARATION_CONTRACT,
    KrxConstraintInput,
    KrxExecutionPreparation,
    KrxPreparationContext,
    KrxPreparationIntent,
)
from qlibx.flow.account_history import (
    AccountHistoryContractError,
    ActualStateHistoryRecorder,
)
from qlibx.flow.artifact_inputs import StrategyArtifactContractRegistry
from qlibx.flow.research import ResearchFlow, StrategyRunResult
from qlibx.flow.strategy_results import StrategyResultPayload
from qlibx.models import QlibxModel
from qlibx.portfolio import BenchmarkWeight, ExecutionLotInput
from qlibx.runtime import BacktestClock, Event
from qlibx.runtime.clock import require_aware
from qlibx.specs.constraints import MvpConstraintPolicy
from qlibx.strategy_state import normalize_strategy_state
from qlibx.view import ExecutionInputProjection, StateAccessRecord, StateHolding, ViewGate

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
    execution_schema_version: Literal[2] = 2
    event_id: str
    decision_id: str
    event_time: datetime
    profile_id: str
    convention_id: str
    exchange_id: str
    exchange_config_fingerprint: str
    preparation_artifact_id: str
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


class MonitorEvidence(QlibxModel):
    event_id: str
    event_time: datetime
    account: StateAccessRecord
    account_version_after_callback: int = Field(ge=0)
    session_performance_status: Literal["published", "skipped_missing_mark"] = "published"


class SimulationCheckpointV2(QlibxModel):
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


class SimulationCheckpointV3(QlibxModel):
    checkpoint_schema_version: Literal[3] = 3
    run_id: str
    request_fingerprint: str
    config_fingerprint: str
    profile_fingerprint: str
    registry_fingerprint: str
    strategy_id: str | None
    event_time: datetime
    initial_account: StateAccessRecord
    account: StateAccessRecord
    account_checkpoint: AccountCheckpoint
    memory_snapshots: tuple[MemorySnapshot, ...] = ()
    event_trace: tuple[str, ...]
    completed_decision_ids: tuple[str, ...]


class SimulationCheckpoint(QlibxModel):
    checkpoint_schema_version: Literal[4] = 4
    run_id: str
    request_fingerprint: str
    config_fingerprint: str
    profile_fingerprint: str
    registry_fingerprint: str
    strategy_id: str | None
    event_time: datetime
    initial_account: StateAccessRecord
    account: StateAccessRecord
    account_checkpoint: AccountCheckpoint
    initial_strategy_state: object = None
    strategy_state: object = None
    event_trace: tuple[str, ...]
    completed_decision_ids: tuple[str, ...]


DECISION_INTENT_CONTRACT = ArtifactContract(
    artifact_type="decision_intent",
    artifact_schema_version=1,
    payload_model=DecisionIntent,
)


class DailyExecutionProfile(QlibxModel):
    profile_id: str = "daily.next-session-close.v1"
    convention_id: str = "close-price.v1"
    execution_timing: Literal["next_session_close", "next_session_open"] = "next_session_close"
    market_dataset_id: str
    execution_price_role: str = "execution_price"
    valuation_price_role: str = "valuation_price"
    volume_role: str | None = None
    session_timezone: str = "Asia/Seoul"
    execution_lots: tuple[tuple[str, float], ...] = ()
    constraint_policy: MvpConstraintPolicy | None = None
    feedback_entry_limit: int = Field(default=256, gt=0)
    limitations: tuple[str, ...] = (
        "single close price for the full cross-sectional batch",
        "intraday path and market impact are not modelled",
        "partial fill is not modelled unless the Exchange has a participation policy",
    )

    def compatibility_json(self) -> str:
        """Preserve the legacy close-profile identity when timing is defaulted."""

        exclude = {"execution_timing"} if self.execution_timing == "next_session_close" else set()
        if not self.execution_lots:
            exclude.add("execution_lots")
        if self.constraint_policy is None:
            exclude.add("constraint_policy")
        return self.model_dump_json(exclude=exclude)


class DailyRunRequest(QlibxModel):
    run_id: str = Field(min_length=1)
    config_fingerprint: str = Field(min_length=1)
    session_closes: tuple[datetime, ...]
    session_opens: tuple[datetime, ...] = ()
    artifact_bindings: tuple[StrategyArtifactBinding, ...] = ()
    account_history: AccountHistoryRecordingSpec = AccountHistoryRecordingSpec()
    initial_strategy_state: object = None

    @model_validator(mode="after")
    def validate_schedule(self) -> "DailyRunRequest":
        sessions = tuple(require_aware(value) for value in self.session_closes)
        opens = tuple(require_aware(value) for value in self.session_opens)
        if sessions != tuple(sorted(set(sessions))):
            raise ValueError("session_closes must be unique and sorted")
        if not sessions:
            raise ValueError("daily flow requires at least one session close")
        if opens != tuple(sorted(set(opens))):
            raise ValueError("session_opens must be unique and sorted")
        binding_roles = [binding.consumer_role for binding in self.artifact_bindings]
        if len(binding_roles) != len(set(binding_roles)):
            raise ValueError("daily Strategy artifact binding roles must be unique")
        normalize_strategy_state(self.initial_strategy_state)
        return self

    def compatibility_json(self) -> str:
        """Preserve the pre-M2 request identity when no artifacts are bound."""

        exclude: set[str] = set()
        if not self.artifact_bindings:
            exclude.add("artifact_bindings")
        if not (
            self.account_history.account_series_fields
            or self.account_history.instrument_panel_fields
        ):
            exclude.add("account_history")
        if not self.session_opens:
            exclude.add("session_opens")
        if self.initial_strategy_state is None:
            exclude.add("initial_strategy_state")
        return self.model_dump_json(exclude=exclude)


@dataclass(frozen=True, slots=True)
class DailyRunResult:
    strategy_results: tuple[StrategyResultPayload, ...]
    decision_intents: tuple[DecisionIntent, ...]
    executions: tuple[ExecutionEvidence, ...]
    marks: tuple[MarkEvidence, ...]
    session_performance: tuple[SessionPerformanceEvidence, ...]
    monitors: tuple[MonitorEvidence, ...]
    initial_strategy_state: object
    final_strategy_state: object
    checkpoint: SimulationCheckpoint
    final_account: AccountSnapshot
    artifacts: tuple[ArtifactEnvelope, ...]


@dataclass(frozen=True, slots=True)
class _PendingExecution:
    intent: DecisionIntent
    intent_artifact: ArtifactEnvelope



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


class NextSessionOpenExecutor:
    """Plan exactly one execution at the first eligible later session open."""

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
                average_cost=position.average_cost,
                realized_pnl=position.realized_pnl,
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
        exchange: BaseExchange[KrxBatchRequest, MatchBatchResult],
        account: Account,
        profile: DailyExecutionProfile,
        preparation: KrxExecutionPreparation | None = None,
        resolver: RequirementResolver | None = None,
        store: ObservationStore | None = None,

        artifact_contracts: StrategyArtifactContractRegistry | None = None,
        strategy_dependencies: tuple[DependencyEdge, ...] = (),
    ) -> None:
        self._clock = clock
        self._registry = registry
        self._artifacts = artifacts
        self._exchange = exchange
        self._account = account
        self._initial_account = _state(account.snapshot(evaluation_time=clock.now))
        self._profile = profile
        self._preparation = preparation or KrxExecutionPreparation()
        self._resolver = resolver or RequirementResolver()
        self._store = store or ObservationStore()
        self._initial_strategy_state: object = None
        self._strategy_state: object = None
        self._feedback_cursor = account.snapshot().feedback_cursor
        self._account_history_recorder: ActualStateHistoryRecorder | None = None
        self._account_history_requirements: tuple[AccountHistoryRequirement, ...] = ()
        self._gate = ViewGate(registry, self._store)
        self._research = ResearchFlow(
            registry=registry,
            artifacts=artifacts,
            resolver=self._resolver,
            store=self._store,
            artifact_contracts=artifact_contracts,
            strategy_dependencies=strategy_dependencies,
        )
        self._request: DailyRunRequest | None = None
        self._strategy: StrategyOperation | None = None
        self._trigger_policy: TriggerPolicy | None = None
        self._trigger_policy_fingerprint = ""
        self._fired_at: list[datetime] = []
        self._candidate_indices: dict[datetime, int] = {}
        self._config_fingerprint = ""
        self._executor: NextSessionCloseExecutor | NextSessionOpenExecutor | None = None
        self._strategy_results: list[StrategyResultPayload] = []
        self._intents: list[DecisionIntent] = []
        self._executions: list[ExecutionEvidence] = []
        self._marks: list[MarkEvidence] = []
        self._session_performance: list[_PublishedSessionPerformance] = []
        self._monitors: list[MonitorEvidence] = []

        self._published: list[ArtifactEnvelope] = []
        self._trace: list[str] = []
        self._completed_decisions: list[str] = []
        self._errors: list[OperationError] = []
        self._authority_commits: list[_AuthorityCommit] = []
        self._pending_executions: dict[str, _PendingExecution] = {}
        # Interrupted-run recovery is outside the current product scope.
        # Final checkpoints remain result evidence, not resume points.
        self._request_fingerprint = ""
        self._profile_fingerprint = ""
        self._registry_fingerprint = ""

    def run(
        self,
        strategy: StrategyOperation,
        request: DailyRunRequest,
    ) -> OperationOutcome:
        self._prepare(request, strategy=strategy)
        if not self._errors:
            for timestamp in request.session_closes:
                normalized = require_aware(timestamp)
                self._clock.schedule(
                    Event("DECISION", normalized, DECISION_PRIORITY),
                    self._on_decision,
                )
        return self._drain(request)

    def execute_frozen(
        self,
        decisions: tuple[FrozenDecision, ...],
        request: DailyRunRequest,
    ) -> OperationOutcome:
        """Execute parent artifacts without importing or rerunning their Strategy."""

        self._prepare(request)
        if self._errors:
            return self._drain(request)
        assert self._executor is not None
        for frozen in decisions:
            if (
                frozen.artifact.artifact_type != "decision_intent"
                or frozen.artifact.logical_identity
                != f"decision-intent:{frozen.intent.decision_id}"
            ):
                self._fail(
                    Event("EXECUTION", frozen.intent.decision_time, EXECUTION_PRIORITY),
                    "execution_plan",
                    "PARENT_ARTIFACT_ID_MISMATCH",
                )
                break
            execution_time = self._executor.plan(frozen.intent)
            if execution_time is None:
                self._fail(
                    Event("EXECUTION", frozen.intent.decision_time, EXECUTION_PRIORITY),
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
            self._clock.schedule(
                Event("EXECUTION", execution_time, EXECUTION_PRIORITY, pending),
                self._on_execution,
            )
        return self._drain(request)
    def _prepare(
        self,
        request: DailyRunRequest,
        *,
        strategy: StrategyOperation | None = None,
    ) -> None:
        if self._request is not None:
            raise RuntimeError("DailyExecutionFlow instances are single-use")
        self._request = request
        self._strategy = strategy
        self._initial_strategy_state = normalize_strategy_state(
            request.initial_strategy_state
        )
        self._strategy_state = self._initial_strategy_state
        self._config_fingerprint = request.config_fingerprint
        if strategy is not None:
            try:
                trigger_method = getattr(strategy, "trigger", None)
                if trigger_method is None:
                    policy: TriggerPolicy = EveryCandidate()
                else:
                    if not callable(trigger_method):
                        raise TypeError("Strategy trigger must be callable")
                    policy = trigger_method()
                if not isinstance(policy.policy_id, str) or not policy.policy_id:
                    raise TypeError("TriggerPolicy.policy_id must be a non-empty string")
                requirements = tuple(policy.requirements())
                if requirements:
                    raise ValueError("schedule-shaped TriggerPolicy requirements must be empty")
                policy_fingerprint = policy.frozen_config_fingerprint()
                if (
                    not isinstance(policy_fingerprint, str)
                    or len(policy_fingerprint) != 64
                    or any(character not in "0123456789abcdef" for character in policy_fingerprint)
                ):
                    raise TypeError(
                        "TriggerPolicy.frozen_config_fingerprint() must return lowercase SHA-256"
                    )
            except Exception as exc:
                self._fail(
                    Event("DECISION", self._clock.now, DECISION_PRIORITY),
                    "decision.trigger.contract",
                    "STRATEGY_TRIGGER_INVALID",
                    context={
                        "exception": type(exc).__name__,
                        "message": str(exc)[:500],
                    },
                )
                return
            self._trigger_policy = policy
            self._trigger_policy_fingerprint = policy_fingerprint
            self._config_fingerprint = self._fingerprint(
                f"{request.config_fingerprint}|trigger:{policy_fingerprint}"
            )
            self._candidate_indices = {
                require_aware(timestamp): index
                for index, timestamp in enumerate(request.session_closes)
            }
        self._account_history_recorder = ActualStateHistoryRecorder(
            request.account_history,
            self._account,
        )
        if strategy is not None:
            try:
                requirements_method = getattr(strategy, "account_history_requirements", None)
                if requirements_method is None:
                    history_requirements: tuple[AccountHistoryRequirement, ...] = ()
                else:
                    if not callable(requirements_method):
                        raise TypeError("account_history_requirements must be callable")
                    history_requirements = tuple(requirements_method())
                    if not all(
                        isinstance(requirement, AccountHistoryRequirement)
                        for requirement in history_requirements
                    ):
                        raise TypeError(
                            "account_history_requirements must return "
                            "AccountHistoryRequirement values"
                        )
                self._account_history_recorder.validate_requirements(history_requirements)
                self._account_history_requirements = history_requirements
            except AccountHistoryContractError as exc:
                self._fail(
                    Event("DECISION", self._clock.now, DECISION_PRIORITY),
                    "decision.account_history.requirements",
                    exc.code,
                    context=exc.context,
                )
                return
            except Exception as exc:
                self._fail(
                    Event("DECISION", self._clock.now, DECISION_PRIORITY),
                    "decision.account_history.requirements",
                    "ACCOUNT_HISTORY_REQUIREMENTS_FAILED",
                    context={
                        "exception": type(exc).__name__,
                        "message": str(exc)[:500],
                    },
                )
                return
        self._request_fingerprint = self._fingerprint(request.compatibility_json())
        self._profile_fingerprint = self._fingerprint(self._profile.compatibility_json())
        self._registry_fingerprint = self._fingerprint(
            "|".join(
                item.registration_identity
                for item in sorted(self._registry.datasets, key=lambda value: value.dataset_id)
            )
        )
        if self._profile.execution_timing == "next_session_open":
            if not request.session_opens:
                self._fail(
                    Event("EXECUTION", self._clock.now, EXECUTION_PRIORITY),
                    "execution_plan",
                    "NEXT_SESSION_OPEN_SCHEDULE_REQUIRED",
                )
                return
            self._executor = NextSessionOpenExecutor(self._profile, request.session_opens)
        else:
            self._executor = NextSessionCloseExecutor(
                self._profile,
                request.session_closes,
            )
        for timestamp in request.session_closes:
            normalized = require_aware(timestamp)
            self._clock.schedule(Event("MARK", normalized, MARK_PRIORITY), self._on_mark)
            self._clock.schedule(Event("MONITOR", normalized, MONITOR_PRIORITY), self._on_monitor)
    def _drain(self, request: DailyRunRequest) -> OperationOutcome:

        while not self._clock.is_finished() and not self._errors:
            for handler in self._clock.advance_to_next():
                self._trace.append(
                    f"{handler.event.ts.isoformat()}|{handler.event.priority}|{handler.event.name}"
                )
                try:
                    handler.callback(handler.event)
                except Exception as exc:
                    self._fail(
                        handler.event,
                        "callback",
                        "DAILY_FLOW_CALLBACK_FAILED",
                        context={
                            "exception": type(exc).__name__,
                            "message": str(exc)[:500],
                        },
                    )
                if self._errors:
                    break


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
            config_fingerprint=self._config_fingerprint,
            profile_fingerprint=self._profile_fingerprint,
            registry_fingerprint=self._registry_fingerprint,
            strategy_id=self._strategy.strategy_id if self._strategy is not None else None,
            event_time=self._clock.now,
            initial_account=self._initial_account,
            account=_state(final_account),
            account_checkpoint=self._account.checkpoint(),
            initial_strategy_state=self._initial_strategy_state,
            strategy_state=self._strategy_state,
            event_trace=tuple(self._trace),
            completed_decision_ids=tuple(self._completed_decisions),
        )
        checkpoint_artifact = self._publish_model(
            event=None,
            stage="checkpoint.artifact",
            logical_identity=f"simulation-checkpoint:{request.run_id}",
            artifact_type="simulation_checkpoint",
            artifact_schema_version=4,
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
                session_performance=tuple(item.record for item in self._session_performance),
                monitors=tuple(self._monitors),
                initial_strategy_state=self._initial_strategy_state,
                final_strategy_state=self._strategy_state,
                checkpoint=checkpoint,
                final_account=final_account,
                artifacts=tuple(self._published),
            ),
        )

    def _execution_inputs_for_decision(
        self,
        decision_time: datetime,
    ) -> tuple[ExecutionInputProjection, ...]:
        if not self._strategy_results:
            return ()
        previous_decision_time = max(result.evaluation_time for result in self._strategy_results)
        envelopes = {
            envelope.logical_identity: envelope
            for envelope in self._published
            if envelope.artifact_type == "execution_result"
        }
        projections: list[ExecutionInputProjection] = []
        for evidence in self._executions:
            if not (previous_decision_time < evidence.event_time <= decision_time):
                continue
            envelope = envelopes.get(f"execution-result:{evidence.event_id}")
            if envelope is None:
                continue
            projections.append(
                ExecutionInputProjection(
                    artifact_id=envelope.artifact_id,
                    artifact_type=envelope.artifact_type,
                    artifact_schema_version=envelope.artifact_schema_version,
                    content_hash=envelope.content_hash,
                    payload=evidence,
                )
            )
        return tuple(sorted(projections, key=lambda item: item.artifact_id))

    def _on_decision(self, event: Event) -> None:
        assert self._request is not None
        assert self._strategy is not None
        assert self._executor is not None
        assert self._trigger_policy is not None
        try:
            trigger = self._trigger_policy.evaluate(
                TriggerContext(
                    candidate_time=event.ts,
                    candidate_index=self._candidate_indices[event.ts],
                    fired_at=tuple(self._fired_at),
                )
            )
            if trigger.policy_id != self._trigger_policy.policy_id:
                raise ValueError("TriggerDecision policy_id does not match its policy")
            if trigger.candidate_time != event.ts:
                raise ValueError("TriggerDecision candidate_time does not match its event")
            if trigger.accesses:
                raise ValueError("schedule-shaped TriggerPolicy must not report data accesses")
        except Exception as exc:
            self._fail(
                event,
                "decision.trigger.evaluate",
                "TRIGGER_EVALUATION_FAILED",
                context={
                    "policy_id": self._trigger_policy.policy_id,
                    "exception": type(exc).__name__,
                    "message": str(exc)[:500],
                },
            )
            return
        self._trace.append(
            f"{event.ts.isoformat()}|TRIGGER|{self._trigger_policy_fingerprint}|"
            f"{trigger.decision}|{trigger.reason}"
        )
        if trigger.decision == "SKIP":
            return
        self._fired_at.append(event.ts)
        decision_id = (
            f"{self._request.run_id}:decision:{event.ts.isoformat().replace('+00:00', 'Z')}"
        )
        invocation = StrategyInvocation(
            invocation_id=decision_id,
            evaluation_time=event.ts,
            config_fingerprint=self._config_fingerprint,
            artifact_bindings=self._request.artifact_bindings,
        )
        account_state = self._account.snapshot(evaluation_time=event.ts)
        try:
            account_feedback = self._account.feedback(
                self._feedback_cursor,
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
            account_history_inputs=tuple(
                self._account_history_recorder.project(requirement)
                for requirement in self._account_history_requirements
            ),
            account_feedback=account_feedback,
            session_performance=(
                self._session_performance[-1] if self._session_performance else None
            ),
            strategy_state=self._strategy_state,
            execution_inputs=self._execution_inputs_for_decision(event.ts),
            additional_dependencies=(
                DependencyEdge(
                    dependency_kind="trigger",
                    dependency_id=self._trigger_policy_fingerprint,
                    consumer_role="decision_cadence",
                ),
            ),
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
        self._strategy_state = run_result.final_strategy_state
        if run_result.result.feedback_accesses:
            self._feedback_cursor = run_result.result.feedback_accesses[-1].next_cursor
        if run_result.result.decision_action is not DecisionAction.TARGET:

            self._completed_decisions.append(decision_id)
            return
        if any(weight.weight < 0 for weight in run_result.result.weights):
            self._fail(event, "decision", "SIGNED_TARGET_REQUIRES_CONSTRUCTION")
            return

        target_gross = sum(weight.weight for weight in run_result.result.weights)
        if target_gross > 1 + 1e-10:
            self._fail(
                event,
                "decision",
                "DAILY_TARGET_BUDGET_UNSUPPORTED",
                context={"target_gross": target_gross, "supported_gross": 1.0},
            )
            return

        snapshot = self._account.snapshot(evaluation_time=event.ts)
        try:
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
        except ValueError as exc:
            self._fail(
                event,
                "decision",
                "DECISION_INTENT_INVALID",
                context={"message": str(exc)[:500]},
            )
            return
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

        )
        self._pending_executions[intent.decision_id] = pending

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
        benchmark_binding = None
        if self._profile.constraint_policy is not None:
            policy = self._profile.constraint_policy
            benchmark_binding = self._resolve(
                event,
                "execution.constraint",
                ComponentRequirement(
                    requirement_id=f"{policy.policy_id}.benchmark_weight",
                    semantic_role=policy.benchmark_weight_role,
                    dataset_id=policy.benchmark_dataset_id,
                ),
            )
            if benchmark_binding is None:
                return
        before = self._account.snapshot(evaluation_time=event.ts)
        if before.positions and before.valuation_status.value == "INCOMPLETE":
            self._fail(event, "execution", "ACCOUNT_VALUATION_INCOMPLETE")
            return
        view = self._gate.execution_view(
            self._clock,
            (
                binding,
                *((volume_binding,) if volume_binding is not None else ()),
                *((benchmark_binding,) if benchmark_binding is not None else ()),
            ),
        )
        session_date = event.ts.astimezone(ZoneInfo(self._profile.session_timezone)).date()
        frame = view.session(
            self._profile.execution_price_role,
            session_date,
            session_timezone=self._profile.session_timezone,
        )
        prices = {
            str(row.instrument): float(getattr(row, self._profile.execution_price_role))
            for row in frame.itertuples()
            if math.isfinite(float(getattr(row, self._profile.execution_price_role)))
            and float(getattr(row, self._profile.execution_price_role)) > 0
        }
        volumes: dict[str, float] = {}
        if volume_binding is not None and self._profile.volume_role is not None:
            volume_frame = view.session(
                self._profile.volume_role,
                session_date,
                session_timezone=self._profile.session_timezone,
            )
            volumes = {
                str(row.instrument): float(getattr(row, self._profile.volume_role))
                for row in volume_frame.itertuples()
                if math.isfinite(float(getattr(row, self._profile.volume_role)))
                and float(getattr(row, self._profile.volume_role)) >= 0
            }
        benchmark: tuple[BenchmarkWeight, ...] = ()
        if self._profile.constraint_policy is not None:
            policy = self._profile.constraint_policy
            benchmark_frame = view.latest(policy.benchmark_weight_role)
            benchmark = tuple(
                BenchmarkWeight(
                    instrument=str(row.instrument),
                    weight=float(getattr(row, policy.benchmark_weight_role)),
                )
                for row in benchmark_frame.itertuples(index=False)
            )
        holdings = before.holdings()
        lot_sizes = dict(self._profile.execution_lots)
        constraint_input = None
        if self._profile.constraint_policy is not None:
            constraint_input = KrxConstraintInput(
                declaration=self._profile.constraint_policy.to_declaration(),
                benchmark=benchmark,
                lots=tuple(
                    ExecutionLotInput(
                        instrument=target.instrument_id,
                        price=prices[target.instrument_id],
                        lot_size=lot_sizes[target.instrument_id],
                        current_quantity=holdings.get(target.instrument_id, 0.0),
                    )
                    for target in pending.intent.targets
                    if target.instrument_id in prices and target.instrument_id in lot_sizes
                ),
                accesses=view.accessed(),
            )
        prepared = self._preparation.prepare(
            KrxPreparationIntent(
                decision_id=pending.intent.decision_id,
                strategy_id=pending.intent.strategy_id,
                targets=tuple(
                    SizingTarget(
                        instrument_id=target.instrument_id,
                        weight=target.weight,
                    )
                    for target in pending.intent.targets
                ),
            ),
            KrxPreparationContext(
                event_id=execution_id,
                event_time=event.ts,
                session_date=session_date,
                sizing_price_role=self._profile.execution_price_role,
                account_state=_state(before),
                prices=tuple(
                    SizingPrice(instrument_id=instrument, price=price)
                    for instrument, price in sorted(prices.items())
                ),
                quotes=tuple(
                    MarketQuote(
                        instrument_id=instrument,
                        price=price,
                        available_volume=volumes.get(instrument),
                    )
                    for instrument, price in sorted(prices.items())
                ),
                exchange_id=self._exchange.exchange_id,
                exchange_config_fingerprint=self._exchange.config_fingerprint,
                constraint=constraint_input,
            ),
        )
        if prepared.status is not OutcomeStatus.COMPLETE:
            self._errors.extend(prepared.errors)
            return
        preparation_dependencies = (
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
            *(
                (
                    DependencyEdge(
                        dependency_kind="dataset",
                        dependency_id=benchmark_binding.registration_identity,
                        consumer_role=(
                            self._profile.constraint_policy.benchmark_weight_role
                            if self._profile.constraint_policy is not None
                            else "benchmark_weight"
                        ),
                        selected_fields=(benchmark_binding.field,),
                    ),
                )
                if benchmark_binding is not None
                else ()
            ),
            DependencyEdge(
                dependency_kind="state",
                dependency_id=(
                    f"account:{before.account_id}:v{before.version}:cursor{before.feedback_cursor}"
                ),
                consumer_role="pre_execution_actual_state",
            ),
        )
        preparation_artifact = self._publish_model(
            event=event,
            stage="execution.preparation.artifact",
            logical_identity=f"krx-execution-preparation:{execution_id}",
            artifact_type=KRX_PREPARATION_CONTRACT.artifact_type,
            artifact_schema_version=KRX_PREPARATION_CONTRACT.artifact_schema_version,
            producer_id="execution.preparation.krx.v1",
            payload=prepared.result.evidence,
            dependencies=preparation_dependencies,
        )
        if preparation_artifact is None:
            return
        orders = prepared.result.request.orders
        sizing_nav = prepared.result.evidence.sizing_nav
        match = self._exchange.match_batch(prepared.result.request)
        if match.status is not OutcomeStatus.COMPLETE:
            self._errors.extend(match.errors)
            return
        if not isinstance(match.result, MatchBatchResult):
            self._fail(
                event,
                "execution.exchange",
                "EXCHANGE_RESULT_TYPE_MISMATCH",
                context={
                    "exchange_id": self._exchange.exchange_id,
                    "expected": "MatchBatchResult",
                    "actual": type(match.result).__name__,
                },
            )
            return
        match_result = match.result
        committed_fills = tuple(fill for fill in match_result.fills if fill.dealt_quantity > 1e-12)
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


        evidence = ExecutionEvidence(
            event_id=execution_id,
            decision_id=pending.intent.decision_id,
            event_time=event.ts,
            profile_id=self._profile.profile_id,
            convention_id=self._profile.convention_id,
            exchange_id=self._exchange.exchange_id,
            exchange_config_fingerprint=self._exchange.config_fingerprint,
            preparation_artifact_id=preparation_artifact.artifact_id,
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
            fills=tuple(_fill(fill) for fill in match_result.fills),
            diagnostics=tuple(
                _diagnostic(diagnostic) for diagnostic in match_result.diagnostics
            ),
            account_before=_state(before),
            account_after=_state(after),
            limitations=self._profile.limitations,
        )
        execution_dependencies = (
            DependencyEdge(
                dependency_kind="artifact",
                dependency_id=preparation_artifact.artifact_id,
                consumer_role="execution_preparation",
            ),
            *preparation_dependencies,
        )
        published = self._publish_model(
            event=event,
            stage="execution.artifact",
            logical_identity=f"execution-result:{evidence.event_id}",
            artifact_type="execution_result",
            producer_id=self._profile.profile_id,
            artifact_schema_version=2,
            payload=evidence,
            dependencies=execution_dependencies,
        )
        if published is None:
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
            published = self._publish_model(
                event=event,
                stage="mark.artifact",
                logical_identity=f"mark-result:{evidence.event_id}",
                artifact_type="mark_result",
                producer_id=self._profile.profile_id,
                payload=evidence,
            )
            if published is not None:
                self._marks.append(evidence)
                assert self._account_history_recorder is not None
                self._account_history_recorder.record(event.ts, self._account)
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
        )
        session_date = event.ts.astimezone(ZoneInfo(self._profile.session_timezone)).date()
        frame = view.session(
            self._profile.valuation_price_role,
            session_date,
            session_timezone=self._profile.session_timezone,
        )
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
        evidence = MarkEvidence(
            event_id=self._event_id(event, "mark"),
            event_time=event.ts,
            marks=tuple((mark.instrument_id, mark.price) for mark in marks),
            account_before=_state(before),
            account_after=_state(commit.snapshot),
        )
        mark_dependencies = (
            DependencyEdge(
                dependency_kind="dataset",
                dependency_id=binding.registration_identity,
                consumer_role=self._profile.valuation_price_role,
                selected_fields=(binding.field,),
            ),
        )
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
            assert self._account_history_recorder is not None
            self._account_history_recorder.record(event.ts, self._account)
    def _on_monitor(self, event: Event) -> None:
        mark = next(
            (item for item in reversed(self._marks) if item.event_time == event.ts),
            None,
        )
        performance_status: Literal["published", "skipped_missing_mark"] = "skipped_missing_mark"
        if mark is not None:
            executions = tuple(item for item in self._executions if item.event_time == event.ts)
            opening = executions[0].account_before if executions else mark.account_before
            closing = mark.account_after
            try:
                performance = compute_session_performance(
                    SessionPerformanceRequest(
                        event_id=self._event_id(event, "session-performance"),
                        event_time=event.ts,
                        source_mark_event_id=mark.event_id,
                        source_execution_event_ids=tuple(item.event_id for item in executions),
                    ),
                    SessionPerformanceInput(
                        opening=opening,
                        closing=closing,
                        executions=tuple(
                            SessionExecutionInput(
                                event_id=execution.event_id,
                                trade_value=sum(abs(fill.trade_value) for fill in execution.fills),
                                transaction_cost=sum(fill.total_cost for fill in execution.fills),
                            )
                            for execution in executions
                        ),
                    ),
                )
            except AnalysisError as exc:
                self._fail(
                    event,
                    "session_performance",
                    exc.code,
                    context=exc.context,
                )
                return
            source_logical_identities = (
                f"mark-result:{mark.event_id}",
                *(f"execution-result:{item.event_id}" for item in executions),
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
            performance_status = "published"

        before = self._account.snapshot(evaluation_time=event.ts)
        evidence = MonitorEvidence(
            event_id=self._event_id(event, "monitor"),
            event_time=event.ts,
            account=_state(before),
            account_version_after_callback=self._account.snapshot(evaluation_time=event.ts).version,
            session_performance_status=performance_status,
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

    @staticmethod
    def _fingerprint(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()


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
                self._event_commits(event) if event is not None else tuple(self._authority_commits)
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
            "discard this failed run result; the listed commits are diagnostic only"
            if crossed_commit
            else "correct the selected profile input and start a new run"
        )
        error = OperationError(
            operation="daily_flow.run",
            stage_path=f"daily_flow.{stage}",
            error_code=code,
            context={
                "event_name": event.name,
                "event_time": event.ts.isoformat(),
                "account_version": self._account.snapshot().version,
                "authoritative_commits": [commit.context() for commit in authoritative_commits],
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
