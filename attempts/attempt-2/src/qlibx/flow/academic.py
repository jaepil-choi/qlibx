"""Artifact-backed execution of frozen hypothetical signed portfolios."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

import pandas as pd
from pydantic import Field

from qlibx.data.registry import RegistrySnapshot
from qlibx.data.store import DataSnapshotError, ObservationStore
from qlibx.errors import CommitStatus, OperationOutcome, OutcomeStatus
from qlibx.evidence import ArtifactContract, DependencyEdge, LocalArtifactBackend
from qlibx.execution.academic import (
    AcademicBatchRequest,
    AcademicExchangeProfile,
    AcademicInstrumentListing,
    AcademicMatchResult,
    AcademicPortfolioSnapshot,
    AcademicPortfolioState,
    AcademicQuote,
    AcademicTargetWeight,
)
from qlibx.execution.base import BaseExchange
from qlibx.execution.preparation import (
    ACADEMIC_PREPARATION_CONTRACT,
    AcademicExecutionPreparation,
    AcademicPreparationContext,
    AcademicPreparationIntent,
)
from qlibx.flow.failures import (
    build_operation_error,
    publish_failed_errors,
    publish_failed_outcome,
)
from qlibx.flow.portfolio import PORTFOLIO_RESULT_CONTRACT
from qlibx.models import QlibxModel
from qlibx.portfolio import ConstructionProfile, PortfolioConstructionResult
from qlibx.specs.academic import AcademicRunSpec

ACADEMIC_LIMITATIONS = (
    "hypothetical research execution only; not an executable market order",
    "borrow, locate, collateral, margin, recalls, and short-proceeds constraints are absent",
    "tax, transaction cost, slippage, market impact, borrow cost, and liquidity limits are zero",
    "fractional quantities and full fills are assumed",
    "dividends, corporate actions, financing rates, and FX are not modelled",
)


class AcademicExecutionResult(QlibxModel):
    execution_schema_version: Literal[2] = 2
    run_id: str = Field(min_length=1)
    config_fingerprint: str = Field(min_length=1)
    exchange_id: str = Field(min_length=1)
    exchange_config_fingerprint: str = Field(min_length=1)
    preparation_artifact_id: str = Field(min_length=1)
    execution_index: int = Field(ge=0)
    event_id: str = Field(min_length=1)
    event_time: datetime
    portfolio_artifact_id: str = Field(min_length=1)
    portfolio_evaluation_time: datetime
    source_requested_budget: float = Field(gt=0)
    source_realized_gross: float = Field(ge=0)
    source_realized_net: float
    profile: AcademicExchangeProfile
    listings: tuple[AcademicInstrumentListing, ...] = Field(min_length=1)
    match: AcademicMatchResult
    limitations: tuple[str, ...] = ACADEMIC_LIMITATIONS


class AcademicCheckpoint(QlibxModel):
    checkpoint_schema_version: Literal[2] = 2
    run_id: str = Field(min_length=1)
    config_fingerprint: str = Field(min_length=1)
    completed_count: int = Field(ge=1)
    completed_portfolio_artifact_ids: tuple[str, ...] = Field(min_length=1)
    execution_artifact_ids: tuple[str, ...] = Field(min_length=1)

    state: AcademicPortfolioState
    snapshot: AcademicPortfolioSnapshot


class AcademicRunResult(QlibxModel):
    result_schema_version: Literal[1] = 1
    run_id: str = Field(min_length=1)
    config_fingerprint: str = Field(min_length=1)
    profile: AcademicExchangeProfile
    listings: tuple[AcademicInstrumentListing, ...] = Field(min_length=1)
    portfolio_artifact_ids: tuple[str, ...] = Field(min_length=1)
    execution_artifact_ids: tuple[str, ...] = Field(min_length=1)
    final_checkpoint_artifact_id: str = Field(min_length=1)
    final_state: AcademicPortfolioState
    final_snapshot: AcademicPortfolioSnapshot
    total_turnover: float = Field(ge=0)
    total_cost: Literal[0.0] = 0.0
    limitations: tuple[str, ...] = ACADEMIC_LIMITATIONS


ACADEMIC_EXECUTION_CONTRACT = ArtifactContract(
    artifact_type="academic_execution_result",
    artifact_schema_version=2,
    payload_model=AcademicExecutionResult,
)

ACADEMIC_CHECKPOINT_CONTRACT = ArtifactContract(
    artifact_type="academic_checkpoint",
    artifact_schema_version=2,
    payload_model=AcademicCheckpoint,
)

ACADEMIC_RUN_RESULT_CONTRACT = ArtifactContract(
    artifact_type="academic_run_result",
    artifact_schema_version=1,
    payload_model=AcademicRunResult,
)


@dataclass(frozen=True, slots=True)
class _FrozenPortfolio:
    artifact_id: str
    payload: PortfolioConstructionResult
    execution_time: datetime


class _AcademicFlowError(ValueError):
    def __init__(self, code: str, stage: str, context: dict[str, object]) -> None:
        self.code = code
        self.stage = stage
        self.context = context
        super().__init__(code)


class AcademicExecutionFlow:
    """Serialize immutable academic execution results and signed state checkpoints."""

    def __init__(
        self,
        *,
        registry: RegistrySnapshot,
        artifacts: LocalArtifactBackend,
        store: ObservationStore,
        exchange: BaseExchange[AcademicBatchRequest, AcademicMatchResult],
        preparation: AcademicExecutionPreparation | None = None,
    ) -> None:
        self._registry = registry
        self._artifacts = artifacts
        self._store = store
        self._exchange = exchange
        self._preparation = preparation or AcademicExecutionPreparation()

    def run(self, spec: AcademicRunSpec) -> OperationOutcome:
        fingerprint = hashlib.sha256(
            (
                f"{spec.frozen_config_fingerprint()}|"
                f"exchange:{self._exchange.exchange_id}|"
                f"exchange-config:{self._exchange.config_fingerprint}"
            ).encode()
        ).hexdigest()
        try:
            portfolios = self._load_portfolios(spec)
            self._validate_listings(spec)
            state = AcademicPortfolioState.seed(spec)
            execution_ids: tuple[str, ...] = ()
            total_turnover = 0.0
        except _AcademicFlowError as exc:
            return self._failure(
                spec,
                exc.code,
                exc.stage,
                exc.context,
                committed=False,
            )

        last_snapshot: AcademicPortfolioSnapshot | None = None
        for index, frozen in enumerate(portfolios):
            event_id = f"academic:{spec.run_id}:{index:08d}"
            targets = tuple(
                AcademicTargetWeight(
                    instrument_id=item.instrument,
                    weight=item.weight,
                )
                for item in frozen.payload.target_weights
            )
            required = set(item.instrument_id for item in targets) | {
                item.instrument_id for item in state.positions if item.quantity != 0
            }
            try:
                quotes = self._load_quotes(
                    spec=spec,
                    event_time=frozen.execution_time,
                    required_instruments=required,
                )
            except _AcademicFlowError as exc:
                return self._failure(
                    spec,
                    exc.code,
                    exc.stage,
                    exc.context,
                    committed=state.version > 0,
                )
            prepared = self._preparation.prepare(
                AcademicPreparationIntent(
                    portfolio_artifact_id=frozen.artifact_id,
                    targets=targets,
                ),
                AcademicPreparationContext(
                    event_id=event_id,
                    event_time=frozen.execution_time,
                    state=state,
                    quotes=quotes,
                    exchange_id=self._exchange.exchange_id,
                    exchange_config_fingerprint=self._exchange.config_fingerprint,
                ),
            )
            if prepared.status is not OutcomeStatus.COMPLETE:
                errors = tuple(
                    error.model_copy(
                        update={
                            "commit_status": (
                                CommitStatus.COMMITTED
                                if state.version > 0
                                else CommitStatus.NONE
                            )
                        }
                    )
                    for error in prepared.errors
                )
                return publish_failed_errors(self._artifacts, errors)
            preparation_dependencies = self._execution_dependencies(
                spec=spec,
                frozen=frozen,
                quotes=quotes,
            )
            preparation_publication = self._artifacts.publish_model(
                logical_identity=(
                    f"academic-execution-preparation:{spec.run_id}:{index:08d}"
                ),
                artifact_type=ACADEMIC_PREPARATION_CONTRACT.artifact_type,
                artifact_schema_version=(
                    ACADEMIC_PREPARATION_CONTRACT.artifact_schema_version
                ),
                producer_id="execution.preparation.academic.v1",
                payload=prepared.result.evidence,
                dependencies=preparation_dependencies,
            )
            if preparation_publication.status is not OutcomeStatus.COMPLETE:
                return preparation_publication
            match = self._exchange.match_batch(prepared.result.request)
            if match.status is not OutcomeStatus.COMPLETE:
                errors = tuple(
                    error.model_copy(
                        update={
                            "commit_status": (
                                CommitStatus.COMMITTED
                                if state.version > 0
                                else CommitStatus.NONE
                            )
                        }
                    )
                    for error in match.errors
                )
                return publish_failed_errors(self._artifacts, errors)
            if not isinstance(match.result, AcademicMatchResult):
                return self._failure(
                    spec,
                    "EXCHANGE_RESULT_TYPE_MISMATCH",
                    "academic.run.exchange",
                    {
                        "exchange_id": self._exchange.exchange_id,
                        "expected": "AcademicMatchResult",
                        "actual": type(match.result).__name__,
                    },
                    committed=state.version > 0,
                )
            selected = match.result
            execution = AcademicExecutionResult(
                run_id=spec.run_id,
                config_fingerprint=fingerprint,
                exchange_id=self._exchange.exchange_id,
                exchange_config_fingerprint=self._exchange.config_fingerprint,
                preparation_artifact_id=preparation_publication.result.artifact_id,
                execution_index=index,
                event_id=event_id,
                event_time=frozen.execution_time,
                portfolio_artifact_id=frozen.artifact_id,
                portfolio_evaluation_time=frozen.payload.evaluation_time,
                source_requested_budget=frozen.payload.requested_budget,
                source_realized_gross=frozen.payload.realized_gross,
                source_realized_net=frozen.payload.realized_net,
                profile=spec.profile,
                listings=tuple(
                    listing
                    for listing in spec.listings
                    if listing.instrument_id
                    in {quote.instrument_id for quote in selected.quotes}
                ),
                match=selected,
            )
            execution_publication = self._artifacts.publish_model(
                logical_identity=f"academic-execution:{spec.run_id}:{index:08d}",
                artifact_type=ACADEMIC_EXECUTION_CONTRACT.artifact_type,
                artifact_schema_version=ACADEMIC_EXECUTION_CONTRACT.artifact_schema_version,
                producer_id="academic.zero-friction.signed-fractional.v1",
                payload=execution,
                dependencies=(
                    DependencyEdge(
                        dependency_kind="artifact",
                        dependency_id=preparation_publication.result.artifact_id,
                        consumer_role="execution_preparation",
                    ),
                    *preparation_dependencies,
                ),
            )
            if execution_publication.status is not OutcomeStatus.COMPLETE:
                return execution_publication
            execution_ids = (*execution_ids, execution_publication.result.artifact_id)
            state = selected.state
            last_snapshot = selected.after
            total_turnover += selected.turnover
        if last_snapshot is None:
            return self._failure(
                spec,
                "ACADEMIC_RUN_EMPTY",
                "academic.run.finalize",
                {},
                committed=False,
            )
        checkpoint = AcademicCheckpoint(
            run_id=spec.run_id,
            config_fingerprint=fingerprint,
            completed_count=len(portfolios),
            completed_portfolio_artifact_ids=tuple(
                item.artifact_id for item in portfolios
            ),
            execution_artifact_ids=execution_ids,
            state=state,
            snapshot=last_snapshot,
        )
        checkpoint_publication = self._artifacts.publish_model(
            logical_identity=f"academic-checkpoint:{spec.run_id}",
            artifact_type=ACADEMIC_CHECKPOINT_CONTRACT.artifact_type,
            artifact_schema_version=ACADEMIC_CHECKPOINT_CONTRACT.artifact_schema_version,
            producer_id="academic.portfolio-state.v1",
            payload=checkpoint,
            dependencies=(
                *(
                    DependencyEdge(
                        dependency_kind="artifact",
                        dependency_id=artifact_id,
                        consumer_role="committed_execution",
                    )
                    for artifact_id in execution_ids
                ),
                DependencyEdge(
                    dependency_kind="config",
                    dependency_id=fingerprint,
                    consumer_role="academic_run_config",
                ),
            ),
        )
        if checkpoint_publication.status is not OutcomeStatus.COMPLETE:
            return checkpoint_publication
        checkpoint_envelope_id = checkpoint_publication.result.artifact_id
        result = AcademicRunResult(
            run_id=spec.run_id,
            config_fingerprint=fingerprint,
            profile=spec.profile,
            listings=spec.listings,
            portfolio_artifact_ids=spec.portfolio_artifact_ids,
            execution_artifact_ids=execution_ids,
            final_checkpoint_artifact_id=checkpoint_envelope_id,
            final_state=state,
            final_snapshot=last_snapshot,
            total_turnover=total_turnover,
        )
        run_publication = self._artifacts.publish_model(
            logical_identity=f"academic-run:{spec.run_id}",
            artifact_type=ACADEMIC_RUN_RESULT_CONTRACT.artifact_type,
            artifact_schema_version=ACADEMIC_RUN_RESULT_CONTRACT.artifact_schema_version,
            producer_id="academic.execution-flow.v1",
            payload=result,
            dependencies=(
                *(
                    DependencyEdge(
                        dependency_kind="artifact",
                        dependency_id=artifact_id,
                        consumer_role="academic_execution",
                    )
                    for artifact_id in execution_ids
                ),
                DependencyEdge(
                    dependency_kind="state",
                    dependency_id=checkpoint_envelope_id,
                    consumer_role="final_academic_checkpoint",
                ),
                DependencyEdge(
                    dependency_kind="config",
                    dependency_id=fingerprint,
                    consumer_role="academic_run_config",
                ),
            ),
        )
        if run_publication.status is not OutcomeStatus.COMPLETE:
            return run_publication
        return OperationOutcome(
            status=OutcomeStatus.COMPLETE,
            result=result,
            diagnostics=(run_publication.result,),
        )

    def _load_portfolios(self, spec: AcademicRunSpec) -> tuple[_FrozenPortfolio, ...]:
        loaded: list[tuple[str, PortfolioConstructionResult]] = []
        for artifact_id in spec.portfolio_artifact_ids:
            outcome = self._artifacts.load_model(artifact_id, PORTFOLIO_RESULT_CONTRACT)
            if outcome.status is not OutcomeStatus.COMPLETE:
                raise _AcademicFlowError(
                    "ACADEMIC_PORTFOLIO_ARTIFACT_UNAVAILABLE",
                    "academic.run.portfolio.load",
                    {"artifact_id": artifact_id},
                )
            payload = outcome.result.payload
            if payload.profile is not ConstructionProfile.HYPOTHETICAL_SIGNED:
                raise _AcademicFlowError(
                    "ACADEMIC_PORTFOLIO_PROFILE_UNSUPPORTED",
                    "academic.run.portfolio.validate",
                    {
                        "artifact_id": artifact_id,
                        "profile": payload.profile.value,
                    },
                )
            if payload.evaluation_time.tzinfo is None:
                raise _AcademicFlowError(
                    "ACADEMIC_PORTFOLIO_TIME_NAIVE",
                    "academic.run.portfolio.validate",
                    {"artifact_id": artifact_id},
                )
            loaded.append((artifact_id, payload))
        times = tuple(payload.evaluation_time for _, payload in loaded)
        if times != tuple(sorted(set(times))):
            raise _AcademicFlowError(
                "ACADEMIC_PORTFOLIO_ORDER_INVALID",
                "academic.run.portfolio.validate",
                {},
            )
        frozen = tuple(
            _FrozenPortfolio(
                artifact_id=artifact_id,
                payload=payload,
                execution_time=self._next_session_close(
                    payload.evaluation_time,
                    spec.session_closes,
                ),
            )
            for artifact_id, payload in loaded
        )
        execution_times = tuple(item.execution_time for item in frozen)
        if execution_times != tuple(sorted(set(execution_times))):
            raise _AcademicFlowError(
                "ACADEMIC_EXECUTION_SCHEDULE_COLLISION",
                "academic.run.schedule",
                {},
            )
        return frozen

    def _validate_listings(self, spec: AcademicRunSpec) -> None:
        for listing in spec.listings:
            dataset = self._registry.get(listing.dataset_id)
            if dataset is None:
                raise _AcademicFlowError(
                    "ACADEMIC_DATASET_NOT_REGISTERED",
                    "academic.run.listings",
                    {
                        "instrument_id": listing.instrument_id,
                        "dataset_id": listing.dataset_id,
                    },
                )
            if listing.price_role not in dataset.bindings:
                raise _AcademicFlowError(
                    "ACADEMIC_PRICE_ROLE_NOT_REGISTERED",
                    "academic.run.listings",
                    {
                        "instrument_id": listing.instrument_id,
                        "dataset_id": listing.dataset_id,
                        "price_role": listing.price_role,
                    },
                )
            if dataset.observation_time_field is None:
                raise _AcademicFlowError(
                    "ACADEMIC_OBSERVATION_TIME_REQUIRED",
                    "academic.run.listings",
                    {"dataset_id": listing.dataset_id},
                )

    def _load_quotes(
        self,
        *,
        spec: AcademicRunSpec,
        event_time: datetime,
        required_instruments: set[str],
    ) -> tuple[AcademicQuote, ...]:
        listing_by_id = {item.instrument_id: item for item in spec.listings}
        missing = sorted(required_instruments - set(listing_by_id))
        if missing:
            raise _AcademicFlowError(
                "ACADEMIC_LISTING_MISSING",
                "academic.run.quotes",
                {"instrument_ids": missing},
            )
        grouped: dict[tuple[str, str], list[AcademicInstrumentListing]] = {}
        for instrument_id in sorted(required_instruments):
            listing = listing_by_id[instrument_id]
            grouped.setdefault((listing.dataset_id, listing.price_role), []).append(listing)

        quotes: list[AcademicQuote] = []
        for (dataset_id, price_role), listings in sorted(grouped.items()):
            dataset = self._registry.get(dataset_id)
            if dataset is None or price_role not in dataset.bindings:
                raise _AcademicFlowError(
                    "ACADEMIC_PRICE_BINDING_STALE",
                    "academic.run.quotes",
                    {"dataset_id": dataset_id, "price_role": price_role},
                )
            selected_field = dataset.bindings[price_role]
            try:
                frame = self._store.query(
                    dataset,
                    field=selected_field,
                    as_of=event_time,
                    observation_at=event_time,
                )
            except (DataSnapshotError, ValueError) as exc:
                raise _AcademicFlowError(
                    "ACADEMIC_PRICE_SNAPSHOT_INVALID",
                    "academic.run.quotes",
                    {
                        "dataset_id": dataset_id,
                        "message": str(exc)[:500],
                    },
                ) from exc
            for listing in listings:
                selected = frame.loc[frame["instrument"] == listing.instrument_id]
                if len(selected) != 1:
                    raise _AcademicFlowError(
                        "ACADEMIC_QUOTE_NOT_EXACT",
                        "academic.run.quotes",
                        {
                            "instrument_id": listing.instrument_id,
                            "event_time": event_time.isoformat(),
                            "row_count": len(selected),
                        },
                    )
                row = selected.iloc[0]
                try:
                    price = float(row["value"])
                except (TypeError, ValueError) as exc:
                    raise _AcademicFlowError(
                        "ACADEMIC_QUOTE_INVALID",
                        "academic.run.quotes",
                        {"instrument_id": listing.instrument_id},
                    ) from exc
                if not math.isfinite(price) or price <= 0:
                    raise _AcademicFlowError(
                        "ACADEMIC_QUOTE_INVALID",
                        "academic.run.quotes",
                        {"instrument_id": listing.instrument_id, "price": price},
                    )
                quotes.append(
                    AcademicQuote(
                        instrument_id=listing.instrument_id,
                        event_time=event_time,
                        price=price,
                        dataset_id=dataset.dataset_id,
                        registration_identity=dataset.registration_identity,
                        physical_fingerprint=dataset.physical_fingerprint,
                        price_role=price_role,
                        selected_field=selected_field,
                        observation_time=self._as_datetime(row["observation_time"]),
                        available_at=self._as_datetime(row["available_at"]),
                    )
                )
        return tuple(sorted(quotes, key=lambda item: item.instrument_id))

    @staticmethod
    def _next_session_close(
        evaluation_time: datetime,
        session_closes: tuple[datetime, ...],
    ) -> datetime:
        for close in session_closes:
            local_evaluation = evaluation_time.astimezone(close.tzinfo)
            if close.date() > local_evaluation.date():
                return close
        raise _AcademicFlowError(
            "ACADEMIC_NEXT_SESSION_CLOSE_MISSING",
            "academic.run.schedule",
            {"evaluation_time": evaluation_time.isoformat()},
        )

    @staticmethod
    def _as_datetime(value: object) -> datetime:
        if isinstance(value, pd.Timestamp):
            return value.to_pydatetime()
        if isinstance(value, datetime):
            return value
        raise _AcademicFlowError(
            "ACADEMIC_QUOTE_TIME_INVALID",
            "academic.run.quotes",
            {"value_type": type(value).__name__},
        )

    @staticmethod
    def _execution_dependencies(
        *,
        spec: AcademicRunSpec,
        frozen: _FrozenPortfolio,
        quotes: tuple[AcademicQuote, ...],
        # No interrupted-run checkpoint input in the current scope.
    ) -> tuple[DependencyEdge, ...]:
        dependencies = [
            DependencyEdge(
                dependency_kind="artifact",
                dependency_id=frozen.artifact_id,
                consumer_role="signed_portfolio",
            ),
            DependencyEdge(
                dependency_kind="config",
                dependency_id=spec.frozen_config_fingerprint(),
                consumer_role="academic_run_config",
            ),
        ]
        seen: set[tuple[str, str]] = set()
        for quote in quotes:
            key = (quote.registration_identity, quote.selected_field)
            if key in seen:
                continue
            seen.add(key)
            dependencies.append(
                DependencyEdge(
                    dependency_kind="dataset",
                    dependency_id=quote.registration_identity,
                    consumer_role="execution_price",
                    selected_fields=(quote.selected_field,),
                    compatibility_fingerprint=quote.physical_fingerprint,
                )
            )

        return tuple(dependencies)

    def _failure(
        self,
        spec: AcademicRunSpec,
        code: str,
        stage: str,
        context: dict[str, object],
        *,
        committed: bool,
    ) -> OperationOutcome:
        error = build_operation_error(
            operation="academic.run",
            stage_path=stage,
            error_code=code,
            idempotency_identity=spec.run_id,
            error_identity_seed=f"{spec.run_id}:{stage}:{code}:{context}",
            context=context,
            retry_preconditions=(
                "provide exact signed portfolio artifacts, listings, schedule, and PIT prices",
            ),
            commit_status=(CommitStatus.COMMITTED if committed else CommitStatus.NONE),
        )
        return publish_failed_outcome(self._artifacts, error)
