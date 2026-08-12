from pathlib import Path

from qlibx import OperationError, OutcomeStatus, QlibxModel, QlibxProject
from qlibx.evidence import ArtifactContract, ArtifactStatus, DependencyEdge


class WeightPayload(QlibxModel):
    weights: dict[str, float]


CONTRACT = ArtifactContract(
    artifact_type="signed_weights",
    artifact_schema_version=1,
    payload_model=WeightPayload,
)


def project(tmp_path: Path) -> QlibxProject:
    QlibxProject.init(tmp_path, apply=True)
    return QlibxProject.open(tmp_path)


def test_artifact_publication_is_idempotent_and_typed(tmp_path: Path) -> None:
    current = project(tmp_path)
    first = current.artifacts.publish_model(
        logical_identity="strategy:value:2025-01-02",
        artifact_type=CONTRACT.artifact_type,
        artifact_schema_version=CONTRACT.artifact_schema_version,
        producer_id="tests.value_strategy",
        payload=WeightPayload(weights={"005930": 0.5}),
    )
    second = current.artifacts.publish_model(
        logical_identity="strategy:value:2025-01-02",
        artifact_type=CONTRACT.artifact_type,
        artifact_schema_version=CONTRACT.artifact_schema_version,
        producer_id="tests.value_strategy",
        payload=WeightPayload(weights={"005930": 0.5}),
    )

    assert first.status is OutcomeStatus.COMPLETE
    assert second.result.artifact_id == first.result.artifact_id
    loaded = current.load_artifact(first.result.artifact_id, CONTRACT)
    assert loaded.status is OutcomeStatus.COMPLETE
    assert loaded.result.payload == WeightPayload(weights={"005930": 0.5})


def test_same_logical_identity_with_other_content_is_a_conflict(tmp_path: Path) -> None:
    current = project(tmp_path)
    first = current.artifacts.publish_model(
        logical_identity="weights:one",
        artifact_type=CONTRACT.artifact_type,
        artifact_schema_version=1,
        producer_id="tests",
        payload=WeightPayload(weights={"005930": 0.5}),
    )
    conflict = current.artifacts.publish_model(
        logical_identity="weights:one",
        artifact_type=CONTRACT.artifact_type,
        artifact_schema_version=1,
        producer_id="tests",
        payload=WeightPayload(weights={"005930": 0.6}),
    )

    assert conflict.status is OutcomeStatus.FAILED
    assert conflict.errors[0].error_code == "ARTIFACT_IDENTITY_CONFLICT"
    assert current.artifacts.list_envelopes() == (first.result,)


def test_uc_artifact_002_invalid_external_payload_never_becomes_reusable(
    tmp_path: Path,
) -> None:
    current = project(tmp_path)
    outcome = current.artifacts.import_model_bytes(
        logical_identity="external:invalid",
        contract=CONTRACT,
        producer_id="external-process",
        payload_bytes=b'{"weights":"not-a-mapping"}',
    )

    assert outcome.status is OutcomeStatus.FAILED
    assert outcome.errors[0].error_code == "ARTIFACT_PAYLOAD_INVALID"
    assert current.artifacts.list_envelopes() == ()


def test_failure_and_resolution_are_distinct_lineage_artifacts(tmp_path: Path) -> None:
    current = project(tmp_path)
    error = OperationError(
        operation="strategy.run",
        stage_path="strategy.run.requirements.sector",
        error_code="REQUIREMENT_NOT_RESOLVED",
        requirement_id="strategy.sector",
        idempotency_identity="strategy-1",
        error_id="error-sector-1",
    )
    failure = current.artifacts.publish_failure(error)
    success = current.artifacts.publish_model(
        logical_identity="strategy:retry:2",
        artifact_type=CONTRACT.artifact_type,
        artifact_schema_version=1,
        producer_id="tests",
        payload=WeightPayload(weights={"005930": 0.5}),
        dependencies=(
            DependencyEdge(
                dependency_kind="error",
                dependency_id=failure.result.artifact_id,
                consumer_role="resolves_error",
            ),
        ),
    )

    assert failure.result.status is ArtifactStatus.FAILURE
    assert success.status is OutcomeStatus.COMPLETE
    assert current.artifacts.list_envelopes() == (success.result,)
    assert current.artifacts.list_envelopes(artifact_type=CONTRACT.artifact_type) == (
        success.result,
    )
    assert current.artifacts.list_envelopes(artifact_type="operation_error") == ()
    assert current.artifacts.list_envelopes(
        include_failure=True,
        artifact_type="operation_error",
    ) == (failure.result,)
    assert len(current.artifacts.list_envelopes(include_failure=True)) == 2


def test_unindexed_payload_is_not_visible(tmp_path: Path) -> None:
    current = project(tmp_path)
    orphan = tmp_path / ".qlibx" / "artifacts" / "orphan.json"
    orphan.write_text("{}", encoding="utf-8")

    assert current.artifacts.list_envelopes() == ()
