from __future__ import annotations

import pandas as pd
import pytest

from qlibx.errors import QlibxError
from qlibx.strategy import (
    DecisionContext,
    DecisionResult,
    FeedbackEvent,
    IntermediateRecord,
    NestedResearchRequest,
    StrategyDefinition,
    compose_child_result,
    evaluate_child,
    freeze_invocation,
    run_decision,
    run_decision_sequence,
)


def _definition() -> StrategyDefinition:
    return StrategyDefinition(
        "reversal.v1",
        "reversal",
        {"scale": 2.0},
        ("returns",),
        "weight",
        version="3",
    )


def _program(context: DecisionContext, parameters) -> DecisionResult:
    payload = context.datasets["returns"].tail(1) * parameters["scale"]
    count = int(context.memory.get("count", 0)) + 1
    return DecisionResult("weight", payload, memory={"count": count})


def _datasets(values: pd.DataFrame) -> dict[str, pd.DataFrame]:
    return {
        "universe": pd.DataFrame(True, index=values.index, columns=values.columns),
        "returns": values,
    }


def test_same_frozen_input_version_state_and_seed_has_same_identity() -> None:
    dates = pd.date_range("2025-01-01", periods=3)
    values = pd.DataFrame({"A": [1.0, 2.0, 3.0]}, index=dates)
    context = DecisionContext(dates[-1], _datasets(values), memory={"count": 4}, seed=11)
    first = run_decision(
        _definition(),
        _program,
        context,
        effective_config_id="config-1",
        dependency_versions={"qlibx": "0.1.0", "qlib": "0.9.7"},
    )
    second = run_decision(
        _definition(),
        _program,
        context,
        effective_config_id="config-1",
        dependency_versions={"qlibx": "0.1.0", "qlib": "0.9.7"},
    )
    assert first.invocation_id == second.invocation_id
    assert first.primary_result_id == second.primary_result_id
    assert first.result_id == second.result_id
    pd.testing.assert_frame_equal(first.payload, second.payload)
    assert first.invocation_id and first.primary_result_id and first.result_id
    changed = freeze_invocation(
        _definition(), DecisionContext(dates[-1], _datasets(values), seed=12)
    )
    assert changed.invocation_id != first.invocation_id


def test_availability_not_event_date_controls_no_look_ahead() -> None:
    future_event = pd.DatetimeIndex(["2025-03-01"])
    calendar = pd.DataFrame({"A": ["meeting"]}, index=future_event)
    known_on = pd.Series(pd.to_datetime(["2025-01-10"]), index=future_event)
    context = DecisionContext(
        "2025-02-01",
        {"returns": calendar},
        availability={"returns": known_on},
    )
    assert context.datasets["returns"].index[0] > context.decision_time

    too_late = pd.Series(pd.to_datetime(["2025-02-02"]), index=future_event)
    with pytest.raises(QlibxError) as leak:
        DecisionContext(
            "2025-02-01",
            {"returns": calendar},
            availability={"returns": too_late},
        )
    # The most expensive failure has to be recoverable without reading qlibx source: the
    # report names the boundary that decided it and the cell that crossed it.
    assert leak.value.code == "QLIBX_DECISION_LOOK_AHEAD"
    assert leak.value.context["boundary"] == "available_at"
    assert leak.value.context["decision_time"] == "2025-02-01T00:00:00"
    assert leak.value.context["violations"] == [
        {
            "row": "2025-03-01T00:00:00",
            "column": "A",
            "available_at": "2025-02-02T00:00:00",
        }
    ]

    # The other boundary: with no available_at the index is itself the availability claim,
    # and the refusal has to name the same contract rather than a second vocabulary.
    with pytest.raises(QlibxError) as by_index:
        DecisionContext("2025-02-01", {"returns": calendar})
    assert by_index.value.code == "QLIBX_DECISION_LOOK_AHEAD"
    assert by_index.value.context["boundary"] == "index"
    assert by_index.value.context["violations"] == ["2025-03-01T00:00:00"]


def test_child_composition_reuses_declared_payload_and_isolates_account() -> None:
    dates = pd.date_range("2025-01-01", periods=2)
    values = pd.DataFrame({"A": [1.0, 2.0]}, index=dates)
    parent = DecisionContext(dates[-1], _datasets(values), account={"cash": 100.0})
    request = NestedResearchRequest(
        _definition(),
        {"returns": values.tail(1)},
        "mean-weight",
        7,
        {"max_rows": 1},
    )
    nested = evaluate_child(parent, request, _program, lambda result: result.payload.mean().iloc[0])
    assert nested.status == "successful"
    assert nested.metric == pytest.approx(4.0)
    assert parent.account == {"cash": 100.0}

    composed = compose_child_result(nested.decision, lambda payload: payload / 2)
    assert composed.payload.iloc[0, 0] == pytest.approx(2.0)
    assert composed.intermediates[0].metadata["child_result_id"] == nested.decision.result_id


def test_child_cannot_change_parent_observation_or_account() -> None:
    dates = pd.date_range("2025-01-01", periods=2)
    values = pd.DataFrame({"A": [1.0, 2.0]}, index=dates)
    parent = DecisionContext(dates[-1], _datasets(values), account={"cash": 100.0})
    changed = values.tail(1).copy()
    changed.iloc[0, 0] = 999.0
    request = NestedResearchRequest(_definition(), {"returns": changed}, "mean", 1, {})
    result = evaluate_child(parent, request, _program, lambda decision: 0.0)
    assert result.status == "invalid"
    # A refused what-if stays an answer rather than a crash, and says why in a code the
    # caller can branch on. QlibxError is a RuntimeError, so this also pins that the
    # rejection path still catches the structured error it now raises.
    assert result.diagnostics["error_code"] == "QLIBX_DECISION_CHILD_OBSERVATIONS_CHANGED"
    assert parent.account == {"cash": 100.0}


def test_feedback_order_and_resume_match_uninterrupted_results() -> None:
    dates = pd.date_range("2025-01-01", periods=4)
    contexts = []
    for position, date in enumerate(dates):
        values = pd.DataFrame({"A": range(position + 1)}, index=dates[: position + 1])
        feedback = tuple(
            FeedbackEvent(dates[offset], "fill", {"quantity": offset})
            for offset in range(position + 1)
        )
        contexts.append(DecisionContext(date, _datasets(values), feedback_history=feedback))
    full = run_decision_sequence(_definition(), _program, contexts)
    first = run_decision_sequence(_definition(), _program, contexts, end_position=2)
    resumed = run_decision_sequence(
        _definition(),
        _program,
        contexts,
        checkpoint=first.checkpoint,
    )
    combined = first.results + resumed.results
    assert [result.result_id for result in combined] == [
        result.result_id for result in full.results
    ]
    for actual, expected in zip(combined, full.results, strict=True):
        pd.testing.assert_frame_equal(actual.payload, expected.payload)
    assert resumed.checkpoint == full.checkpoint

    with pytest.raises(QlibxError) as unconfirmed:
        DecisionContext(
            dates[0],
            {"returns": pd.DataFrame({"A": [1.0]}, index=dates[:1])},
            feedback_history=(FeedbackEvent(dates[1], "fill", {}),),
        )
    assert unconfirmed.value.code == "QLIBX_DECISION_FEEDBACK_UNCONFIRMED"
    assert unconfirmed.value.context["violations"] == [
        {"kind": "fill", "confirmed_at": "2025-01-02T00:00:00"}
    ]


def test_intermediate_recording_does_not_change_primary_result() -> None:
    date = pd.Timestamp("2025-01-01")
    values = pd.DataFrame({"A": [1.0]}, index=[date])
    context = DecisionContext(date, _datasets(values))
    plain = run_decision(_definition(), _program, context)

    def recorded(context: DecisionContext, parameters) -> DecisionResult:
        result = _program(context, parameters)
        return DecisionResult(
            result.kind,
            result.payload,
            memory=result.memory,
            intermediates=(IntermediateRecord("raw", 0, context.datasets["returns"]),),
        )

    with_record = run_decision(_definition(), recorded, context)
    assert with_record.primary_result_id == plain.primary_result_id
    assert with_record.result_id != plain.result_id
