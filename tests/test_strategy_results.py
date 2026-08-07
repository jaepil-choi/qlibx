from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from qlibx import (
    BudgetMode,
    DecisionAction,
    OutcomeStatus,
    QlibxProject,
    StrategyResult,
    StrategyResultV1,
    StrategySourceStateLineage,
    WeightEntry,
)
from qlibx.context import StateAccessRecord
from qlibx.flow.strategy_results import (
    STRATEGY_RESULT_CONTRACT,
    STRATEGY_RESULT_V1_CONTRACT,
    load_strategy_result,
)

EVALUATION_TIME = datetime(2025, 1, 3, 9, tzinfo=UTC)


def result_fields(identity: str) -> dict[str, object]:
    return {
        "invocation_id": identity,
        "strategy_id": "tests.versioned",
        "evaluation_time": EVALUATION_TIME,
        "weights": (WeightEntry(instrument="A", weight=1.0),),
        "budget_mode": BudgetMode.FIXED,
        "target_gross": 1.0,
        "invested_gross": 1.0,
        "net_exposure": 1.0,
        "residual_budget": 0.0,
        "decision_action": DecisionAction.RESEARCH_ONLY,
        "path_dependent": False,
    }


def project(tmp_path: Path) -> QlibxProject:
    QlibxProject.init(tmp_path, apply=True)
    return QlibxProject.open(tmp_path)


def test_exact_strategy_result_loader_dispatches_v1_and_v2(tmp_path: Path) -> None:
    current = project(tmp_path)
    v1 = StrategyResultV1(**result_fields("v1"))
    v2 = StrategyResult(**result_fields("v2"))
    published_v1 = current.artifacts.publish_model(
        logical_identity="strategy:v1",
        artifact_type=STRATEGY_RESULT_V1_CONTRACT.artifact_type,
        artifact_schema_version=STRATEGY_RESULT_V1_CONTRACT.artifact_schema_version,
        producer_id=v1.strategy_id,
        payload=v1,
    )
    published_v2 = current.artifacts.publish_model(
        logical_identity="strategy:v2",
        artifact_type=STRATEGY_RESULT_CONTRACT.artifact_type,
        artifact_schema_version=STRATEGY_RESULT_CONTRACT.artifact_schema_version,
        producer_id=v2.strategy_id,
        payload=v2,
    )

    loaded_v1 = load_strategy_result(current.artifacts, published_v1.result.artifact_id)
    loaded_v2 = load_strategy_result(current.artifacts, published_v2.result.artifact_id)

    assert loaded_v1.status is OutcomeStatus.COMPLETE
    assert loaded_v2.status is OutcomeStatus.COMPLETE
    assert type(loaded_v1.result.payload) is StrategyResultV1
    assert type(loaded_v2.result.payload) is StrategyResult


def test_strategy_result_loader_rejects_unknown_exact_schema(tmp_path: Path) -> None:
    current = project(tmp_path)
    legacy = StrategyResultV1(**result_fields("v3"))
    published = current.artifacts.publish_model(
        logical_identity="strategy:v3",
        artifact_type="strategy_result",
        artifact_schema_version=3,
        producer_id=legacy.strategy_id,
        payload=legacy,
    )

    loaded = load_strategy_result(current.artifacts, published.result.artifact_id)

    assert loaded.status is OutcomeStatus.FAILED
    assert loaded.errors[0].error_code == "STRATEGY_RESULT_SCHEMA_UNSUPPORTED"
    assert loaded.errors[0].context["actual_version"] == 3


def test_v2_distinguishes_inherited_lineage_from_direct_state() -> None:
    source = StrategySourceStateLineage(
        source_artifact_id="artifact-source",
        source_artifact_schema_version=2,
        source_invocation_id="source-invocation",
        source_strategy_id="tests.source",
        declared_state_identity="account:A:v4",
        state_accesses=(
            StateAccessRecord(
                account_id="A",
                version=4,
                feedback_cursor=7,
                cash=100.0,
                nav=100.0,
                valuation_status="complete",
                holdings=(),
                as_of=EVALUATION_TIME,
            ),
        ),
    )

    inherited = StrategyResult(
        **{
            **result_fields("consumer"),
            "path_dependent": True,
            "source_state_lineage": (source,),
        }
    )

    assert inherited.path_dependent is True
    assert inherited.state_identity is None
    assert inherited.source_state_lineage == (source,)


def test_v2_rejects_unobserved_or_unsorted_path_claims() -> None:
    with pytest.raises(ValidationError, match="path_dependent must match"):
        StrategyResult(**{**result_fields("false-claim"), "path_dependent": True})
