"""Deterministic next-session-close simulation flow."""

import hashlib
import math
from dataclasses import dataclass
from datetime import datetime
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


class SimulationCheckpoint(QlibxModel):
    checkpoint_schema_version: int = 1
    run_id: str
    event_time: datetime
    account: StateAccessRecord
    account_checkpoint: AccountCheckpoint
    event_trace: tuple[str, ...]
    completed_decision_ids: tuple[str, ...]


class DailyExecutionProfile(QlibxModel):
    profile_id: str = "daily.next-session-close.v1"
    convention_id: str = "close-price.v1"
    market_dataset_id: str
    execution_price_role: str = "execution_price"
    valuation_price_role: str = "valuation_price"
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
    checkpoint: SimulationCheckpoint
    final_account: AccountSnapshot
    artifacts: tuple[ArtifactEnvelope, ...]


@dataclass(frozen=True, slots=True)
class _PendingExecution:
    intent: DecisionIntent
    intent_artifact: ArtifactEnvelope


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
    ) -> None:
        self._clock = clock
        self._registry = registry
        self._artifacts = artifacts
        self._exchange = exchange
        self._account = account
        self._profile = profile
        self._resolver = resolver or RequirementResolver()
        self._store = store or ObservationStore()
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
        self._published: list[ArtifactEnvelope] = []
        self._trace: list[str] = []
        self._completed_decisions: list[str] = []
        self._errors: list[OperationError] = []

    def run(
        self,
        strategy: StrategyOperation,
        request: DailyRunRequest,
    ) -> OperationOutcome:
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
        for timestamp in request.decision_times:
            normalized = require_aware(timestamp)
            self._clock.schedule(
                Event("DECISION", normalized, DECISION_PRIORITY),
                self._on_decision,
            )

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
            event_trace=tuple(self._trace),
            completed_decision_ids=tuple(self._completed_decisions),
        )
        checkpoint_artifact = self._publish_model(
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
                _PendingExecution(intent=intent, intent_artifact=intent_artifact),
            ),
            self._on_execution,
        )

    def _on_execution(self, event: Event) -> None:
        if not isinstance(event.payload, _PendingExecution):
            self._fail(event, "execution", "EXECUTION_PAYLOAD_INVALID")
            return
        pending = event.payload
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
        before = self._account.snapshot()
        if before.positions and before.valuation_status.value != "COMPLETE":
            self._fail(event, "execution", "ACCOUNT_VALUATION_INCOMPLETE")
            return
        view = self._gate.execution_view(
            self._clock,
            (binding,),
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
        for instrument in required_instruments:
            target_quantity = target_weights.get(instrument, 0) * before.nav / prices[instrument]
            actual_quantity = holdings.get(instrument, 0)
            delta = target_quantity - actual_quantity
            if delta > 1e-12:
                orders.append(Order(instrument, Side.BUY, delta))
            elif delta < -1e-12:
                orders.append(Order(instrument, Side.SELL, -delta))
        orders.sort(key=lambda order: (0 if order.side is Side.SELL else 1, order.instrument_id))
        match = self._exchange.match_batch(
            event_id=f"{pending.intent.decision_id}:execution",
            event_time=event.ts,
            orders=tuple(orders),
            quotes=tuple(
                MarketQuote(instrument_id=instrument, price=prices[instrument])
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
                        event_id=f"{pending.intent.decision_id}:fill",
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
            after = commit.snapshot
        else:
            after = before
        evidence = ExecutionEvidence(
            event_id=f"{pending.intent.decision_id}:execution",
            decision_id=pending.intent.decision_id,
            event_time=event.ts,
            profile_id=self._profile.profile_id,
            convention_id=self._profile.convention_id,
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
        evidence = MarkEvidence(
            event_id=self._event_id(event, "mark"),
            event_time=event.ts,
            marks=tuple((mark.instrument_id, mark.price) for mark in marks),
            account_before=_state(before),
            account_after=_state(commit.snapshot),
        )
        published = self._publish_model(
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
            self._errors.extend(publication.errors)
            return None
        self._published.append(publication.result)
        return publication.result

    def _fail(
        self,
        event: Event,
        stage: str,
        code: str,
        *,
        context: dict[str, object] | None = None,
    ) -> None:
        assert self._request is not None
        identity = self._event_id(event, stage)
        seed = hashlib.sha256(f"{identity}:{code}".encode()).hexdigest()[:24]
        error = OperationError(
            operation="daily_flow.run",
            stage_path=f"daily_flow.{stage}",
            error_code=code,
            context={
                "event_name": event.name,
                "event_time": event.ts.isoformat(),
                "account_version": self._account.snapshot().version,
                **(context or {}),
            },
            commit_status=CommitStatus.NONE,
            retry_preconditions=("correct the selected profile input and retry from a checkpoint",),
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
