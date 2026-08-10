from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from qlibx.account import Account, FillBatch
from qlibx.domain import Fill, Side
from qlibx.errors import CommitStatus, OperationError, OperationOutcome, OutcomeStatus
from qlibx.evidence import LocalArtifactBackend
from qlibx.flow.recovery import (
    DailyRecoveryCoordinator,
    DailyRecoveryIdentity,
    DailyRecoveryIssue,
    DailyRecoveryWrite,
    PendingExecutionRecovery,
    SimulationRecoveryPoint,
)
from qlibx.models import QlibxModel

EVENT_TIME = datetime(2025, 1, 2, 15, 30, tzinfo=UTC)


class RecoveryPayload(QlibxModel):
    value: str


def backend(root: Path) -> LocalArtifactBackend:
    return LocalArtifactBackend(
        root / ".qlibx" / "catalog.duckdb",
        root / ".qlibx" / "artifacts",
    )


def identity(*, config_fingerprint: str = "config-v1") -> DailyRecoveryIdentity:
    return DailyRecoveryIdentity(
        run_id="daily-recovery-unit",
        request_fingerprint="request-v1",
        config_fingerprint=config_fingerprint,
        profile_fingerprint="profile-v1",
        registry_fingerprint="registry-v1",
        strategy_id="strategy-v1",
    )


def account() -> Account:
    return Account(
        account_id="account-v1",
        base_currency="KRW",
        initial_cash=10_000,
        instrument_ids=frozenset({"A"}),
    )


def fill() -> Fill:
    return Fill(
        fill_id="fill-v1",
        instrument_id="A",
        side=Side.BUY,
        requested_quantity=10,
        dealt_quantity=10,
        price=100,
        trade_value=1_000,
        total_cost=1,
        cost_rule_id="cost-v1",
        schedule_version="schedule-v1",
    )


def coordinator(root: Path, *, selected_identity: DailyRecoveryIdentity | None = None):
    return DailyRecoveryCoordinator(
        artifacts=backend(root),
        identity=selected_identity or identity(),
        producer_id="profile-v1",
    )


def initial_write(current: Account) -> DailyRecoveryWrite:
    return DailyRecoveryWrite(
        account_checkpoint=current.checkpoint(),
        memory_snapshots=(),
        event_trace=(),
        completed_decision_ids=(),
    )


def test_coordinator_publishes_deltas_and_restores_typed_pending_state(
    tmp_path: Path,
) -> None:
    current = account()
    writer = coordinator(tmp_path)
    initial = writer.publish(initial_write(current))
    assert initial.sequence == 0
    assert initial.previous_recovery_artifact_id is None
    assert initial.account_journal_delta == ()

    current.commit(
        FillBatch(
            account_id="account-v1",
            event_id="execution-v1",
            as_of=EVENT_TIME,
            fills=(fill(),),
        ),
        expected_version=0,
    )
    pending = PendingExecutionRecovery(
        decision_id="decision-v1",
        intent_artifact_id="artifact-intent-v1",
        execution_time=EVENT_TIME,
        commit_strategy_memory=True,
    )
    pending_publication = DailyRecoveryCoordinator.publication(
        artifact_type="memory_commit",
        logical_identity="memory-commit:daily-recovery-unit:strategy-v1:v1",
        producer_id="strategy-v1",
        payload=RecoveryPayload(value="pending"),
    )
    appended = writer.publish(
        DailyRecoveryWrite(
            account_checkpoint=current.checkpoint(),
            memory_snapshots=(),
            event_trace=("execution-v1",),
            completed_decision_ids=("decision-v1",),
            pending_executions=(pending,),
            pending_publications=(pending_publication,),
            event_time=EVENT_TIME,
            event_priority=10,
            event_name="EXECUTION",
        )
    )
    assert appended.sequence == 1
    assert appended.previous_recovery_artifact_id is not None
    assert len(appended.account_journal_delta) == 1

    restored = coordinator(tmp_path).restore()
    assert restored.account_checkpoint == current.checkpoint()
    assert restored.event_trace == ("execution-v1",)
    assert restored.completed_decision_ids == ("decision-v1",)
    assert restored.pending_executions == (pending,)
    assert restored.pending_publications == (pending_publication,)
    assert restored.resume_position == (EVENT_TIME, 10)


def test_failed_publication_does_not_advance_recovery_cursors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected_backend = backend(tmp_path)
    current = account()
    writer = DailyRecoveryCoordinator(
        artifacts=selected_backend,
        identity=identity(),
        producer_id="profile-v1",
    )
    original_publish = selected_backend.publish_model
    failure = OperationError(
        operation="tests.daily_recovery",
        stage_path="tests.publish",
        error_code="TEST_PUBLICATION_FAILED",
        commit_status=CommitStatus.NONE,
        idempotency_identity="daily-recovery-unit",
        error_id="error-daily-recovery-unit",
    )
    monkeypatch.setattr(
        selected_backend,
        "publish_model",
        lambda **_: OperationOutcome(status=OutcomeStatus.FAILED, errors=(failure,)),
    )
    with pytest.raises(DailyRecoveryIssue) as failed:
        writer.publish(initial_write(current))
    assert failed.value.code == "RECOVERY_POINT_PUBLICATION_FAILED"

    monkeypatch.setattr(selected_backend, "publish_model", original_publish)
    retried = writer.publish(initial_write(current))
    assert retried.sequence == 0
    assert retried.previous_recovery_artifact_id is None


def test_latest_identity_mismatch_requires_a_new_branch(tmp_path: Path) -> None:
    writer = coordinator(tmp_path)
    writer.publish(initial_write(account()))

    changed = coordinator(
        tmp_path,
        selected_identity=identity(config_fingerprint="config-v2"),
    )
    with pytest.raises(DailyRecoveryIssue) as failed:
        changed.restore()
    assert failed.value.stage == "resume.identity"
    assert failed.value.code == "RESUME_BRANCH_REQUIRED"
    assert failed.value.context["mismatches"]["config_fingerprint"] == {
        "expected": "config-v2",
        "actual": "config-v1",
    }


class CycleBackend:
    def __init__(self) -> None:
        checkpoint = account().checkpoint()
        common = {
            "run_id": "daily-recovery-unit",
            "request_fingerprint": "request-v1",
            "config_fingerprint": "config-v1",
            "profile_fingerprint": "profile-v1",
            "registry_fingerprint": "registry-v1",
            "strategy_id": "strategy-v1",
            "account_id": checkpoint.account_id,
            "account_base_currency": checkpoint.base_currency,
            "account_cash": checkpoint.cash,
            "account_instrument_ids": checkpoint.instrument_ids,
            "account_positions": checkpoint.positions,
            "account_version": checkpoint.version,
        }
        self.points = {
            "artifact-a": SimulationRecoveryPoint(
                **common,
                sequence=2,
                previous_recovery_artifact_id="artifact-b",
            ),
            "artifact-b": SimulationRecoveryPoint(
                **common,
                sequence=1,
                previous_recovery_artifact_id="artifact-a",
            ),
        }
        self.envelopes = {
            artifact_id: SimpleNamespace(
                artifact_id=artifact_id,
                artifact_schema_version=2,
                artifact_type="simulation_recovery_point",
                logical_identity=f"simulation-recovery:daily-recovery-unit:{index:08d}:cycle",
            )
            for index, artifact_id in enumerate(("artifact-a", "artifact-b"), start=1)
        }

    def latest_envelope(self, **_: object) -> object:
        return self.envelopes["artifact-a"]

    def load_model(self, artifact_id: str, _: object) -> OperationOutcome[object]:
        return OperationOutcome(
            status=OutcomeStatus.COMPLETE,
            result=SimpleNamespace(payload=self.points[artifact_id]),
        )

    def load_envelope(self, artifact_id: str) -> OperationOutcome[object]:
        return OperationOutcome(
            status=OutcomeStatus.COMPLETE,
            result=self.envelopes[artifact_id],
        )


def test_cycle_is_rejected_before_state_is_returned() -> None:
    selected = DailyRecoveryCoordinator(
        artifacts=CycleBackend(),  # type: ignore[arg-type]
        identity=identity(),
        producer_id="profile-v1",
    )
    with pytest.raises(DailyRecoveryIssue) as failed:
        selected.restore()
    assert failed.value.stage == "resume.chain"
    assert failed.value.code == "RECOVERY_CHAIN_CYCLE"
