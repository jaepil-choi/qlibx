from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from qlibx import OutcomeStatus, QlibxProject
from qlibx.context import StrategyView
from qlibx.operations import (
    ArtifactSemanticConstraint,
    BudgetMode,
    StoredSignalEntry,
    StoredSignalResult,
    StrategyArtifactBinding,
    StrategyArtifactRequirement,
    StrategyDraft,
    StrategyInvocation,
    StrategyResult,
    WeightEntry,
)

EVALUATION_TIME = datetime(2025, 1, 3, 9, tzinfo=UTC)


def initialized_project(tmp_path: Path) -> QlibxProject:
    QlibxProject.init(tmp_path, apply=True)
    return QlibxProject.open(tmp_path)


def publish_signal(
    project: QlibxProject,
    identity: str,
    *,
    semantics: str = "alpha",
    artifact_type: str = "stored_signal_result",
    schema_version: int = 1,
) -> object:
    outcome = project.artifacts.publish_model(
        logical_identity=identity,
        artifact_type=artifact_type,
        artifact_schema_version=schema_version,
        producer_id="tests.signal_producer",
        payload=StoredSignalResult(
            signal_semantics=semantics,
            observation_time=EVALUATION_TIME,
            entries=(StoredSignalEntry(instrument="A", value=1.0),),
        ),
    )
    assert outcome.status is OutcomeStatus.COMPLETE
    return outcome.result


def invocation(
    identity: str,
    *bindings: StrategyArtifactBinding,
) -> StrategyInvocation:
    return StrategyInvocation(
        invocation_id=identity,
        evaluation_time=EVALUATION_TIME,
        config_fingerprint="config-1",
        artifact_bindings=bindings,
    )


def requirement(
    requirement_id: str,
    consumer_role: str,
    *,
    artifact_type: str = "stored_signal_result",
    schema_version: int = 1,
    semantic_field: str | None = "signal_semantics",
    semantic_value: object = "alpha",
) -> StrategyArtifactRequirement:
    constraints = (
        ()
        if semantic_field is None
        else (
            ArtifactSemanticConstraint(
                field=semantic_field,
                expected=semantic_value,
            ),
        )
    )
    return StrategyArtifactRequirement(
        requirement_id=requirement_id,
        consumer_role=consumer_role,
        artifact_type=artifact_type,
        artifact_schema_version=schema_version,
        semantic_constraints=constraints,
    )


class ArtifactStrategy:
    strategy_id = "tests.artifact_strategy"

    def __init__(
        self,
        requirements: tuple[StrategyArtifactRequirement, ...],
        *,
        access_role: str | None = None,
        payload_type: type[StoredSignalResult] | type[StrategyResult] = StoredSignalResult,
    ) -> None:
        self._requirements = requirements
        self._access_role = access_role
        self._payload_type = payload_type
        self.called = False

    def requirements(self) -> tuple[object, ...]:
        return ()

    def artifact_requirements(self) -> tuple[StrategyArtifactRequirement, ...]:
        return self._requirements

    def run(self, view: StrategyView) -> StrategyDraft:
        self.called = True
        if self._access_role is not None:
            view.artifact(self._access_role, self._payload_type)
        return StrategyDraft(
            weights=(WeightEntry(instrument="A", weight=1.0),),
            budget_mode=BudgetMode.FIXED,
            target_gross=1.0,
        )


def test_generic_research_flow_tracks_only_artifacts_actually_accessed(
    tmp_path: Path,
) -> None:
    project = initialized_project(tmp_path)
    first = publish_signal(project, "signal:first")
    second = publish_signal(project, "signal:second")
    strategy = ArtifactStrategy(
        (
            requirement("signal.first", "alpha_signal"),
            requirement("signal.second", "unused_signal"),
        ),
        access_role="alpha_signal",
    )

    outcome = project.invoke(
        strategy,
        invocation(
            "artifact-input-success",
            StrategyArtifactBinding(
                consumer_role="alpha_signal",
                artifact_id=first.artifact_id,
            ),
            StrategyArtifactBinding(
                consumer_role="unused_signal",
                artifact_id=second.artifact_id,
            ),
        ),
    )

    assert outcome.status is OutcomeStatus.COMPLETE
    artifact_dependencies = tuple(
        edge
        for edge in outcome.result.artifact.dependencies
        if edge.dependency_kind == "artifact"
    )
    assert len(artifact_dependencies) == 1
    assert artifact_dependencies[0].dependency_id == first.artifact_id
    assert artifact_dependencies[0].consumer_role == "alpha_signal"
    assert artifact_dependencies[0].compatibility_fingerprint == first.content_hash
    assert "artifact" not in type(outcome.result.result).model_fields


def test_declared_but_unused_artifact_is_still_validated_before_compute(
    tmp_path: Path,
) -> None:
    project = initialized_project(tmp_path)
    signal = publish_signal(project, "signal:unused", semantics="beta")
    strategy = ArtifactStrategy((requirement("signal.unused", "unused_signal"),))

    outcome = project.invoke(
        strategy,
        invocation(
            "unused-invalid",
            StrategyArtifactBinding(
                consumer_role="unused_signal",
                artifact_id=signal.artifact_id,
            ),
        ),
    )

    assert outcome.status is OutcomeStatus.FAILED
    assert outcome.errors[0].error_code == "STRATEGY_ARTIFACT_SEMANTICS_INCOMPATIBLE"
    assert strategy.called is False


@pytest.mark.parametrize(
    ("requirements", "bindings", "error_code"),
    [
        (
            (requirement("signal.required", "required_signal"),),
            (),
            "STRATEGY_ARTIFACT_BINDING_MISSING",
        ),
        (
            (),
            (StrategyArtifactBinding(consumer_role="extra", artifact_id="artifact-extra"),),
            "STRATEGY_ARTIFACT_BINDING_UNDECLARED",
        ),
        (
            (
                requirement("signal.duplicate", "first"),
                requirement("signal.duplicate", "second"),
            ),
            (),
            "STRATEGY_ARTIFACT_REQUIREMENTS_FAILED",
        ),
        (
            (
                requirement("signal.first", "duplicate"),
                requirement("signal.second", "duplicate"),
            ),
            (),
            "STRATEGY_ARTIFACT_REQUIREMENTS_FAILED",
        ),
    ],
)
def test_binding_and_requirement_cardinality_fail_before_compute(
    tmp_path: Path,
    requirements: tuple[StrategyArtifactRequirement, ...],
    bindings: tuple[StrategyArtifactBinding, ...],
    error_code: str,
) -> None:
    project = initialized_project(tmp_path)
    strategy = ArtifactStrategy(requirements)

    outcome = project.invoke(strategy, invocation("cardinality", *bindings))

    assert outcome.status is OutcomeStatus.FAILED
    assert outcome.errors[0].error_code == error_code
    assert strategy.called is False


def test_duplicate_binding_roles_are_rejected_at_the_frozen_invocation_boundary() -> None:
    duplicate = StrategyArtifactBinding(consumer_role="signal", artifact_id="artifact-1")
    with pytest.raises(ValidationError, match="binding roles must be unique"):
        invocation(
            "duplicate-binding",
            duplicate,
            StrategyArtifactBinding(consumer_role="signal", artifact_id="artifact-2"),
        )


@pytest.mark.parametrize(
    ("artifact_type", "schema_version"),
    [("not_a_signal", 1), ("stored_signal_result", 2)],
)
def test_wrong_artifact_type_or_schema_fails_before_compute(
    tmp_path: Path,
    artifact_type: str,
    schema_version: int,
) -> None:
    project = initialized_project(tmp_path)
    selected = publish_signal(
        project,
        "signal:wrong-contract",
        artifact_type=artifact_type,
        schema_version=schema_version,
    )
    strategy = ArtifactStrategy((requirement("signal.required", "signal"),))

    outcome = project.invoke(
        strategy,
        invocation(
            "wrong-contract",
            StrategyArtifactBinding(
                consumer_role="signal",
                artifact_id=selected.artifact_id,
            ),
        ),
    )

    assert outcome.status is OutcomeStatus.FAILED
    assert outcome.errors[0].error_code == "STRATEGY_ARTIFACT_CONTRACT_UNSUPPORTED"
    assert outcome.errors[0].requirement_id == "signal.required"
    assert strategy.called is False


@pytest.mark.parametrize(
    ("field", "expected"),
    [("missing_field", "alpha"), ("signal_semantics", "beta")],
)
def test_missing_or_mismatched_semantics_fail_before_compute(
    tmp_path: Path,
    field: str,
    expected: str,
) -> None:
    project = initialized_project(tmp_path)
    selected = publish_signal(project, "signal:semantics")
    strategy = ArtifactStrategy(
        (
            requirement(
                "signal.required",
                "signal",
                semantic_field=field,
                semantic_value=expected,
            ),
        )
    )

    outcome = project.invoke(
        strategy,
        invocation(
            "semantic-mismatch",
            StrategyArtifactBinding(
                consumer_role="signal",
                artifact_id=selected.artifact_id,
            ),
        ),
    )

    assert outcome.status is OutcomeStatus.FAILED
    assert outcome.errors[0].error_code == "STRATEGY_ARTIFACT_SEMANTICS_INCOMPATIBLE"
    assert outcome.errors[0].expected is not None
    assert outcome.errors[0].context["consumer_role"] == "signal"
    assert strategy.called is False


class NonCallableArtifactRequirements(ArtifactStrategy):
    artifact_requirements = ()


class RaisingArtifactRequirements(ArtifactStrategy):
    def artifact_requirements(self) -> tuple[StrategyArtifactRequirement, ...]:
        raise RuntimeError("broken local Strategy declaration")


@pytest.mark.parametrize(
    "strategy",
    [
        NonCallableArtifactRequirements(()),
        RaisingArtifactRequirements(()),
    ],
)
def test_invalid_optional_requirement_method_is_a_typed_failure(
    tmp_path: Path,
    strategy: ArtifactStrategy,
) -> None:
    project = initialized_project(tmp_path)

    outcome = project.invoke(strategy, invocation("requirement-method"))

    assert outcome.status is OutcomeStatus.FAILED
    assert outcome.errors[0].error_code == "STRATEGY_ARTIFACT_REQUIREMENTS_FAILED"
    assert strategy.called is False


@pytest.mark.parametrize(
    ("requirements", "access_role", "payload_type", "error_code"),
    [
        ((), "undeclared", StoredSignalResult, "STRATEGY_ARTIFACT_ACCESS_UNDECLARED"),
        (
            (requirement("signal.required", "signal"),),
            "signal",
            StrategyResult,
            "STRATEGY_ARTIFACT_PAYLOAD_TYPE_MISMATCH",
        ),
    ],
)
def test_view_artifact_access_errors_keep_success_artifact_unpublished(
    tmp_path: Path,
    requirements: tuple[StrategyArtifactRequirement, ...],
    access_role: str,
    payload_type: type[StoredSignalResult] | type[StrategyResult],
    error_code: str,
) -> None:
    project = initialized_project(tmp_path)
    bindings: tuple[StrategyArtifactBinding, ...] = ()
    if requirements:
        selected = publish_signal(project, "signal:view-access")
        bindings = (
            StrategyArtifactBinding(
                consumer_role="signal",
                artifact_id=selected.artifact_id,
            ),
        )
    strategy = ArtifactStrategy(
        requirements,
        access_role=access_role,
        payload_type=payload_type,
    )

    outcome = project.invoke(strategy, invocation("view-access", *bindings))

    assert outcome.status is OutcomeStatus.FAILED
    assert outcome.errors[0].error_code == error_code
    assert not any(
        envelope.artifact_type == "strategy_result"
        for envelope in project.artifacts.list_envelopes()
    )