from __future__ import annotations

from datetime import UTC, datetime

import pytest

from vqapr.evidence.recorder import InvocationRecorder
from vqapr.evidence.tables import TableSpec
from vqapr.flow.run_state import (
    LifecycleKind,
    LifecycleTrace,
    RunStateRepository,
    capture_live_memory,
    restore_live_memory,
)

NOW = datetime(2024, 3, 5, 4, tzinfo=UTC)


def _recorder() -> InvocationRecorder:
    recorder = InvocationRecorder(
        (TableSpec("diagnostics", ("message",)),),
        run_id="run-1",
        producer_id="strategy-1",
        stage="STRATEGY_CALLBACK",
        event_time=NOW,
    )
    recorder.append("diagnostics", {"message": "observed"})
    return recorder


def test_prepared_state_is_not_visible_or_loadable_until_root_swap() -> None:
    repository = RunStateRepository()

    prepared = repository.prepare_callback(
        {"count": 1}, lifecycle=LifecycleTrace(LifecycleKind.NO_DECISION)
    )

    assert repository.root.version == 0
    assert repository.root.model_state_commit_count == 0
    with pytest.raises(KeyError, match="unknown visible"):
        repository.load_model_state(prepared.root.current_model_state_ref)

    accepted = repository.publish(prepared)

    assert accepted.version == 1
    assert accepted.model_state_commit_count == 1
    assert repository.load_model_state(accepted.current_model_state_ref) == {"count": 1}


def test_visible_state_is_detached_from_candidate_and_loaded_values() -> None:
    repository = RunStateRepository()
    memory = {"values": [1]}
    accepted = repository.accept_no_decision(memory)
    memory["values"].append(2)

    loaded = repository.load_model_state(accepted.current_model_state_ref)
    loaded["values"].append(3)

    assert repository.load_model_state(accepted.current_model_state_ref) == {"values": [1]}


def test_optimistic_conflict_does_not_replace_current_root() -> None:
    repository = RunStateRepository()
    stale = repository.prepare_callback(
        {"count": 1}, lifecycle=LifecycleTrace(LifecycleKind.NO_DECISION)
    )
    repository.accept_no_decision({"count": 2})

    with pytest.raises(RuntimeError, match="optimistic conflict"):
        repository.publish(stale)

    assert repository.root.version == 1
    assert repository.root.model_state_commit_count == 1


def test_no_decision_publishes_state_and_rows_but_keeps_pending_intent() -> None:
    pending = object()
    repository = RunStateRepository(pending_accepted_intent=pending)

    accepted = repository.accept_no_decision({"count": 1}, recorder=_recorder())

    assert accepted.pending_accepted_intent is pending
    assert accepted.lifecycle_trace[-1].kind is LifecycleKind.NO_DECISION
    assert accepted.recorder_rows["diagnostics"][0]["sequence"] == 0


def test_accepted_intent_publishes_state_pending_and_rows_together() -> None:
    repository = RunStateRepository()
    intent = object()

    accepted = repository.accept_intent({"count": 1}, intent, recorder=_recorder())

    assert accepted.current_model_state_ref is not None
    assert accepted.pending_accepted_intent is intent
    assert accepted.lifecycle_trace[-1].kind is LifecycleKind.ACCEPTED_INTENT
    assert accepted.recorder_rows["diagnostics"][0]["message"] == "observed"


def test_prepare_and_before_swap_failures_leave_authority_and_live_memory_unchanged() -> None:
    repository = RunStateRepository(pending_accepted_intent="previous")
    before = repository.root
    model = type("Model", (), {"memory": {"count": 1}})()
    baseline = capture_live_memory(model.memory)

    with pytest.raises(TypeError):
        repository.prepare_callback(
            {1: "invalid"}, lifecycle=LifecycleTrace(LifecycleKind.NO_DECISION)
        )
    assert repository.root is before

    def fail_before_swap(_prepared: object) -> None:
        model.memory["count"] = 99
        raise RuntimeError("injected")

    failing = RunStateRepository(pending_accepted_intent="previous", before_swap=fail_before_swap)
    candidate = failing.prepare_callback(
        {"count": 2}, lifecycle=LifecycleTrace(LifecycleKind.NO_DECISION), recorder=_recorder()
    )
    old = failing.root
    with pytest.raises(RuntimeError, match="injected"):
        failing.publish(candidate)
    restore_live_memory(model, baseline)

    assert failing.root is old
    assert failing.root.model_state_commit_count == 0
    assert failing.root.pending_accepted_intent == "previous"
    assert not failing.root.recorder_rows
    assert model.memory == {"count": 1}


def test_reserved_flow_envelope_fields_are_rejected_at_declaration() -> None:
    with pytest.raises(ValueError, match="reserved"):
        TableSpec("diagnostics", ("event_time",))
