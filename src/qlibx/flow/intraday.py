"""Multi-event execution characterization behind an immutable DecisionIntent."""

import hashlib
import math
from dataclasses import dataclass
from datetime import datetime

from pydantic import Field, model_validator

from qlibx.account import Account, AccountCheckpoint, AccountSnapshot, FillBatch, Mark, MarkBatch
from qlibx.context import StateAccessRecord, StateHolding, ViewGate
from qlibx.data import ComponentRequirement, ObservationStore, RegistrySnapshot, RequirementResolver
from qlibx.domain import Side
from qlibx.errors import CommitStatus, OperationError, OperationOutcome, OutcomeStatus
from qlibx.evidence import ArtifactEnvelope, DependencyEdge, LocalArtifactBackend
from qlibx.execution import KrxExchange, MarketQuote, Order
from qlibx.flow.daily import (
    EXECUTION_PRIORITY,
    ExecutionEvidence,
    FillDiagnosticEvidence,
    FillEvidence,
    FrozenDecision,
    OrderEvidence,
)
from qlibx.kernel import BacktestClock, Event
from qlibx.kernel.clock import require_aware
from qlibx.models import QlibxModel


class IntradayExecutionProfile(QlibxModel):
    """Required market capabilities and declared limitations for one child."""

    profile_id: str = Field(min_length=1)
    market_dataset_id: str = Field(min_length=1)
    execution_price_role: str = "intraday_execution_price"
    volume_role: str = "intraday_volume"
    valuation_price_role: str = "intraday_execution_price"
    convention_id: str = "point-price.v1"
    limitations: tuple[str, ...] = (
        "characterization profile; no order book or latency model",
        "target quantities are frozen from first-event prices",
        "participation capacity resets at each declared event",
    )


class IntradayRunRequest(QlibxModel):
    run_id: str = Field(min_length=1)
    config_fingerprint: str = Field(min_length=1)
    execution_times: tuple[datetime, ...]

    @model_validator(mode="after")
    def validate_schedule(self) -> "IntradayRunRequest":
        normalized = tuple(require_aware(value) for value in self.execution_times)
        if not normalized or normalized != tuple(sorted(set(normalized))):
            raise ValueError("intraday execution_times must be non-empty, unique, and sorted")
        return self


class RemainingTarget(QlibxModel):
    instrument_id: str
    target_quantity: float = Field(ge=0)
    actual_quantity: float = Field(ge=0)
    remaining_quantity: float = Field(ge=0)


class IntradayExecutionEvidence(QlibxModel):
    intraday_schema_version: int = 1
    sequence: int = Field(ge=0)
    execution: ExecutionEvidence
    remaining: tuple[RemainingTarget, ...]
    completes_decision: bool


class IntradayCheckpoint(QlibxModel):
    checkpoint_schema_version: int = 1
    run_id: str
    decision_id: str
    event_time: datetime
    account: StateAccessRecord
    account_checkpoint: AccountCheckpoint
    target_quantities: tuple[tuple[str, float], ...]
    completed_events: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class IntradayRunResult:
    executions: tuple[IntradayExecutionEvidence, ...]
    checkpoint: IntradayCheckpoint
    final_account: AccountSnapshot
    artifacts: tuple[ArtifactEnvelope, ...]


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


class IntradayExecutionFlow:
    """Commit one partial FillBatch per declared event, always from latest actual state."""

    def __init__(
        self,
        *,
        clock: BacktestClock,
        registry: RegistrySnapshot,
        artifacts: LocalArtifactBackend,
        exchange: KrxExchange,
        account: Account,
        profile: IntradayExecutionProfile,
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
        self._bindings = ()
        self._request: IntradayRunRequest | None = None
        self._decision: FrozenDecision | None = None
        self._targets: dict[str, float] = {}
        self._executions: list[IntradayExecutionEvidence] = []
        self._published: list[ArtifactEnvelope] = []
        self._completed_events: list[str] = []
        self._errors: list[OperationError] = []
        self._last_prices: dict[str, float] = {}

    def execute_frozen(
        self,
        decision: FrozenDecision,
        request: IntradayRunRequest,
    ) -> OperationOutcome:
        if self._request is not None:
            raise RuntimeError("IntradayExecutionFlow instances are single-use")
        self._request = request
        self._decision = decision
        if (
            decision.artifact.artifact_type != "decision_intent"
            or decision.artifact.logical_identity
            != f"decision-intent:{decision.intent.decision_id}"
        ):
            return self._fail("PARENT_ARTIFACT_ID_MISMATCH", "intraday.plan.parent")
        if any(
            require_aware(ts) <= decision.intent.decision_time
            for ts in request.execution_times
        ):
            return self._fail("EXECUTION_NOT_AFTER_DECISION", "intraday.plan.schedule")

        requirements = (
            ComponentRequirement(
                requirement_id="intraday.execution_price",
                semantic_role=self._profile.execution_price_role,
                dataset_id=self._profile.market_dataset_id,
            ),
            ComponentRequirement(
                requirement_id="intraday.volume",
                semantic_role=self._profile.volume_role,
                dataset_id=self._profile.market_dataset_id,
            ),
            ComponentRequirement(
                requirement_id="intraday.valuation_price",
                semantic_role=self._profile.valuation_price_role,
                dataset_id=self._profile.market_dataset_id,
            ),
        )
        resolution = self._resolver.resolve(
            operation="intraday.execute",
            idempotency_identity=request.run_id,
            requirements=requirements,
            registry=self._registry,
        )
        if resolution.failed:
            for error in resolution.errors:
                self._artifacts.publish_failure(error)
            return OperationOutcome(status=OutcomeStatus.FAILED, errors=resolution.errors)
        self._bindings = resolution.bindings
        coverage = self._preflight_coverage(request.execution_times)
        if coverage is not None:
            return coverage

        for sequence, timestamp in enumerate(request.execution_times):
            self._clock.schedule(
                Event("INTRADAY_EXECUTION", timestamp, EXECUTION_PRIORITY, sequence),
                self._on_execution,
            )
        while not self._clock.is_finished() and not self._errors:
            for handler in self._clock.advance_to_next():
                handler.callback(handler.event)
                if self._errors:
                    break
        if self._errors:
            return OperationOutcome(status=OutcomeStatus.FAILED, errors=tuple(self._errors))
        return self._finish()

    def _preflight_coverage(
        self,
        execution_times: tuple[datetime, ...],
    ) -> OperationOutcome | None:
        assert self._decision is not None
        required = {target.instrument_id for target in self._decision.intent.targets}
        for timestamp in execution_times:
            for binding in self._bindings:
                dataset = self._registry.get(binding.dataset_id)
                assert dataset is not None
                frame = self._store.query(
                    dataset,
                    field=binding.field,
                    as_of=timestamp,
                    observation_at=timestamp,
                )
                observed = set(frame["instrument"].astype(str))
                if observed != required or len(frame) != len(required):
                    return self._fail(
                        "INTRADAY_COVERAGE_MISSING",
                        "intraday.preflight.coverage",
                        context={
                            "event_time": require_aware(timestamp).isoformat(),
                            "semantic_role": binding.semantic_role,
                            "required": sorted(required),
                            "observed": sorted(observed),
                        },
                    )
        return None

    def _on_execution(self, event: Event) -> None:
        assert self._decision is not None and self._request is not None
        sequence = int(event.payload)
        before = self._account.snapshot()
        view = self._gate.execution_view(
            self._clock,
            self._bindings,
            account_state=before,
        )
        price_frame = view.at(self._profile.execution_price_role, event.ts)
        volume_frame = view.at(self._profile.volume_role, event.ts)
        prices = {
            str(row.instrument): float(getattr(row, self._profile.execution_price_role))
            for row in price_frame.itertuples()
        }
        volumes = {
            str(row.instrument): float(getattr(row, self._profile.volume_role))
            for row in volume_frame.itertuples()
        }
        self._last_prices = prices
        if not self._targets:
            self._targets = {
                target.instrument_id: math.floor(
                    before.nav * target.weight / prices[target.instrument_id]
                )
                for target in self._decision.intent.targets
            }
        holdings = before.holdings()
        orders: list[Order] = []
        for instrument_id, target in sorted(self._targets.items()):
            difference = target - holdings.get(instrument_id, 0)
            orders.append(
                Order(
                    instrument_id=instrument_id,
                    side=Side.BUY if difference >= 0 else Side.SELL,
                    quantity=abs(difference),
                )
            )
        event_id = (
            f"intraday:{self._request.run_id}:{self._decision.intent.decision_id}:{sequence}"
        )
        match = self._exchange.match_batch(
            event_id=event_id,
            event_time=event.ts,
            orders=tuple(orders),
            quotes=tuple(
                MarketQuote(
                    instrument_id=instrument_id,
                    price=prices[instrument_id],
                    available_volume=volumes[instrument_id],
                )
                for instrument_id in sorted(prices)
            ),
            cash=before.cash,
            holdings=holdings,
        )
        if match.status is not OutcomeStatus.COMPLETE:
            self._errors.extend(match.errors)
            return
        committed_fills = tuple(fill for fill in match.result.fills if fill.dealt_quantity > 0)
        after = before
        if committed_fills:
            after = self._account.commit(
                FillBatch(
                    account_id=before.account_id,
                    event_id=event_id,
                    fills=committed_fills,
                ),
                expected_version=before.version,
            ).snapshot
        remaining = self._remaining(after)
        execution = ExecutionEvidence(
            event_id=event_id,
            decision_id=self._decision.intent.decision_id,
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
            fills=tuple(
                FillEvidence(
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
                for fill in match.result.fills
            ),
            diagnostics=tuple(
                FillDiagnosticEvidence(
                    instrument_id=item.instrument_id,
                    requested_quantity=item.requested_quantity,
                    dealt_quantity=item.dealt_quantity,
                    reasons=item.reasons,
                )
                for item in match.result.diagnostics
            ),
            account_before=_state(before),
            account_after=_state(after),
            limitations=self._profile.limitations,
        )
        evidence = IntradayExecutionEvidence(
            sequence=sequence,
            execution=execution,
            remaining=remaining,
            completes_decision=all(item.remaining_quantity <= 1e-12 for item in remaining),
        )
        publication = self._artifacts.publish_model(
            logical_identity=f"intraday-execution:{self._request.run_id}:{sequence}",
            artifact_type="intraday_execution_result",
            artifact_schema_version=1,
            producer_id=self._profile.profile_id,
            payload=evidence,
            dependencies=(
                DependencyEdge(
                    dependency_kind="artifact",
                    dependency_id=self._decision.artifact.artifact_id,
                    consumer_role="decision_intent",
                ),
            ),
        )
        if publication.status is not OutcomeStatus.COMPLETE:
            self._errors.extend(publication.errors)
            return
        self._executions.append(evidence)
        self._published.append(publication.result)
        self._completed_events.append(event_id)

    def _remaining(self, snapshot: AccountSnapshot) -> tuple[RemainingTarget, ...]:
        holdings = snapshot.holdings()
        return tuple(
            RemainingTarget(
                instrument_id=instrument_id,
                target_quantity=target,
                actual_quantity=holdings.get(instrument_id, 0),
                remaining_quantity=max(target - holdings.get(instrument_id, 0), 0),
            )
            for instrument_id, target in sorted(self._targets.items())
        )

    def _finish(self) -> OperationOutcome:
        assert self._request is not None and self._decision is not None
        before_mark = self._account.snapshot()
        held = before_mark.holdings()
        if held:
            marks = tuple(
                Mark(instrument_id=instrument_id, price=self._last_prices[instrument_id])
                for instrument_id in sorted(held)
            )
            event_id = f"intraday-mark:{self._request.run_id}"
            final = self._account.commit(
                MarkBatch(account_id=before_mark.account_id, event_id=event_id, marks=marks),
                expected_version=before_mark.version,
            ).snapshot
        else:
            final = before_mark
        checkpoint = IntradayCheckpoint(
            run_id=self._request.run_id,
            decision_id=self._decision.intent.decision_id,
            event_time=self._clock.now,
            account=_state(final),
            account_checkpoint=self._account.checkpoint(),
            target_quantities=tuple(sorted(self._targets.items())),
            completed_events=tuple(self._completed_events),
        )
        publication = self._artifacts.publish_model(
            logical_identity=f"intraday-checkpoint:{self._request.run_id}",
            artifact_type="intraday_checkpoint",
            artifact_schema_version=1,
            producer_id=self._profile.profile_id,
            payload=checkpoint,
            dependencies=(
                DependencyEdge(
                    dependency_kind="artifact",
                    dependency_id=self._decision.artifact.artifact_id,
                    consumer_role="decision_intent",
                ),
            ),
        )
        if publication.status is not OutcomeStatus.COMPLETE:
            return publication
        self._published.append(publication.result)
        return OperationOutcome(
            status=OutcomeStatus.COMPLETE,
            result=IntradayRunResult(
                executions=tuple(self._executions),
                checkpoint=checkpoint,
                final_account=final,
                artifacts=tuple(self._published),
            ),
        )

    def _fail(
        self,
        code: str,
        stage_path: str,
        *,
        context: dict[str, object] | None = None,
    ) -> OperationOutcome:
        identity = self._request.run_id if self._request is not None else self._profile.profile_id
        seed = hashlib.sha256(f"{identity}:{stage_path}:{code}".encode()).hexdigest()[:24]
        error = OperationError(
            operation="intraday.execute",
            stage_path=stage_path,
            error_code=code,
            context=context or {},
            commit_status=CommitStatus.NONE,
            retry_preconditions=("register complete point-in-time intraday price and volume",),
            idempotency_identity=identity,
            error_id=f"error-{seed}",
        )
        self._artifacts.publish_failure(error)
        return OperationOutcome(status=OutcomeStatus.FAILED, errors=(error,))
