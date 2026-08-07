"""PIT-safe constraint adjustment and independent validation orchestration."""

from qlibx.context import AccessRecord, MaterializeView, ViewGate
from qlibx.data import ObservationStore, RegistrySnapshot, RequirementResolver, Resolution
from qlibx.data.requirements import ComponentRequirement
from qlibx.errors import OperationError, OperationOutcome, OutcomeStatus
from qlibx.evidence import ArtifactContract, DependencyEdge, LocalArtifactBackend
from qlibx.flow.failures import (
    build_operation_error,
    publish_failed_errors,
    publish_failed_outcome,
)
from qlibx.flow.portfolio import PORTFOLIO_RESULT_CONTRACT
from qlibx.kernel import BacktestClock
from qlibx.portfolio import (
    BenchmarkWeight,
    ConstraintAdjustmentRequest,
    ConstraintAdjustmentResult,
    ConstraintDeclaration,
    ConstraintEvaluationError,
    ConstraintValidationRequest,
    ConstraintValidationResult,
    adjust_single_name_caps,
    validate_single_name_caps,
)

CONSTRAINT_ADJUSTMENT_CONTRACT = ArtifactContract(
    artifact_type="constraint_adjustment_result",
    artifact_schema_version=1,
    payload_model=ConstraintAdjustmentResult,
)

CONSTRAINT_VALIDATION_CONTRACT = ArtifactContract(
    artifact_type="constraint_validation_result",
    artifact_schema_version=1,
    payload_model=ConstraintValidationResult,
)


class ConstraintFlow:
    """Resolve only selected constraint data and publish mutation-free evidence."""

    def __init__(
        self,
        *,
        registry: RegistrySnapshot,
        artifacts: LocalArtifactBackend,
        resolver: RequirementResolver | None = None,
        store: ObservationStore | None = None,
    ) -> None:
        self._registry = registry
        self._artifacts = artifacts
        self._resolver = resolver or RequirementResolver()
        self._store = store or ObservationStore()

    def adjust(
        self,
        declaration: ConstraintDeclaration,
        request: ConstraintAdjustmentRequest,
    ) -> OperationOutcome:
        loaded = self._artifacts.load_model(
            request.source_portfolio_artifact_id,
            PORTFOLIO_RESULT_CONTRACT,
        )
        if loaded.status is not OutcomeStatus.COMPLETE:
            return loaded
        resolution = self._resolve(
            operation="constraint.adjust",
            identity=request.invocation_id,
            declaration=declaration,
        )
        if resolution.failed:
            return self._resolution_failure(resolution.errors)
        view = ViewGate(self._registry, self._store).materialize_view(
            BacktestClock(request.evaluation_time),
            resolution.bindings,
        )
        try:
            benchmark = self._benchmark(view, declaration)
            accesses = view.accessed()
        except Exception as exc:
            return self._failure(
                operation="constraint.adjust",
                stage_path="constraint.adjust.data",
                identity=request.invocation_id,
                code="CONSTRAINT_DATA_READ_FAILED",
                context={
                    "exception": type(exc).__name__,
                    "message": str(exc)[:500],
                    "accesses": self._access_context(view),
                },
            )
        try:
            result = adjust_single_name_caps(
                request,
                declaration,
                loaded.result.payload,
                benchmark,
                accesses,
            )
        except ConstraintEvaluationError as exc:
            return self._failure(
                operation="constraint.adjust",
                stage_path="constraint.adjust.compute",
                identity=request.invocation_id,
                code=exc.code,
                context={**exc.context, "accesses": self._access_context(view)},
            )
        except Exception as exc:
            return self._failure(
                operation="constraint.adjust",
                stage_path="constraint.adjust.compute",
                identity=request.invocation_id,
                code="CONSTRAINT_COMPUTE_FAILED",
                context={
                    "exception": type(exc).__name__,
                    "message": str(exc)[:500],
                    "accesses": self._access_context(view),
                },
            )
        publication = self._artifacts.publish_model(
            logical_identity=f"constraint-adjustment:{request.invocation_id}",
            artifact_type="constraint_adjustment_result",
            artifact_schema_version=1,
            producer_id="constraint.single_name_cap.adjust",
            payload=result,
            dependencies=self._dependencies(
                request.source_portfolio_artifact_id,
                "portfolio_candidate",
                request.config_fingerprint,
                result.accesses,
                state_identity=request.account_state_identity,
            ),
        )
        if publication.status is not OutcomeStatus.COMPLETE:
            return publication
        return OperationOutcome(
            status=OutcomeStatus.COMPLETE,
            result=result,
            diagnostics=(publication.result,),
        )

    def validate(
        self,
        declaration: ConstraintDeclaration,
        request: ConstraintValidationRequest,
    ) -> OperationOutcome:
        loaded = self._artifacts.load_model(
            request.adjustment_artifact_id,
            CONSTRAINT_ADJUSTMENT_CONTRACT,
        )
        if loaded.status is not OutcomeStatus.COMPLETE:
            return loaded
        resolution = self._resolve(
            operation="constraint.validate",
            identity=request.invocation_id,
            declaration=declaration,
        )
        if resolution.failed:
            return self._resolution_failure(resolution.errors)
        view = ViewGate(self._registry, self._store).materialize_view(
            BacktestClock(request.evaluation_time),
            resolution.bindings,
        )
        try:
            benchmark = self._benchmark(view, declaration)
            accesses = view.accessed()
        except Exception as exc:
            return self._failure(
                operation="constraint.validate",
                stage_path="constraint.validate.data",
                identity=request.invocation_id,
                code="CONSTRAINT_DATA_READ_FAILED",
                context={
                    "exception": type(exc).__name__,
                    "message": str(exc)[:500],
                    "accesses": self._access_context(view),
                },
            )
        try:
            result = validate_single_name_caps(
                request,
                declaration,
                loaded.result.payload,
                benchmark,
                accesses,
            )
        except ConstraintEvaluationError as exc:
            return self._failure(
                operation="constraint.validate",
                stage_path="constraint.validate.compute",
                identity=request.invocation_id,
                code=exc.code,
                context={**exc.context, "accesses": self._access_context(view)},
            )
        except Exception as exc:
            return self._failure(
                operation="constraint.validate",
                stage_path="constraint.validate.compute",
                identity=request.invocation_id,
                code="CONSTRAINT_COMPUTE_FAILED",
                context={
                    "exception": type(exc).__name__,
                    "message": str(exc)[:500],
                    "accesses": self._access_context(view),
                },
            )
        publication = self._artifacts.publish_model(
            logical_identity=f"constraint-validation:{request.invocation_id}",
            artifact_type="constraint_validation_result",
            artifact_schema_version=1,
            producer_id="constraint.single_name_cap.validate",
            payload=result,
            dependencies=self._dependencies(
                request.adjustment_artifact_id,
                "adjusted_candidate",
                request.config_fingerprint,
                result.accesses,
            ),
        )
        if publication.status is not OutcomeStatus.COMPLETE:
            return publication
        return OperationOutcome(
            status=OutcomeStatus.COMPLETE,
            result=result,
            diagnostics=(publication.result,),
        )

    def _resolve(
        self,
        *,
        operation: str,
        identity: str,
        declaration: ConstraintDeclaration,
    ) -> Resolution:
        return self._resolver.resolve(
            operation=operation,
            idempotency_identity=identity,
            requirements=(
                ComponentRequirement(
                    requirement_id=f"{declaration.declaration_id}.benchmark_weight",
                    semantic_role=declaration.benchmark_weight_role,
                    dataset_id=declaration.benchmark_dataset_id,
                ),
            ),
            registry=self._registry,
        )

    @staticmethod
    def _benchmark(
        view: MaterializeView,
        declaration: ConstraintDeclaration,
    ) -> tuple[BenchmarkWeight, ...]:
        frame = view.latest(declaration.benchmark_weight_role)
        return tuple(
            BenchmarkWeight(
                instrument=str(row.instrument),
                weight=float(getattr(row, declaration.benchmark_weight_role)),
            )
            for row in frame.itertuples(index=False)
        )

    @staticmethod
    def _access_context(view: MaterializeView) -> list[dict[str, object]]:
        return [item.model_dump(mode="json") for item in view.accessed()]

    @staticmethod
    def _dependencies(
        source_artifact_id: str,
        source_role: str,
        config_fingerprint: str,
        accesses: tuple[AccessRecord, ...],
        state_identity: str | None = None,
    ) -> tuple[DependencyEdge, ...]:
        return (
            DependencyEdge(
                dependency_kind="artifact",
                dependency_id=source_artifact_id,
                consumer_role=source_role,
            ),
            DependencyEdge(
                dependency_kind="config",
                dependency_id=config_fingerprint,
                consumer_role="constraint_config",
            ),
            *(
                ()
                if state_identity is None
                else (
                    DependencyEdge(
                        dependency_kind="state",
                        dependency_id=state_identity,
                        consumer_role="actual_pretrade_state",
                        selected_fields=("nav", "positions"),
                    ),
                )
            ),
            *(
                DependencyEdge(
                    dependency_kind="dataset",
                    dependency_id=access.registration_identity,
                    consumer_role=access.semantic_role,
                    selected_fields=(access.selected_field,),
                )
                for access in accesses
            ),
        )

    def _resolution_failure(self, errors: tuple[OperationError, ...]) -> OperationOutcome:
        return publish_failed_errors(self._artifacts, errors)

    def _failure(
        self,
        *,
        operation: str,
        stage_path: str,
        identity: str,
        code: str,
        context: dict[str, object],
    ) -> OperationOutcome:
        error = build_operation_error(
            operation=operation,
            stage_path=stage_path,
            error_code=code,
            idempotency_identity=identity,
            error_identity_seed=f"{identity}:{stage_path}:{code}",
            context=context,
            retry_preconditions=(
                "provide complete PIT benchmark and execution-lot inputs",
            ),
        )
        return publish_failed_outcome(self._artifacts, error)
