from datetime import UTC, datetime

import duckdb
import pytest

from qlibx import (
    ForwardReturnLabelModel,
    ForwardReturnLabelResult,
    MaterializationInvocation,
    OutcomeStatus,
)
from qlibx.data import ComponentRequirement, RowsLookback
from qlibx.operations import FORWARD_RETURN_LABEL_OUTPUT
from tests.acceptance.real_dw_support import (
    RealDwProject,
    register_real_forward_label_horizon,
)


def _at_close(day: int) -> datetime:
    return datetime(2024, 1, day, 6, 30, tzinfo=UTC)


class CountingRealForwardLabelModel:
    producer_id = "acceptance.real-forward-label"
    output_contract = FORWARD_RETURN_LABEL_OUTPUT

    def __init__(self) -> None:
        self._delegate = ForwardReturnLabelModel(
            "real-forward-label-prices",
            "real-forward-label-horizon",
            RowsLookback(rows=100_000),
            producer_id=self.producer_id,
        )
        self.calls = 0

    def requirements(self) -> tuple[ComponentRequirement, ...]:
        return self._delegate.requirements()

    def run(self, view: object) -> ForwardReturnLabelResult:
        self.calls += 1
        return self._delegate.run(view)  # type: ignore[arg-type]


def test_uc_pit_001_real_forward_label_fails_then_retries_without_lookahead(
    real_forward_label_case: RealDwProject,
) -> None:
    case = real_forward_label_case
    model = CountingRealForwardLabelModel()
    missing = case.project.materialize(
        model,
        MaterializationInvocation(
            invocation_id="uc-pit-001-missing-horizon",
            evaluation_time=_at_close(3),
            config_fingerprint="real-forward-label-v1",
        ),
    )

    assert missing.status is OutcomeStatus.FAILED
    assert missing.errors[0].requirement_id == "label.horizon_end"
    assert missing.errors[0].error_code == "REQUIREMENT_NOT_RESOLVED"
    assert model.calls == 0
    assert case.project.artifacts.list_envelopes() == ()
    failure = missing.diagnostics[0]

    register_real_forward_label_horizon(case)
    retry = case.project.materialize(
        model,
        MaterializationInvocation(
            invocation_id="uc-pit-001-valid-horizon",
            evaluation_time=_at_close(3),
            config_fingerprint="real-forward-label-v1",
            resolves_error_artifact_id=failure.artifact_id,
        ),
    )

    assert retry.status is OutcomeStatus.COMPLETE
    assert model.calls == 1
    result = retry.result.result
    assert len(result.entries) == 2
    assert {entry.observation_time.day for entry in result.entries} == {2}
    assert all(entry.available_at <= result.evaluation_time for entry in result.entries)

    expected = {
        ticker: float(end_value / start_value - 1.0)
        for ticker, start_value, end_value in duckdb.sql(
            f"""
            SELECT ticker, label_start_value, label_end_value
            FROM read_parquet('{case.source.as_posix()}')
            WHERE CAST(observation_time AS DATE) = DATE '2024-01-02'
            ORDER BY ticker
            """
        ).fetchall()
    }
    assert {entry.instrument: entry.value for entry in result.entries} == pytest.approx(expected)

    accesses = retry.result.accesses
    assert {access.semantic_role for access in accesses} == {
        "label_start_value",
        "label_end_value",
        "horizon_end",
    }
    assert all(access.max_available_at <= result.evaluation_time for access in accesses)
    dependencies = retry.result.artifact.dependencies
    assert any(
        edge.dependency_kind == "error"
        and edge.dependency_id == failure.artifact_id
        and edge.consumer_role == "resolves_error"
        for edge in dependencies
    )
    assert {edge.dependency_id for edge in dependencies if edge.dependency_kind == "dataset"} == {
        case.project.registry_snapshot().get("real-forward-label-prices").registration_identity,
        case.project.registry_snapshot().get("real-forward-label-horizon").registration_identity,
    }
    assert len(case.project.artifacts.list_envelopes(include_failure=True)) == 2
