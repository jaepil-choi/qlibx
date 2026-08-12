"""Direct orchestration for PIT-safe research-data materialization."""

from dataclasses import dataclass
from typing import Generic, TypeVar

from qlibx.contracts import (
    FORWARD_RETURN_LABEL_OUTPUT,
    ModelComputationError,
    ModelInvocation,
    ModelOutputContract,
    ResearchModel,
)
from qlibx.data import (
    ComponentRequirement,
    ObservationStore,
    RegistrySnapshot,
    RequirementResolver,
)
from qlibx.data.store import DataSnapshotError
from qlibx.errors import OperationError, OperationOutcome, OutcomeStatus
from qlibx.evidence import (
    ArtifactContract,
    ArtifactEnvelope,
    ArtifactStatus,
    DependencyEdge,
    LocalArtifactBackend,
)
from qlibx.flow.failures import (
    build_operation_error,
    publish_failed_errors,
    publish_failed_outcome,
)
from qlibx.models import QlibxModel
from qlibx.runtime import BacktestClock
from qlibx.view import AccessRecord, ViewAccessError, ViewGate

PayloadModel = TypeVar("PayloadModel", bound=QlibxModel)


FORWARD_RETURN_LABEL_CONTRACT = ArtifactContract(
    artifact_type=FORWARD_RETURN_LABEL_OUTPUT.artifact_type,
    artifact_schema_version=FORWARD_RETURN_LABEL_OUTPUT.artifact_schema_version,
    payload_model=FORWARD_RETURN_LABEL_OUTPUT.payload_model,
)

_OPERATION_ERROR_CONTRACT = ArtifactContract(
    artifact_type="operation_error",
    artifact_schema_version=1,
    payload_model=OperationError,
)


@dataclass(frozen=True, slots=True)
class ModelRunResult(Generic[PayloadModel]):
    result: PayloadModel
    artifact: ArtifactEnvelope
    accesses: tuple[AccessRecord, ...]


class ModelFlow:
    """Resolve, scope, calculate, and publish one optional materialization operation."""

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

    def invoke(
        self,
        operation: ResearchModel[PayloadModel],
        invocation: ModelInvocation,
    ) -> OperationOutcome:
        declared = self._declared_contract(operation, invocation)
        if isinstance(declared, OperationOutcome):
            return declared
        producer_id, output_contract = declared

        resolution_dependency = self._resolution_dependency(invocation)
        if isinstance(resolution_dependency, OperationOutcome):
            return resolution_dependency

        try:
            requirements = tuple(operation.requirements())
            if not all(isinstance(item, ComponentRequirement) for item in requirements):
                raise TypeError(
                    "materialization requirements must contain ComponentRequirement values"
                )
        except Exception as exc:
            return self._failure(
                invocation,
                "materialization.run.requirements",
                "MATERIALIZATION_REQUIREMENTS_FAILED",
                exc,
            )

        resolution = self._resolver.resolve(
            operation="materialization.run",
            idempotency_identity=invocation.invocation_id,
            requirements=requirements,
            registry=self._registry,
        )
        if resolution.failed:
            return publish_failed_errors(self._artifacts, resolution.errors)

        view = ViewGate(self._registry, self._store).model_view(
            BacktestClock(invocation.evaluation_time),
            resolution.bindings,
        )
        try:
            result = operation.run(view)
        except ModelComputationError as exc:
            return self._failure(
                invocation,
                "materialization.run.compute",
                exc.code,
                exc,
                context=exc.context,
                accesses=view.accessed(),
            )
        except DataSnapshotError as exc:
            return self._failure(
                invocation,
                "materialization.run.data",
                exc.code,
                exc,
                accesses=view.accessed(),
            )
        except ViewAccessError as exc:
            return self._failure(
                invocation,
                "materialization.run.data",
                "MATERIALIZATION_DATA_READ_FAILED",
                exc,
                accesses=view.accessed(),
            )
        except Exception as exc:
            return self._failure(
                invocation,
                "materialization.run.compute",
                "MATERIALIZATION_COMPUTE_FAILED",
                exc,
                accesses=view.accessed(),
            )

        if not isinstance(result, output_contract.payload_model):
            return self._failure(
                invocation,
                "materialization.run.result",
                "MATERIALIZATION_RESULT_INVALID",
                TypeError(
                    f"materialization returned {type(result).__name__}, "
                    f"expected {output_contract.payload_model.__name__}"
                ),
                accesses=view.accessed(),
            )

        accesses = view.accessed()
        dependencies = self._dependencies(
            invocation,
            accesses,
            resolution_dependency,
        )
        publication = self._artifacts.publish_model(
            logical_identity=f"materialization:{invocation.invocation_id}",
            artifact_type=output_contract.artifact_type,
            artifact_schema_version=output_contract.artifact_schema_version,
            producer_id=producer_id,
            payload=result,
            dependencies=dependencies,
        )
        if publication.status is not OutcomeStatus.COMPLETE:
            return publication
        return OperationOutcome(
            status=OutcomeStatus.COMPLETE,
            result=ModelRunResult(
                result=result,
                artifact=publication.result,
                accesses=accesses,
            ),
        )

    def _declared_contract(
        self,
        operation: ResearchModel[PayloadModel],
        invocation: ModelInvocation,
    ) -> tuple[str, ModelOutputContract[PayloadModel]] | OperationOutcome:
        try:
            producer_id = operation.producer_id
            output_contract = operation.output_contract
            if not isinstance(producer_id, str) or not producer_id:
                raise TypeError("materialization producer_id must be a non-empty string")
            if not isinstance(output_contract, ModelOutputContract):
                raise TypeError(
                    "materialization output_contract must be ModelOutputContract"
                )
        except Exception as exc:
            return self._failure(
                invocation,
                "materialization.run.contract",
                "MATERIALIZATION_CONTRACT_INVALID",
                exc,
            )
        return producer_id, output_contract

    def _resolution_dependency(
        self,
        invocation: ModelInvocation,
    ) -> DependencyEdge | OperationOutcome | None:
        artifact_id = invocation.resolves_error_artifact_id
        if artifact_id is None:
            return None
        loaded = self._artifacts.load_model(
            artifact_id,
            _OPERATION_ERROR_CONTRACT,
            include_failure=True,
        )
        if loaded.status is not OutcomeStatus.COMPLETE:
            return self._failure(
                invocation,
                "materialization.run.resolution",
                "MATERIALIZATION_RESOLUTION_ERROR_INVALID",
                ValueError("resolution artifact is absent or not a supported failure"),
                context={"resolves_error_artifact_id": artifact_id},
            )
        if (
            loaded.result.envelope.status is not ArtifactStatus.FAILURE
            or loaded.result.payload.operation != "materialization.run"
            or loaded.result.payload.idempotency_identity == invocation.invocation_id
        ):
            return self._failure(
                invocation,
                "materialization.run.resolution",
                "MATERIALIZATION_RESOLUTION_ERROR_INVALID",
                ValueError("resolution artifact is not a prior materialization failure"),
                context={
                    "resolves_error_artifact_id": artifact_id,
                    "source_operation": loaded.result.payload.operation,
                    "source_invocation_id": loaded.result.payload.idempotency_identity,
                },
            )
        return DependencyEdge(
            dependency_kind="error",
            dependency_id=artifact_id,
            consumer_role="resolves_error",
        )

    @staticmethod
    def _dependencies(
        invocation: ModelInvocation,
        accesses: tuple[AccessRecord, ...],
        resolution_dependency: DependencyEdge | None,
    ) -> tuple[DependencyEdge, ...]:
        candidates = (
            *(
                DependencyEdge(
                    dependency_kind="dataset",
                    dependency_id=access.registration_identity,
                    consumer_role=access.semantic_role,
                    selected_fields=(access.selected_field,),
                )
                for access in accesses
            ),
            DependencyEdge(
                dependency_kind="config",
                dependency_id=invocation.config_fingerprint,
                consumer_role="materialization_config",
            ),
            *((resolution_dependency,) if resolution_dependency is not None else ()),
        )
        unique: dict[tuple[str, str], DependencyEdge] = {}
        for dependency in candidates:
            key = (dependency.dependency_id, dependency.consumer_role)
            current = unique.get(key)
            if current is not None and current != dependency:
                raise ValueError(f"conflicting materialization dependency: {key}")
            unique[key] = dependency
        return tuple(
            unique[key]
            for key in sorted(unique, key=lambda item: (item[1], item[0]))
        )

    def _failure(
        self,
        invocation: ModelInvocation,
        stage_path: str,
        error_code: str,
        exception: Exception,
        *,
        context: dict[str, object] | None = None,
        accesses: tuple[AccessRecord, ...] = (),
    ) -> OperationOutcome:
        error = build_operation_error(
            operation="materialization.run",
            stage_path=stage_path,
            error_code=error_code,
            context={
                "exception": type(exception).__name__,
                "message": str(exception)[:500],
                "accesses": [access.model_dump(mode="json") for access in accesses],
                **(context or {}),
            },
            retry_preconditions=(
                "correct the materialization contract or explicitly bind the required input",
            ),
            idempotency_identity=invocation.invocation_id,
            error_identity_seed=f"{invocation.invocation_id}:{stage_path}:{error_code}",
        )
        return publish_failed_outcome(self._artifacts, error)
