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
    StrategySourceStateLineage,
    WeightEntry,
)
from qlibx.flow.strategy_results import STRATEGY_RESULT_CONTRACT, load_strategy_result
from qlibx.view import StateAccessRecord

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


def test_exact_strategy_result_loader_accepts_only_v4(tmp_path: Path) -> None:
    current = project(tmp_path)
    payload = StrategyResult(**result_fields("canonical"))
    canonical = current.artifacts.publish_model(
        logical_identity="strategy:canonical",
        artifact_type="strategy_result",
        artifact_schema_version=4,
        producer_id=payload.strategy_id,
        payload=payload,
    )
    assert canonical.status is OutcomeStatus.COMPLETE

    loaded = load_strategy_result(current.artifacts, canonical.result.artifact_id)

    assert loaded.status is OutcomeStatus.COMPLETE
    assert type(loaded.result.payload) is StrategyResult
    assert STRATEGY_RESULT_CONTRACT.artifact_schema_version == 4


@pytest.mark.parametrize("legacy_version", [1, 2, 3])
def test_strategy_result_loader_rejects_legacy_versions(
    tmp_path: Path,
    legacy_version: int,
) -> None:
    current = project(tmp_path)
    payload = StrategyResult(**result_fields(f"legacy-v{legacy_version}"))
    published = current.artifacts.publish_model(
        logical_identity=f"strategy:legacy-v{legacy_version}",
        artifact_type="strategy_result",
        artifact_schema_version=legacy_version,
        producer_id=payload.strategy_id,
        payload=payload,
    )

    loaded = load_strategy_result(current.artifacts, published.result.artifact_id)

    assert loaded.status is OutcomeStatus.FAILED
    assert loaded.errors[0].error_code == "STRATEGY_RESULT_SCHEMA_UNSUPPORTED"
    assert loaded.errors[0].context["actual_version"] == legacy_version
    assert loaded.errors[0].retry_preconditions == (
        "rerun the Strategy producer to create strategy_result:v4",
    )


def test_v4_distinguishes_inherited_lineage_from_direct_state() -> None:
    source = StrategySourceStateLineage(
        source_artifact_id="artifact-source",
        source_artifact_schema_version=4,
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


def test_v4_rejects_unobserved_path_claim() -> None:
    with pytest.raises(ValidationError, match="path_dependent must match"):
        StrategyResult(**{**result_fields("false-claim"), "path_dependent": True})
