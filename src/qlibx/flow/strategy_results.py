"""Exact v4 dispatch and lineage handling for persisted Strategy results."""

from qlibx.contracts import (
    StrategyResult,
    StrategySourceStateLineage,
    strategy_accesses_are_path_dependent,
)
from qlibx.errors import OperationOutcome, OutcomeStatus
from qlibx.evidence import (
    ArtifactContract,
    ArtifactEnvelope,
    DependencyEdge,
    LocalArtifactBackend,
)
from qlibx.flow.failures import build_operation_error
from qlibx.view import ArtifactAccessRecord, ArtifactInputProjection

STRATEGY_RESULT_CONTRACT = ArtifactContract(
    artifact_type="strategy_result",
    artifact_schema_version=4,
    payload_model=StrategyResult,
)
STRATEGY_RESULT_CONTRACTS = (STRATEGY_RESULT_CONTRACT,)
StrategyResultPayload = StrategyResult


def load_strategy_result(
    artifacts: LocalArtifactBackend,
    artifact_id: str,
    *,
    envelope: ArtifactEnvelope | None = None,
    operation: str = "strategy_result.load",
    idempotency_identity: str | None = None,
) -> OperationOutcome:
    """Load only canonical schema v4 by exact artifact ID and envelope metadata."""

    selected_envelope = envelope
    if selected_envelope is None:
        loaded_envelope = artifacts.load_envelope(artifact_id)
        if loaded_envelope.status is not OutcomeStatus.COMPLETE:
            return loaded_envelope
        selected_envelope = loaded_envelope.result
    if selected_envelope.artifact_id != artifact_id:
        return _unsupported(
            artifact_id=artifact_id,
            operation=operation,
            idempotency_identity=idempotency_identity,
            actual_type=selected_envelope.artifact_type,
            actual_version=selected_envelope.artifact_schema_version,
            reason="provided envelope does not match the exact artifact ID",
        )
    if (
        selected_envelope.artifact_type != STRATEGY_RESULT_CONTRACT.artifact_type
        or selected_envelope.artifact_schema_version
        != STRATEGY_RESULT_CONTRACT.artifact_schema_version
    ):
        return _unsupported(
            artifact_id=artifact_id,
            operation=operation,
            idempotency_identity=idempotency_identity,
            actual_type=selected_envelope.artifact_type,
            actual_version=selected_envelope.artifact_schema_version,
            reason="artifact is not canonical strategy_result:v4",
        )
    return artifacts.load_model(artifact_id, STRATEGY_RESULT_CONTRACT)


def _unsupported(
    *,
    artifact_id: str,
    operation: str,
    idempotency_identity: str | None,
    actual_type: str,
    actual_version: int,
    reason: str,
) -> OperationOutcome:
    identity = idempotency_identity or artifact_id
    error = build_operation_error(
        operation=operation,
        stage_path=f"{operation}.contract",
        error_code="STRATEGY_RESULT_SCHEMA_UNSUPPORTED",
        idempotency_identity=identity,
        error_identity_seed=(
            f"{identity}:{artifact_id}:{actual_type}:{actual_version}:unsupported"
        ),
        context={
            "artifact_id": artifact_id,
            "actual_type": actual_type,
            "actual_version": actual_version,
            "reason": reason,
        },
        expected={
            "artifact_type": "strategy_result",
            "artifact_schema_versions": (4,),
        },
        retry_preconditions=("rerun the Strategy producer to create strategy_result:v4",),
    )
    return OperationOutcome(status=OutcomeStatus.FAILED, errors=(error,))


class StrategySourceLineageError(ValueError):
    """Typed pre-publication failure while promoting consumed source lineage."""

    def __init__(self, code: str, context: dict[str, object]) -> None:
        self.code = code
        self.context = context
        super().__init__(code)


def collect_strategy_source_lineage(
    projections: tuple[ArtifactInputProjection, ...],
    accesses: tuple[ArtifactAccessRecord, ...],
) -> tuple[StrategySourceStateLineage, ...]:
    """Flatten canonical lineage from actually accessed v3 Strategy projections."""

    projection_by_key = {
        (projection.consumer_role, projection.artifact_id): projection for projection in projections
    }
    unique_accesses: dict[tuple[str, str], ArtifactAccessRecord] = {}
    for access in accesses:
        key = (access.consumer_role, access.artifact_id)
        existing = unique_accesses.get(key)
        if existing is not None and existing != access:
            raise StrategySourceLineageError(
                "STRATEGY_SOURCE_LINEAGE_CONFLICT",
                {"consumer_role": access.consumer_role, "artifact_id": access.artifact_id},
            )
        unique_accesses[key] = access

    lineage_by_source: dict[str, StrategySourceStateLineage] = {}
    for key in sorted(unique_accesses):
        access = unique_accesses[key]
        projection = projection_by_key.get(key)
        if projection is None or (
            projection.artifact_schema_version != access.artifact_schema_version
            or projection.content_hash != access.content_hash
        ):
            raise StrategySourceLineageError(
                "STRATEGY_SOURCE_LINEAGE_CONFLICT",
                {"consumer_role": access.consumer_role, "artifact_id": access.artifact_id},
            )
        if access.artifact_type != "strategy_result":
            continue
        payload = projection.payload
        if not isinstance(payload, StrategyResult):
            raise StrategySourceLineageError(
                "STRATEGY_SOURCE_LINEAGE_CONFLICT",
                {
                    "artifact_id": access.artifact_id,
                    "payload_model": type(payload).__name__,
                },
            )
        for candidate in _v4_source_lineage(access.artifact_id, payload):
            existing = lineage_by_source.get(candidate.source_artifact_id)
            if existing is not None and existing != candidate:
                raise StrategySourceLineageError(
                    "STRATEGY_SOURCE_LINEAGE_CONFLICT",
                    {"source_artifact_id": candidate.source_artifact_id},
                )
            lineage_by_source[candidate.source_artifact_id] = candidate
    return tuple(lineage_by_source[key] for key in sorted(lineage_by_source))


def _v4_source_lineage(
    artifact_id: str,
    payload: StrategyResult,
) -> tuple[StrategySourceStateLineage, ...]:
    inherited = list(payload.source_state_lineage)
    observed = strategy_accesses_are_path_dependent(
        account_history_accesses=payload.account_history_accesses,
        state_accesses=payload.state_accesses,
        feedback_accesses=payload.feedback_accesses,
        performance_accesses=payload.performance_accesses,
        strategy_state_accesses=payload.strategy_state_accesses,
        execution_accesses=payload.execution_accesses,
    )
    if observed:
        assert payload.state_identity is not None
        inherited.append(
            StrategySourceStateLineage(
                source_artifact_id=artifact_id,
                source_artifact_schema_version=4,
                source_invocation_id=payload.invocation_id,
                source_strategy_id=payload.strategy_id,
                declared_state_identity=payload.state_identity,

                state_accesses=payload.state_accesses,
                account_history_accesses=payload.account_history_accesses,
                feedback_accesses=payload.feedback_accesses,
                performance_accesses=payload.performance_accesses,
                strategy_state_accesses=payload.strategy_state_accesses,
                execution_accesses=payload.execution_accesses,
            )
        )
    return tuple(inherited)


def source_lineage_dependencies(
    lineages: tuple[StrategySourceStateLineage, ...],
) -> tuple[DependencyEdge, ...]:
    """Expose every inherited state and execution origin as dependency edges."""

    dependencies: list[DependencyEdge] = []
    for source_index, lineage in enumerate(lineages):
        prefix = f"source_{source_index:03d}"
        dependencies.append(
            DependencyEdge(
                dependency_kind="state",
                dependency_id=lineage.declared_state_identity,
                consumer_role=f"{prefix}_declared_state",
                selected_fields=("state_identity",),
            )
        )
        dependencies.extend(
            DependencyEdge(
                dependency_kind="state",
                dependency_id=(
                    f"account:{access.account_id}:history:{access.shape.value}:"
                    f"{access.start_session}:{access.end_session}"
                ),
                consumer_role=f"{prefix}_account_history_{index:03d}",
                selected_fields=access.selected_fields,
                compatibility_fingerprint=(
                    f"rows:{access.requested_rows}:sessions:{access.available_sessions}:"
                    f"instruments:{','.join(access.instruments)}"
                ),
            )
            for index, access in enumerate(lineage.account_history_accesses)
        )
        dependencies.extend(
            DependencyEdge(
                dependency_kind="state",
                dependency_id=(
                    f"account:{access.account_id}:v{access.version}:cursor{access.feedback_cursor}"
                ),
                consumer_role=f"{prefix}_account_{index:03d}",
                selected_fields=("cash", "nav", "positions", "feedback_cursor"),
            )
            for index, access in enumerate(lineage.state_accesses)
        )
        dependencies.extend(
            DependencyEdge(
                dependency_kind="state",
                dependency_id=(
                    f"account:{access.account_id}:feedback:"
                    f"{access.after_cursor}-{access.next_cursor}"
                ),
                consumer_role=f"{prefix}_feedback_{index:03d}",
                selected_fields=("event_ids", "change_types", "fill_ids"),
            )
            for index, access in enumerate(lineage.feedback_accesses)
        )
        dependencies.extend(
            DependencyEdge(
                dependency_kind="artifact",
                dependency_id=access.artifact_id,
                consumer_role=f"{prefix}_performance_{index:03d}",
            )
            for index, access in enumerate(lineage.performance_accesses)
        )
        dependencies.extend(
            DependencyEdge(
                dependency_kind="state",
                dependency_id=(
                    f"strategy-state:{access.strategy_id}:{access.state_fingerprint}"
                ),
                consumer_role=f"{prefix}_strategy_state_{index:03d}",
                selected_fields=("value",),
                compatibility_fingerprint=access.state_fingerprint,
            )
            for index, access in enumerate(lineage.strategy_state_accesses)
        )
        dependencies.extend(
            DependencyEdge(
                dependency_kind="artifact",
                dependency_id=access.artifact_id,
                consumer_role=f"{prefix}_execution_{index:03d}",
                compatibility_fingerprint=access.content_hash,
            )
            for index, access in enumerate(lineage.execution_accesses)
        )
    return tuple(dependencies)


def canonicalize_dependencies(
    dependencies: tuple[DependencyEdge, ...],
) -> tuple[DependencyEdge, ...]:
    """Remove identical repeated edges and reject conflicting catalog primary keys."""

    unique: dict[tuple[str, str], DependencyEdge] = {}
    ordered_keys: list[tuple[str, str]] = []
    for dependency in dependencies:
        key = (
            dependency.dependency_id,
            dependency.consumer_role,
        )
        existing = unique.get(key)
        if existing is not None:
            if existing != dependency:
                raise StrategySourceLineageError(
                    "STRATEGY_SOURCE_LINEAGE_CONFLICT",
                    {
                        "dependency_kind": dependency.dependency_kind,
                        "dependency_id": dependency.dependency_id,
                        "consumer_role": dependency.consumer_role,
                    },
                )
            continue
        unique[key] = dependency
        ordered_keys.append(key)
    return tuple(unique[key] for key in ordered_keys)
