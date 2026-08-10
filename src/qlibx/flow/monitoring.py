"""Independent monitoring over committed Account state and PIT compliance data."""

from qlibx.account import Account
from qlibx.data import ObservationStore, RegistrySnapshot, RequirementResolver, Resolution
from qlibx.data.requirements import ComponentRequirement
from qlibx.errors import OperationError, OperationOutcome, OutcomeStatus
from qlibx.evidence import ArtifactContract, DependencyEdge, LocalArtifactBackend
from qlibx.flow.failures import (
    build_operation_error,
    publish_failed_errors,
    publish_failed_outcome,
)
from qlibx.kernel import Clock
from qlibx.portfolio import (
    BenchmarkWeight,
    ConstraintDeclaration,
    ConstraintEvaluationError,
    ConstraintMonitoringRequest,
    ConstraintMonitoringResult,
    monitor_actual_single_name_caps,
)
from qlibx.view import MonitorView, ViewGate

CONSTRAINT_MONITORING_CONTRACT = ArtifactContract(
    artifact_type="constraint_monitoring_result",
    artifact_schema_version=1,
    payload_model=ConstraintMonitoringResult,
)


class MonitoringFlow:
    """Publish findings without creating a decision, order, or authority commit."""

    def __init__(
        self,
        *,
        clock: Clock,
        registry: RegistrySnapshot,
        artifacts: LocalArtifactBackend,
        account: Account,
        resolver: RequirementResolver | None = None,
        store: ObservationStore | None = None,
    ) -> None:
        self._clock = clock
        self._registry = registry
        self._artifacts = artifacts
        self._account = account
        self._resolver = resolver or RequirementResolver()
        self._store = store or ObservationStore()

    def run(
        self,
        declaration: ConstraintDeclaration,
        request: ConstraintMonitoringRequest,
    ) -> OperationOutcome:
        resolution = self._resolve(request, declaration)
        if resolution.failed:
            return self._resolution_failure(resolution.errors)

        snapshot = self._account.snapshot(evaluation_time=self._clock.now)
        view = ViewGate(self._registry, self._store).monitor_view(
            self._clock,
            resolution.bindings,
            account_state=snapshot,
        )
        try:
            view.account_snapshot()
            account_state = view.state_accessed()[0]
            benchmark = self._benchmark(view, declaration)
            accesses = view.accessed()
        except Exception as exc:
            return self._failure(
                request=request,
                stage_path="monitoring.constraint.data",
                code="MONITORING_DATA_READ_FAILED",
                context={
                    "exception": type(exc).__name__,
                    "message": str(exc)[:500],
                    "accesses": self._access_context(view),
                },
            )
        try:
            result = monitor_actual_single_name_caps(
                request,
                self._clock.now,
                declaration,
                account_state,
                benchmark,
                accesses,
            )
        except ConstraintEvaluationError as exc:
            return self._failure(
                request=request,
                stage_path="monitoring.constraint.compute",
                code=exc.code,
                context={
                    **exc.context,
                    "accesses": self._access_context(view),
                },
            )
        except Exception as exc:
            return self._failure(
                request=request,
                stage_path="monitoring.constraint.compute",
                code="MONITORING_COMPUTE_FAILED",
                context={
                    "exception": type(exc).__name__,
                    "message": str(exc)[:500],
                    "accesses": self._access_context(view),
                },
            )

        publication = self._artifacts.publish_model(
            logical_identity=f"constraint-monitoring:{request.invocation_id}",
            artifact_type="constraint_monitoring_result",
            artifact_schema_version=1,
            producer_id="monitoring.single_name_cap",
            payload=result,
            dependencies=self._dependencies(request, result),
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
        request: ConstraintMonitoringRequest,
        declaration: ConstraintDeclaration,
    ) -> Resolution:
        return self._resolver.resolve(
            operation="monitoring.constraint",
            idempotency_identity=request.invocation_id,
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
        view: MonitorView,
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
    def _access_context(view: MonitorView) -> list[dict[str, object]]:
        return [item.model_dump(mode="json") for item in view.accessed()]

    @staticmethod
    def _dependencies(
        request: ConstraintMonitoringRequest,
        result: ConstraintMonitoringResult,
    ) -> tuple[DependencyEdge, ...]:
        state = result.account_state
        return (
            DependencyEdge(
                dependency_kind="config",
                dependency_id=request.config_fingerprint,
                consumer_role="monitoring_config",
            ),
            DependencyEdge(
                dependency_kind="state",
                dependency_id=(
                    f"{state.account_id}:v{state.version}:cursor{state.feedback_cursor}"
                ),
                consumer_role="committed_account_snapshot",
                selected_fields=("cash", "nav", "positions"),
            ),
            *(
                DependencyEdge(
                    dependency_kind="dataset",
                    dependency_id=access.registration_identity,
                    consumer_role=access.semantic_role,
                    selected_fields=(access.selected_field,),
                )
                for access in result.accesses
            ),
        )

    def _resolution_failure(self, errors: tuple[OperationError, ...]) -> OperationOutcome:
        return publish_failed_errors(self._artifacts, errors)

    def _failure(
        self,
        *,
        request: ConstraintMonitoringRequest,
        stage_path: str,
        code: str,
        context: dict[str, object],
    ) -> OperationOutcome:
        error = build_operation_error(
            operation="monitoring.constraint",
            stage_path=stage_path,
            error_code=code,
            idempotency_identity=request.invocation_id,
            error_identity_seed=f"{request.invocation_id}:{stage_path}:{code}",
            context=context,
            retry_preconditions=(
                "provide complete PIT benchmark and marked committed Account state",
            ),
        )
        return publish_failed_outcome(self._artifacts, error)
