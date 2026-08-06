"""Artifact-backed orchestration for optional portfolio construction."""

import hashlib

from qlibx.errors import CommitStatus, OperationError, OperationOutcome, OutcomeStatus
from qlibx.evidence import DependencyEdge, LocalArtifactBackend
from qlibx.flow.composition import STRATEGY_RESULT_CONTRACT
from qlibx.portfolio import (
    PortfolioConstructionError,
    PortfolioConstructionInput,
    PortfolioConstructionRequest,
    PortfolioWeight,
    construct_portfolio,
)


class PortfolioConstructionFlow:
    """Construct a new portfolio artifact without changing its source alpha."""

    def __init__(self, *, artifacts: LocalArtifactBackend) -> None:
        self._artifacts = artifacts

    def construct(self, request: PortfolioConstructionRequest) -> OperationOutcome:
        loaded = self._artifacts.load_model(
            request.source_artifact_id,
            STRATEGY_RESULT_CONTRACT,
        )
        if loaded.status is not OutcomeStatus.COMPLETE:
            return loaded
        strategy = loaded.result.payload
        try:
            source = PortfolioConstructionInput(
                source_strategy_id=strategy.strategy_id,
                weights=tuple(
                    PortfolioWeight(instrument=entry.instrument, weight=entry.weight)
                    for entry in strategy.weights
                ),
            )
            result = construct_portfolio(request, source)
        except (PortfolioConstructionError, ValueError) as exc:
            code = (
                exc.code
                if isinstance(exc, PortfolioConstructionError)
                else "CONSTRUCTION_INPUT_INVALID"
            )
            context = exc.context if isinstance(exc, PortfolioConstructionError) else {
                "message": str(exc)[:500]
            }
            return self._failure(request, code, context)

        publication = self._artifacts.publish_model(
            logical_identity=f"portfolio:{request.invocation_id}",
            artifact_type="portfolio_construction_result",
            artifact_schema_version=1,
            producer_id=f"portfolio.{request.profile.value}",
            payload=result,
            dependencies=(
                DependencyEdge(
                    dependency_kind="artifact",
                    dependency_id=request.source_artifact_id,
                    consumer_role="signed_alpha",
                ),
                DependencyEdge(
                    dependency_kind="config",
                    dependency_id=request.config_fingerprint,
                    consumer_role="construction_config",
                ),
            ),
        )
        if publication.status is not OutcomeStatus.COMPLETE:
            return publication
        return OperationOutcome(
            status=OutcomeStatus.COMPLETE,
            result=result,
            diagnostics=(publication.result,),
        )

    def _failure(
        self,
        request: PortfolioConstructionRequest,
        code: str,
        context: dict[str, object],
    ) -> OperationOutcome:
        seed = hashlib.sha256(
            f"{request.invocation_id}:{code}".encode()
        ).hexdigest()[:24]
        error = OperationError(
            operation="portfolio.construct",
            stage_path="portfolio.construct.compute",
            error_code=code,
            context=context,
            commit_status=CommitStatus.NONE,
            retry_preconditions=("select a compatible construction profile and signed alpha",),
            idempotency_identity=request.invocation_id,
            error_id=f"error-{seed}",
        )
        published = self._artifacts.publish_failure(error)
        diagnostics = (
            (published.result,) if published.status is OutcomeStatus.COMPLETE else published.errors
        )
        return OperationOutcome(
            status=OutcomeStatus.FAILED,
            diagnostics=diagnostics,
            errors=(error,),
        )
