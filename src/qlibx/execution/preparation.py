"""Execution-time preparation for venue-specific immutable requests."""

from __future__ import annotations

import hashlib
import json
import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime
from typing import Generic, TypeVar

from qlibx.domain import BudgetMode
from qlibx.errors import (
    CommitStatus,
    OperationError,
    OperationOutcome,
    OutcomeStatus,
)
from qlibx.evidence import ArtifactContract
from qlibx.execution.academic import (
    AcademicBatchRequest,
    AcademicPortfolioState,
    AcademicQuote,
    AcademicTargetWeight,
)
from qlibx.execution.krx import (
    KrxBatchRequest,
    MarketQuote,
)
from qlibx.execution.sizing import (
    SessionSizingInput,
    SessionSizingRequest,
    SizingError,
    SizingPrice,
    SizingTarget,
    size_session_orders,
)
from qlibx.models import QlibxModel
from qlibx.portfolio import (
    BenchmarkWeight,
    ConstraintAdjustmentRequest,
    ConstraintAdjustmentResult,
    ConstraintDeclaration,
    ConstraintEvaluationError,
    ConstraintValidationRequest,
    ConstraintValidationResult,
    ConstructionProfile,
    ExecutionLotInput,
    PortfolioConstructionResult,
    PortfolioWeight,
    adjust_single_name_caps,
    validate_single_name_caps,
)
from qlibx.view import AccessRecord, StateAccessRecord

IntentT = TypeVar("IntentT")
ContextT = TypeVar("ContextT")
RequestT = TypeVar("RequestT")
EvidenceT = TypeVar("EvidenceT")
ResultT = TypeVar("ResultT")


@dataclass(frozen=True, slots=True)
class PreparedExecution(Generic[RequestT, EvidenceT]):
    request: RequestT
    evidence: EvidenceT


class ExecutionPreparation(
    ABC,
    Generic[IntentT, ContextT, RequestT, EvidenceT],
):
    """Prepare one immutable Exchange request without committing authority."""

    @abstractmethod
    def prepare(
        self,
        intent: IntentT,
        context: ContextT,
    ) -> OperationOutcome[PreparedExecution[RequestT, EvidenceT]]:
        """Return one request and one evidence bundle, or a typed pre-Exchange failure."""


class KrxPreparationIntent(QlibxModel):
    decision_id: str
    strategy_id: str
    targets: tuple[SizingTarget, ...]


class KrxConstraintInput(QlibxModel):
    declaration: ConstraintDeclaration
    benchmark: tuple[BenchmarkWeight, ...]
    lots: tuple[ExecutionLotInput, ...]
    accesses: tuple[AccessRecord, ...]


class KrxPreparationContext(QlibxModel):
    event_id: str
    event_time: datetime
    session_date: date
    sizing_price_role: str
    account_state: StateAccessRecord
    prices: tuple[SizingPrice, ...]
    quotes: tuple[MarketQuote, ...]
    exchange_id: str
    exchange_config_fingerprint: str
    constraint: KrxConstraintInput | None = None


class PreparedOrderEvidence(QlibxModel):
    instrument_id: str
    side: str
    quantity: float


class PreparedQuoteEvidence(QlibxModel):
    instrument_id: str
    price: float
    available_volume: float | None = None
    total_market_volume: float | None = None


class KrxExecutionPreparationBundle(QlibxModel):
    preparation_schema_version: int = 1
    event_id: str
    event_time: datetime
    decision_id: str
    strategy_id: str
    exchange_id: str
    exchange_config_fingerprint: str
    account_state: StateAccessRecord
    sizing_price_role: str
    constructed_weights: tuple[PortfolioWeight, ...]
    adjusted_weights: tuple[PortfolioWeight, ...]
    constraint_adjustment: ConstraintAdjustmentResult | None = None
    constraint_validation: ConstraintValidationResult | None = None
    compliant: bool | None = None
    sizing_nav: float
    orders: tuple[PreparedOrderEvidence, ...]
    quotes: tuple[PreparedQuoteEvidence, ...]
    request_fingerprint: str


class AcademicPreparationIntent(QlibxModel):
    portfolio_artifact_id: str
    targets: tuple[AcademicTargetWeight, ...]


class AcademicPreparationContext(QlibxModel):
    event_id: str
    event_time: datetime
    state: AcademicPortfolioState
    quotes: tuple[AcademicQuote, ...]
    exchange_id: str
    exchange_config_fingerprint: str


class AcademicExecutionPreparationBundle(QlibxModel):
    preparation_schema_version: int = 1
    event_id: str
    event_time: datetime
    portfolio_artifact_id: str
    exchange_id: str
    exchange_config_fingerprint: str
    state_portfolio_id: str
    state_version: int
    state_event_cursor: int
    targets: tuple[AcademicTargetWeight, ...]
    quote_instruments: tuple[str, ...]
    request_fingerprint: str


KRX_PREPARATION_CONTRACT = ArtifactContract(
    artifact_type="krx_execution_preparation",
    artifact_schema_version=1,
    payload_model=KrxExecutionPreparationBundle,
)

ACADEMIC_PREPARATION_CONTRACT = ArtifactContract(
    artifact_type="academic_execution_preparation",
    artifact_schema_version=1,
    payload_model=AcademicExecutionPreparationBundle,
)


class KrxExecutionPreparation(
    ExecutionPreparation[
        KrxPreparationIntent,
        KrxPreparationContext,
        KrxBatchRequest,
        KrxExecutionPreparationBundle,
    ]
):
    """Construct, optionally constrain, validate, size, and freeze a KRX request."""

    def prepare(
        self,
        intent: KrxPreparationIntent,
        context: KrxPreparationContext,
    ) -> OperationOutcome[
        PreparedExecution[KrxBatchRequest, KrxExecutionPreparationBundle]
    ]:
        constructed = tuple(
            PortfolioWeight(instrument=item.instrument_id, weight=item.weight)
            for item in sorted(intent.targets, key=lambda item: item.instrument_id)
        )
        adjusted = constructed
        adjustment: ConstraintAdjustmentResult | None = None
        validation: ConstraintValidationResult | None = None
        try:
            if context.constraint is not None:
                capital = self._capital(context)
                source = self._constructed_result(intent, context, constructed)
                adjustment = adjust_single_name_caps(
                    ConstraintAdjustmentRequest(
                        invocation_id=f"{context.event_id}:adjust",
                        source_portfolio_artifact_id=(
                            f"preparation:{context.event_id}:constructed"
                        ),
                        evaluation_time=context.event_time,
                        config_fingerprint=context.exchange_config_fingerprint,
                        account_state_identity=(
                            f"account:{context.account_state.account_id}:"
                            f"v{context.account_state.version}"
                        ),
                        capital=capital,
                        lots=context.constraint.lots,
                    ),
                    context.constraint.declaration,
                    source,
                    context.constraint.benchmark,
                    context.constraint.accesses,
                )
                validation = validate_single_name_caps(
                    ConstraintValidationRequest(
                        invocation_id=f"{context.event_id}:validate",
                        adjustment_artifact_id=(
                            f"preparation:{context.event_id}:adjustment"
                        ),
                        evaluation_time=context.event_time,
                        config_fingerprint=context.exchange_config_fingerprint,
                    ),
                    context.constraint.declaration,
                    adjustment,
                    context.constraint.benchmark,
                    context.constraint.accesses,
                )
                adjusted = adjustment.adjusted_weights

            sizing = size_session_orders(
                SessionSizingRequest(
                    session_date=context.session_date,
                    sizing_price_role=context.sizing_price_role,
                    targets=tuple(
                        SizingTarget(
                            instrument_id=item.instrument,
                            weight=item.weight,
                        )
                        for item in adjusted
                    ),
                ),
                SessionSizingInput(
                    account_state=context.account_state,
                    prices=context.prices,
                ),
            )
            quote_by_id = {item.instrument_id: item for item in context.quotes}
            missing_quotes = tuple(
                item
                for item in sizing.required_instruments
                if item not in quote_by_id
            )
            if missing_quotes:
                raise SizingError(
                    "EXECUTION_SESSION_PRICE_MISSING",
                    {
                        "session": str(context.session_date),
                        "instruments": list(missing_quotes[:20]),
                    },
                )
            request = KrxBatchRequest(
                event_id=context.event_id,
                event_time=context.event_time,
                orders=sizing.orders,
                quotes=tuple(
                    quote_by_id[item] for item in sizing.required_instruments
                ),
                cash=context.account_state.cash,
                holdings=tuple(
                    sorted(
                        (
                            item.instrument_id,
                            item.quantity,
                        )
                        for item in context.account_state.holdings
                    )
                ),
            )
        except (ConstraintEvaluationError, SizingError) as exc:
            return self._failure(context.event_id, exc.code, getattr(exc, "context", {}))
        except Exception as exc:
            return self._failure(
                context.event_id,
                "EXECUTION_PREPARATION_FAILED",
                {
                    "exception": type(exc).__name__,
                    "message": str(exc)[:500],
                },
            )

        request_fingerprint = self._krx_request_fingerprint(request)
        evidence = KrxExecutionPreparationBundle(
            event_id=context.event_id,
            event_time=context.event_time,
            decision_id=intent.decision_id,
            strategy_id=intent.strategy_id,
            exchange_id=context.exchange_id,
            exchange_config_fingerprint=context.exchange_config_fingerprint,
            account_state=context.account_state,
            sizing_price_role=context.sizing_price_role,
            constructed_weights=constructed,
            adjusted_weights=adjusted,
            constraint_adjustment=adjustment,
            constraint_validation=validation,
            compliant=validation.compliant if validation is not None else None,
            sizing_nav=sizing.sizing_nav,
            orders=tuple(
                PreparedOrderEvidence(
                    instrument_id=item.instrument_id,
                    side=item.side.value,
                    quantity=item.quantity,
                )
                for item in request.orders
            ),
            quotes=tuple(
                PreparedQuoteEvidence(
                    instrument_id=item.instrument_id,
                    price=item.price,
                    available_volume=item.available_volume,
                    total_market_volume=item.total_market_volume,
                )
                for item in request.quotes
            ),
            request_fingerprint=request_fingerprint,
        )
        return OperationOutcome(
            status=OutcomeStatus.COMPLETE,
            result=PreparedExecution(request=request, evidence=evidence),
        )

    @staticmethod
    def _capital(context: KrxPreparationContext) -> float:
        prices = {
            item.instrument_id: item.price
            for item in context.prices
            if math.isfinite(item.price) and item.price > 0
        }
        missing = tuple(
            item.instrument_id
            for item in context.account_state.holdings
            if item.instrument_id not in prices
        )
        if missing:
            raise SizingError(
                "EXECUTION_SESSION_PRICE_MISSING",
                {
                    "session": str(context.session_date),
                    "instruments": list(missing[:20]),
                },
            )
        capital = context.account_state.cash + sum(
            item.quantity * prices[item.instrument_id]
            for item in context.account_state.holdings
        )
        if not math.isfinite(capital) or capital <= 0:
            raise SizingError(
                "EXECUTION_SIZING_NAV_INVALID",
                {"sizing_nav": capital},
            )
        return capital

    @staticmethod
    def _constructed_result(
        intent: KrxPreparationIntent,
        context: KrxPreparationContext,
        weights: tuple[PortfolioWeight, ...],
    ) -> PortfolioConstructionResult:
        gross = sum(abs(item.weight) for item in weights)
        net = sum(item.weight for item in weights)
        return PortfolioConstructionResult(
            invocation_id=f"{context.event_id}:construct",
            source_artifact_id=f"decision:{intent.decision_id}",
            source_strategy_id=intent.strategy_id,
            evaluation_time=context.event_time,
            profile=ConstructionProfile.EQUITY_LONG_ONLY,
            original_weights=weights,
            target_weights=weights,
            requested_budget=1.0,
            realized_gross=gross,
            realized_net=net,
            cash_residual=max(0.0, 1.0 - gross),
            diagnostics=("daily DecisionIntent is already a physical long-only target",),
            source_budget_mode=BudgetMode.FIXED,
            source_target_gross=1.0,
            requested_budget_mode=BudgetMode.FLEXIBLE,
            normalization_policy="preserve_source_residual",
        )

    @staticmethod
    def _krx_request_fingerprint(request: KrxBatchRequest) -> str:
        payload = {
            "event_id": request.event_id,
            "event_time": request.event_time.isoformat(),
            "orders": [
                {
                    "instrument_id": item.instrument_id,
                    "side": item.side.value,
                    "quantity": item.quantity,
                }
                for item in request.orders
            ],
            "quotes": [
                {
                    "instrument_id": item.instrument_id,
                    "price": item.price,
                    "available_volume": item.available_volume,
                    "total_market_volume": item.total_market_volume,
                }
                for item in request.quotes
            ],
            "cash": request.cash,
            "holdings": list(request.holdings),
        }
        return _fingerprint(payload)

    @staticmethod
    def _failure(
        event_id: str,
        code: str,
        context: dict[str, object],
    ) -> OperationOutcome[PreparedExecution[KrxBatchRequest, KrxExecutionPreparationBundle]]:
        return OperationOutcome(
            status=OutcomeStatus.FAILED,
            errors=(
                _preparation_error(
                    event_id=event_id,
                    code=code,
                    context=context,
                    stage="execution.preparation.krx",
                ),
            ),
        )


class AcademicExecutionPreparation(
    ExecutionPreparation[
        AcademicPreparationIntent,
        AcademicPreparationContext,
        AcademicBatchRequest,
        AcademicExecutionPreparationBundle,
    ]
):
    """Freeze one hypothetical signed request without importing KRX semantics."""

    def prepare(
        self,
        intent: AcademicPreparationIntent,
        context: AcademicPreparationContext,
    ) -> OperationOutcome[
        PreparedExecution[
            AcademicBatchRequest,
            AcademicExecutionPreparationBundle,
        ]
    ]:
        try:
            request = AcademicBatchRequest(
                event_id=context.event_id,
                event_time=context.event_time,
                targets=intent.targets,
                quotes=context.quotes,
                state=context.state,
            )
            request_fingerprint = _fingerprint(
                {
                    "event_id": request.event_id,
                    "event_time": request.event_time.isoformat(),
                    "targets": [
                        item.model_dump(mode="json") for item in request.targets
                    ],
                    "quotes": [
                        item.model_dump(mode="json") for item in request.quotes
                    ],
                    "state": request.state.model_dump(mode="json"),
                }
            )
            evidence = AcademicExecutionPreparationBundle(
                event_id=context.event_id,
                event_time=context.event_time,
                portfolio_artifact_id=intent.portfolio_artifact_id,
                exchange_id=context.exchange_id,
                exchange_config_fingerprint=context.exchange_config_fingerprint,
                state_portfolio_id=context.state.portfolio_id,
                state_version=context.state.version,
                state_event_cursor=context.state.event_cursor,
                targets=intent.targets,
                quote_instruments=tuple(
                    sorted(item.instrument_id for item in context.quotes)
                ),
                request_fingerprint=request_fingerprint,
            )
        except Exception as exc:
            return OperationOutcome(
                status=OutcomeStatus.FAILED,
                errors=(
                    _preparation_error(
                        event_id=context.event_id,
                        code="ACADEMIC_EXECUTION_PREPARATION_FAILED",
                        context={
                            "exception": type(exc).__name__,
                            "message": str(exc)[:500],
                        },
                        stage="execution.preparation.academic",
                    ),
                ),
            )
        return OperationOutcome(
            status=OutcomeStatus.COMPLETE,
            result=PreparedExecution(request=request, evidence=evidence),
        )


def _fingerprint(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _preparation_error(
    *,
    event_id: str,
    code: str,
    context: dict[str, object],
    stage: str,
) -> OperationError:
    seed = hashlib.sha256(f"{event_id}:{code}".encode()).hexdigest()
    return OperationError(
        operation="execution.prepare",
        stage_path=stage,
        error_code=code,
        context=context,
        commit_status=CommitStatus.NONE,
        retry_preconditions=(
            "provide complete execution-time prices, lots, and selected constraint inputs",
        ),
        idempotency_identity=event_id,
        error_id=f"error-{seed[:24]}",
    )
