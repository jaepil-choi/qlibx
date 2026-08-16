from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from vqapr.account.account import Account, AccountMode
from vqapr.account.snapshot import AccountSnapshot, AccountState
from vqapr.evidence.recorder import InvocationRecorder
from vqapr.evidence.tables import TableSpec
from vqapr.exchange.fills import Fill, FillBatch
from vqapr.flow.run_state import (
    LifecycleKind,
    LifecycleTrace,
    RunFinalization,
    RunStateRepository,
    capture_live_memory,
    restore_live_memory,
)
from vqapr.valuation.marks import Mark, MarkBatch

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


def _account_state() -> AccountState:
    return AccountState(AccountSnapshot(0, Decimal("100"), {"A": Decimal("1")}))


def _due_candidate(repository: RunStateRepository):
    account = Account(mode=AccountMode.LONG_ONLY)
    state = repository.root.account
    assert state is not None
    fill = FillBatch((Fill("A", Decimal("1"), Decimal("1"), Decimal("10")),), 0)
    prepared_fill = account.prepare_fill(state, fill, expected_version=0)
    marks = MarkBatch((Mark("A", Decimal("2"), Decimal("20"), Decimal("40")),), Decimal("40"))
    return fill, marks, account.prepare_mark(prepared_fill, marks, provenance={"at": "due"})


def test_prepared_state_is_not_visible_or_loadable_until_root_swap() -> None:
    repository = RunStateRepository()

    prepared = repository.prepare_callback(
        {"count": 1}, b"", lifecycle=LifecycleTrace(LifecycleKind.NO_DECISION)
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
    accepted = repository.accept_no_decision(memory, b"")
    memory["values"].append(2)

    loaded = repository.load_model_state(accepted.current_model_state_ref)
    loaded["values"].append(3)

    assert repository.load_model_state(accepted.current_model_state_ref) == {"values": [1]}


def test_optimistic_conflict_does_not_replace_current_root() -> None:
    repository = RunStateRepository()
    stale = repository.prepare_callback(
        {"count": 1}, b"", lifecycle=LifecycleTrace(LifecycleKind.NO_DECISION)
    )
    repository.accept_no_decision({"count": 2}, b"")

    with pytest.raises(RuntimeError, match="optimistic conflict"):
        repository.publish(stale)

    assert repository.root.version == 1
    assert repository.root.model_state_commit_count == 1


def test_no_decision_publishes_state_and_rows_but_keeps_pending_intent() -> None:
    pending = object()
    repository = RunStateRepository(pending_accepted_intent=pending)

    accepted = repository.accept_no_decision({"count": 1}, b"", recorder=_recorder())

    assert accepted.pending_accepted_intent is pending
    assert accepted.lifecycle_trace[-1].kind is LifecycleKind.NO_DECISION
    assert accepted.recorder_rows["diagnostics"][0]["sequence"] == 0


def test_accepted_intent_publishes_state_pending_and_rows_together() -> None:
    repository = RunStateRepository()
    intent = object()

    accepted = repository.accept_intent({"count": 1}, b"", intent, recorder=_recorder())

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
            {1: "invalid"}, b"", lifecycle=LifecycleTrace(LifecycleKind.NO_DECISION)
        )
    assert repository.root is before

    def fail_before_swap(_prepared: object) -> None:
        model.memory["count"] = 99
        raise RuntimeError("injected")

    failing = RunStateRepository(pending_accepted_intent="previous", before_swap=fail_before_swap)
    candidate = failing.prepare_callback(
        {"count": 2},
        b"",
        lifecycle=LifecycleTrace(LifecycleKind.NO_DECISION),
        recorder=_recorder(),
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


def test_due_candidate_publishes_account_marks_and_consumes_pending_once() -> None:
    pending = type("Pending", (), {"pending_id": "intent-1"})()
    repository = RunStateRepository(
        initial_account=_account_state(), pending_accepted_intent=pending
    )
    fill, marks, candidate = _due_candidate(repository)
    before = repository.root
    assert before.account is candidate.fill.source
    assert before.account.snapshot.cash == Decimal("100")
    assert before.account.mark_history == ()
    assert candidate.next_state.snapshot.cash == Decimal("90")
    assert candidate.next_state.latest_mark is not None

    with pytest.raises(RuntimeError, match="identity"):
        repository.prepare_due(
            pending_id="other",
            account=candidate,
            fill=fill,
            mark=marks,
        )
    assert repository.root is before

    accepted = repository.complete_due(
        pending_id="intent-1",
        account=candidate,
        fill=fill,
        mark=marks,
        feedback=("feedback",),
        evidence={"target": "exact"},
    )
    assert accepted.pending_accepted_intent is None
    assert accepted.account is candidate.next_state
    assert accepted.account.snapshot.version == 1
    assert accepted.account.latest_mark is not None
    assert accepted.account.latest_mark.nav == Decimal("130")
    assert accepted.feedback == ("feedback",)
    assert accepted.lifecycle_trace[-1].kind is LifecycleKind.DUE_EXECUTED
    with pytest.raises(RuntimeError, match="identity"):
        repository.complete_due(pending_id="intent-1", account=candidate, fill=fill, mark=marks)


def test_due_prepare_and_swap_faults_leave_account_pending_rows_and_marks_unchanged() -> None:
    pending = type("Pending", (), {"pending_id": "intent-1"})()
    repository = RunStateRepository(
        initial_account=_account_state(), pending_accepted_intent=pending
    )
    _fill, _marks, candidate = _due_candidate(repository)
    before = repository.root
    with pytest.raises(ValueError, match="exactly cover"):
        Account(mode=AccountMode.LONG_ONLY).prepare_mark(
            candidate.fill, MarkBatch((), Decimal("0")), provenance="bad"
        )
    assert repository.root is before

    failing = RunStateRepository(
        initial_account=_account_state(),
        pending_accepted_intent=pending,
        before_swap=lambda _prepared: (_ for _ in ()).throw(RuntimeError("injected")),
    )
    failing_fill, failing_marks, failing_candidate = _due_candidate(failing)
    old = failing.root
    with pytest.raises(RuntimeError, match="injected"):
        failing.complete_due(
            pending_id="intent-1",
            account=failing_candidate,
            fill=failing_fill,
            mark=failing_marks,
        )
    assert failing.root is old
    assert failing.root.pending_accepted_intent is pending
    assert failing.root.account == _account_state()
    assert not failing.root.recorder_rows


def test_typed_finalization_is_published_only_after_pending_is_empty() -> None:
    pending = type("Pending", (), {"pending_id": "intent-1"})()
    repository = RunStateRepository(pending_accepted_intent=pending)
    with pytest.raises(RuntimeError, match="pending"):
        repository.prepare_finalization(RunFinalization("done"))

    repository = RunStateRepository()
    prepared = repository.prepare_finalization(RunFinalization({"reason": "end"}))
    assert repository.root.finalization is None
    accepted = repository.publish(prepared)
    assert isinstance(accepted.finalization, RunFinalization)
    assert accepted.pending_accepted_intent is None
