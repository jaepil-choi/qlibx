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
from qlibx.evidence import ArtifactEnvelope, DependencyEdge, LocalArtifactBackend
from qlibx.execution import FillDiagnostic, KrxExchange, MarketQuote, Order
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
    checkpoint_schema_version: int = 1
    run_id: str
    event_time: datetime
    account: StateAccessRecord
    account_checkpoint: AccountCheckpoint
    memory_snapshots: tuple[MemorySnapshot, ...] = ()
    event_trace: tuple[str, ...]
    completed_decision_ids: tuple[str, ...]


class DailyExecutionProfile(QlibxModel):
    profile_id: str = "daily.next-session-close.v1"
    convention_id: str = "close-price.v1"
    market_dataset_id: str
    execution_price_role: str = "execution_price"
    valuation_price_role: str = "valuation_price"
    volume_role: str | None = None
    session_timezone: str = "Asia/Seoul"
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
        holdings=tuple(
            StateHolding(
                instrument_id=position.instrument_id,
                quantity=position.quantity,
                mark=position.mark,
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
        self._monitors: list[MonitorEvidence] = []
        self._memory_commits: list[MemoryCommitEvidence] = []
        self._published: list[ArtifactEnvelope] = []
        self._trace: list[str] = []
        self._completed_decisions: list[str] = []
        self._errors: list[OperationError] = []
        self._authority_commits: list[_AuthorityCommit] = []

    def run(
        self,
        strategy: StrategyOperation,
        request: DailyRunRequest,
    ) -> OperationOutcome:
        self._prepare(request, strategy=strategy)
        for timestamp in request.decision_times:
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
            self._clock.schedule(
                Event(
                    "EXECUTION",
                    execution_time,
                    EXECUTION_PRIORITY,
                    _PendingExecution(
                        intent=frozen.intent,
                        intent_artifact=frozen.artifact,
                    ),
                ),
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
        self._executor = NextSessionCloseExecutor(self._profile, request.session_closes)
        for timestamp in request.session_closes:
            normalized = require_aware(timestamp)
            self._clock.schedule(
                Event("MARK", normalized, MARK_PRIORITY),
                self._on_mark,
            )
            self._clock.schedule(
                Event("MONITOR", normalized, MONITOR_PRIORITY),
                self._on_monitor,
            )

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

        if self._errors:
            return OperationOutcome(
                status=OutcomeStatus.FAILED,
                diagnostics=tuple(self._published),
                errors=tuple(self._errors),
            )

        final_account = self._account.snapshot()
        checkpoint = SimulationCheckpoint(
            run_id=request.run_id,
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
        outcome = self._research.invoke_strategy(
            self._strategy,
            invocation,
            account_state=self._account.snapshot(),
            memory_state=self._memory.snapshot(self._strategy.strategy_id),
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
            self._commit_memory(
                event,
                run_result.result,
                run_result.artifact.artifact_id,
            )
            if self._errors:
                return
            self._completed_decisions.append(decision_id)
            return
        if any(weight.weight < 0 for weight in run_result.result.weights):
            self._fail(event, "decision", "SIGNED_TARGET_REQUIRES_CONSTRUCTION")
            return

        snapshot = self._account.snapshot()
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
        self._clock.schedule(
            Event(
                "EXECUTION",
                execution_time,
                EXECUTION_PRIORITY,
                _PendingExecution(
                    intent=intent,
                    intent_artifact=intent_artifact,
                    strategy_result=run_result.result,
                ),
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
        before = self._account.snapshot()
        if before.positions and before.valuation_status.value != "COMPLETE":
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
        if committed_fills:
            try:
                commit = self._account.commit(
                    FillBatch(
                        account_id=before.account_id,
                        event_id=f"{execution_id}:fill",
                        fills=committed_fills,
                    ),
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
            account_after=_state(after),
            limitations=self._profile.limitations,
        )
        published = self._publish_model(
            event=event,
            stage="execution.artifact",
            logical_identity=f"execution-result:{evidence.event_id}",
            artifact_type="execution_result",
            producer_id=self._profile.profile_id,
            payload=evidence,
            dependencies=(
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
            ),
        )
        if published is None:
            return
        if pending.strategy_result is not None:
            self._commit_memory(
                event,
                pending.strategy_result,
                pending.intent.strategy_artifact_id,
            )
            if self._errors:
                return
        self._executions.append(evidence)
        self._completed_decisions.append(pending.intent.decision_id)

    def _on_mark(self, event: Event) -> None:
        before = self._account.snapshot()
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
        try:
            commit = self._account.commit(
                MarkBatch(
                    account_id=before.account_id,
                    event_id=self._event_id(event, "mark"),
                    marks=marks,
                ),
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
        published = self._publish_model(
            event=event,
            stage="mark.artifact",
            logical_identity=f"mark-result:{evidence.event_id}",
            artifact_type="mark_result",
            producer_id=self._profile.profile_id,
            payload=evidence,
            dependencies=(
                DependencyEdge(
                    dependency_kind="dataset",
                    dependency_id=binding.registration_identity,
                    consumer_role=self._profile.valuation_price_role,
                    selected_fields=(binding.field,),
                ),
            ),
        )
        if published is not None:
            self._marks.append(evidence)

    def _on_monitor(self, event: Event) -> None:
        before = self._account.snapshot()
        evidence = MonitorEvidence(
            event_id=self._event_id(event, "monitor"),
            event_time=event.ts,
            account=_state(before),
            account_version_after_callback=self._account.snapshot().version,
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

    def _commit_memory(
        self,
        event: Event,
        result: StrategyResult,
        source_artifact_id: str,
    ) -> None:
        assert self._request is not None
        if result.proposed_memory is None:
            return
        if result.expected_memory_version is None or not result.memory_accesses:
            self._fail(event, "memory", "MEMORY_PROPOSAL_WITHOUT_PRIOR_STATE")
            return
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
            return
        if not result.state_accesses:
            self._fail(event, "memory", "MEMORY_PROPOSAL_WITHOUT_ACTUAL_FEEDBACK")
            return
        feedback_cursor = result.state_accesses[-1].feedback_cursor
        initialization = (
            current.version == 0
            and current.value is None
            and current.feedback_cursor == 0
            and feedback_cursor == 0
        )
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
            return
        try:
            committed = self._memory.commit(
                strategy_id=result.strategy_id,
                value=dict(result.proposed_memory),
                feedback_cursor=feedback_cursor,
                expected_version=result.expected_memory_version,
            )
        except ValueError as exc:
            self._fail(
                event,
                "memory.commit",
                "MEMORY_COMMIT_REJECTED",
                context={"message": str(exc)},
            )
            return
        self._record_authority_commit(
            event,
            authority="memory",
            event_id=(
                f"{self._request.run_id}:{result.strategy_id}:memory:v{committed.version}"
            ),
            version=committed.version,
        )
        evidence = MemoryCommitEvidence(
            strategy_id=result.strategy_id,
            source_artifact_id=source_artifact_id,
            previous_version=current.version,
            version=committed.version,
            feedback_cursor=committed.feedback_cursor,
            update_kind="INITIALIZATION" if initialization else "FEEDBACK_UPDATE",
            value=dict(result.proposed_memory),
        )
        published = self._publish_model(
            event=event,
            stage="memory.artifact",
            logical_identity=(
                f"memory-commit:{self._request.run_id}:{result.strategy_id}:"
                f"v{committed.version}"
            ),
            artifact_type="memory_commit",
            producer_id=result.strategy_id,
            payload=evidence,
            dependencies=(
                DependencyEdge(
                    dependency_kind="artifact",
                    dependency_id=source_artifact_id,
                    consumer_role="proposed_memory",
                ),
                DependencyEdge(
                    dependency_kind="state",
                    dependency_id=(
                        f"account:{result.state_accesses[-1].account_id}:"
                        f"v{result.state_accesses[-1].version}:"
                        f"cursor{feedback_cursor}"
                    ),
                    consumer_role=(
                        "initial_actual_state" if initialization else "confirmed_feedback"
                    ),
                ),
            ),
        )
        if published is not None:
            self._memory_commits.append(evidence)

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
        payload: QlibxModel,
        dependencies: tuple[DependencyEdge, ...] = (),
    ) -> ArtifactEnvelope | None:
        publication = self._artifacts.publish_model(
            logical_identity=logical_identity,
            artifact_type=artifact_type,
            artifact_schema_version=1,
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
