"""Exact version dispatch for persisted Strategy results."""

from qlibx.errors import OperationOutcome, OutcomeStatus
from qlibx.evidence import ArtifactContract, ArtifactEnvelope, LocalArtifactBackend
from qlibx.flow.failures import build_operation_error
from qlibx.operations import StrategyResult, StrategyResultV1

STRATEGY_RESULT_V1_CONTRACT = ArtifactContract(
    artifact_type="strategy_result",
    artifact_schema_version=1,
    payload_model=StrategyResultV1,
)

STRATEGY_RESULT_CONTRACT = ArtifactContract(
    artifact_type="strategy_result",
    artifact_schema_version=2,
    payload_model=StrategyResult,
)

STRATEGY_RESULT_CONTRACTS = (
    STRATEGY_RESULT_V1_CONTRACT,
    STRATEGY_RESULT_CONTRACT,
)

StrategyResultPayload = StrategyResultV1 | StrategyResult


def load_strategy_result(
    artifacts: LocalArtifactBackend,
    artifact_id: str,
    *,
    envelope: ArtifactEnvelope | None = None,
    operation: str = "strategy_result.load",
    idempotency_identity: str | None = None,
) -> OperationOutcome:
    """Load schema 1 or 2 by exact envelope metadata, never by catalog selection."""

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
    contract_by_version = {
        contract.artifact_schema_version: contract for contract in STRATEGY_RESULT_CONTRACTS
    }
    contract = contract_by_version.get(selected_envelope.artifact_schema_version)
    if selected_envelope.artifact_type != "strategy_result" or contract is None:
        return _unsupported(
            artifact_id=artifact_id,
            operation=operation,
            idempotency_identity=idempotency_identity,
            actual_type=selected_envelope.artifact_type,
            actual_version=selected_envelope.artifact_schema_version,
            reason="artifact is not a supported Strategy result schema",
        )
    return artifacts.load_model(artifact_id, contract)


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
            "artifact_schema_versions": (1, 2),
        },
        retry_preconditions=(
            "supply the exact ID of a supported strategy_result:v1 or v2 artifact",
        ),
    )
    return OperationOutcome(status=OutcomeStatus.FAILED, errors=(error,))
