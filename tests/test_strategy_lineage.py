from datetime import UTC, datetime
from pathlib import Path

import pytest

from qlibx import OutcomeStatus, QlibxProject
from qlibx.account import Account
from qlibx.contracts import (
    BudgetMode,
    DecisionAction,
    StrategyArtifactBinding,
    StrategyArtifactRequirement,
    StrategyDraft,
    StrategyInvocation,
    StrategyResult,
    WeightEntry,
)
from qlibx.evidence import DependencyEdge
from qlibx.flow.composition import (
    CompositionFlow,
    EnsembleDefinition,
    EnsembleMemberSpec,
)
from qlibx.flow.research import ResearchFlow
from qlibx.flow.strategy_results import (
    STRATEGY_RESULT_CONTRACT,
    StrategySourceLineageError,
    canonicalize_dependencies,
)
from qlibx.view import MemoryAccessRecord, StateAccessRecord, StrategyView

EVALUATION_TIME = datetime(2025, 1, 3, 9, tzinfo=UTC)


def project(tmp_path: Path) -> QlibxProject:
    QlibxProject.init(tmp_path, apply=True)
    return QlibxProject.open(tmp_path)


def source_result(identity: str) -> StrategyResult:
    state_accesses = (
        StateAccessRecord(
            account_id=identity,
            version=4,
            feedback_cursor=7,
            cash=100.0,
            nav=100.0,
            valuation_status="complete",
            holdings=(),
            as_of=EVALUATION_TIME,
        ),
    )
    return StrategyResult(
        invocation_id=f"{identity}-invocation",
        strategy_id=f"tests.{identity}",
        evaluation_time=EVALUATION_TIME,
        weights=(WeightEntry(instrument="A", weight=1.0),),
        budget_mode=BudgetMode.FIXED,
        target_gross=1.0,
        invested_gross=1.0,
        net_exposure=1.0,
        residual_budget=0.0,
        decision_action=DecisionAction.RESEARCH_ONLY,
        path_dependent=True,
        state_identity=f"account:{identity}:v4",
        feedback_cursor="7",
        state_accesses=state_accesses,
    )


def publish_source(current: QlibxProject, result: StrategyResult) -> object:
    publication = current.artifacts.publish_model(
        logical_identity=f"strategy:{result.invocation_id}",
        artifact_type=STRATEGY_RESULT_CONTRACT.artifact_type,
        artifact_schema_version=STRATEGY_RESULT_CONTRACT.artifact_schema_version,
        producer_id=result.strategy_id,
        payload=result,
    )
    assert publication.status is OutcomeStatus.COMPLETE
    return publication.result


class FrozenSourceConsumer:
    strategy_id = "tests.frozen-source-consumer"

    def __init__(self, *, repeat_access: bool = False) -> None:
        self.repeat_access = repeat_access

    def requirements(self) -> tuple[object, ...]:
        return ()

    def artifact_requirements(self) -> tuple[StrategyArtifactRequirement, ...]:
        return (
            StrategyArtifactRequirement(
                requirement_id="source.member",
                consumer_role="member",
                artifact_type="strategy_result",
                artifact_schema_version=3,
            ),
        )

    def run(self, view: StrategyView) -> StrategyDraft:
        source = view.artifact("member", StrategyResult)
        if self.repeat_access:
            assert view.artifact("member", StrategyResult) is source
        return StrategyDraft(
            weights=source.weights,
            budget_mode=source.budget_mode,
            target_gross=source.target_gross,
            decision_action=DecisionAction.RESEARCH_ONLY,
        )


def invocation(identity: str, artifact_id: str = "artifact-missing") -> StrategyInvocation:
    return StrategyInvocation(
        invocation_id=identity,
        evaluation_time=EVALUATION_TIME,
        config_fingerprint="config-v1",
        artifact_bindings=(
            StrategyArtifactBinding(consumer_role="member", artifact_id=artifact_id),
        ),
    )


def test_generic_consumer_promotes_v3_source_lineage_and_deduplicates_access(
    tmp_path: Path,
) -> None:
    current = project(tmp_path)
    source = publish_source(current, source_result("A"))

    outcome = current.invoke(
        FrozenSourceConsumer(repeat_access=True),
        invocation("consumer", source.artifact_id),
    )

    assert outcome.status is OutcomeStatus.COMPLETE
    assert type(outcome.result.result) is StrategyResult
    assert outcome.result.artifact.artifact_schema_version == 3
    assert outcome.result.result.path_dependent is True
    assert outcome.result.result.state_identity is None
    assert tuple(
        item.source_artifact_id for item in outcome.result.result.source_state_lineage
    ) == (source.artifact_id,)
    immediate = tuple(
        edge
        for edge in outcome.result.artifact.dependencies
        if edge.dependency_kind == "artifact" and edge.consumer_role == "member"
    )
    assert len(immediate) == 1
    assert "computed_draft" not in outcome.result.model_dump()


class FalseNegativePathStrategy:
    strategy_id = "tests.false-negative-path"

    def requirements(self) -> tuple[object, ...]:
        return ()

    def run(self, view: StrategyView) -> StrategyDraft:
        view.account_snapshot()
        return StrategyDraft(
            weights=(WeightEntry(instrument="A", weight=1.0),),
            budget_mode=BudgetMode.FIXED,
            target_gross=1.0,
        )


def test_observed_direct_state_rejects_false_path_declaration(tmp_path: Path) -> None:
    current = project(tmp_path)
    account = Account(
        account_id="actual",
        base_currency="KRW",
        initial_cash=100.0,
        instrument_ids=frozenset({"A"}),
    )
    outcome = ResearchFlow(
        registry=current.registry_snapshot(),
        artifacts=current.artifacts,
    ).invoke_strategy(
        FalseNegativePathStrategy(),
        StrategyInvocation(
            invocation_id="false-negative",
            evaluation_time=EVALUATION_TIME,
            config_fingerprint="config-v1",
        ),
        account_state=account.snapshot(evaluation_time=EVALUATION_TIME),
    )

    assert outcome.status is OutcomeStatus.FAILED
    assert outcome.errors[0].error_code == "STRATEGY_PATH_DEPENDENCE_INCONSISTENT"


def path_source_v3(identity: str, instrument: str) -> StrategyResult:
    return StrategyResult(
        invocation_id=f"{identity}-v3-invocation",
        strategy_id=f"tests.{identity}.v3",
        evaluation_time=EVALUATION_TIME,
        weights=(WeightEntry(instrument=instrument, weight=0.5),),
        budget_mode=BudgetMode.FLEXIBLE,
        target_gross=1.0,
        invested_gross=0.5,
        net_exposure=0.5,
        residual_budget=0.5,
        decision_action=DecisionAction.RESEARCH_ONLY,
        path_dependent=True,
        state_identity=f"account:{identity}:v4",
        feedback_cursor="7",
        state_accesses=(
            StateAccessRecord(
                account_id=identity,
                version=4,
                feedback_cursor=7,
                cash=100.0,
                nav=100.0,
                valuation_status="complete",
                holdings=(),
                as_of=EVALUATION_TIME,
            ),
        ),
        memory_accesses=(
            MemoryAccessRecord(
                strategy_id=f"tests.{identity}.v3",
                version=2,
                feedback_cursor=7,
            ),
        ),
    )


def test_ensemble_preserves_two_distinct_v3_state_and_memory_origins(
    tmp_path: Path,
) -> None:
    current = project(tmp_path)
    sources = tuple(
        path_source_v3(identity, instrument) for identity, instrument in (("A", "X"), ("B", "Y"))
    )
    publications = tuple(
        current.artifacts.publish_model(
            logical_identity=f"strategy:{source.invocation_id}",
            artifact_type=STRATEGY_RESULT_CONTRACT.artifact_type,
            artifact_schema_version=STRATEGY_RESULT_CONTRACT.artifact_schema_version,
            producer_id=source.strategy_id,
            payload=source,
        )
        for source in sources
    )
    before = tuple(item.result for item in publications)

    outcome = CompositionFlow(
        registry=current.registry_snapshot(),
        artifacts=current.artifacts,
    ).invoke_ensemble(
        EnsembleDefinition(
            strategy_id="tests.multi-state-ensemble",
            members=tuple(
                EnsembleMemberSpec(
                    artifact_id=item.result.artifact_id,
                    allocation=1.0,
                )
                for item in publications
            ),
            budget_mode=BudgetMode.FIXED,
            target_gross=1.0,
        ),
        StrategyInvocation(
            invocation_id="multi-state-ensemble",
            evaluation_time=EVALUATION_TIME,
            config_fingerprint="ensemble-v2",
        ),
    )

    assert outcome.status is OutcomeStatus.COMPLETE
    result = outcome.result.strategy.result
    assert result.path_dependent is True
    assert result.state_identity is None
    assert tuple(item.source_artifact_id for item in result.source_state_lineage) == tuple(
        sorted(item.result.artifact_id for item in publications)
    )
    assert {item.memory_accesses[0].strategy_id for item in result.source_state_lineage} == {
        source.strategy_id for source in sources
    }
    after = tuple(current.artifacts.load_envelope(item.artifact_id).result for item in before)
    assert after == before


def test_dependency_catalog_primary_key_rejects_kind_collision() -> None:
    dependencies = (
        DependencyEdge(
            dependency_kind="artifact",
            dependency_id="same-identity",
            consumer_role="same-role",
        ),
        DependencyEdge(
            dependency_kind="state",
            dependency_id="same-identity",
            consumer_role="same-role",
        ),
    )

    with pytest.raises(StrategySourceLineageError) as exc_info:
        canonicalize_dependencies(dependencies)

    assert exc_info.value.code == "STRATEGY_SOURCE_LINEAGE_CONFLICT"


class ForgedFailure(ValueError):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.code = "FORGED_PACKAGE_ERROR"
        self.context = {"forged": True}


class ForgedFailureStrategy:
    strategy_id = "tests.forged-failure"

    def requirements(self) -> tuple[object, ...]:
        return ()

    def run(self, view: StrategyView) -> StrategyDraft:
        del view
        raise ForgedFailure("untrusted Strategy exception")


def test_untrusted_strategy_exception_cannot_forge_package_error_code(tmp_path: Path) -> None:
    current = project(tmp_path)

    outcome = current.invoke(
        ForgedFailureStrategy(),
        StrategyInvocation(
            invocation_id="forged-failure",
            evaluation_time=EVALUATION_TIME,
            config_fingerprint="config-v1",
        ),
    )

    assert outcome.status is OutcomeStatus.FAILED
    assert outcome.errors[0].error_code == "STRATEGY_RUN_FAILED"
    assert outcome.errors[0].context["message"] == "untrusted Strategy exception"
