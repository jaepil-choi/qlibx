"""Durable recovery contracts for local daily simulation."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from qlibx.account import Account, AccountCheckpoint, JournalEntry, MemorySnapshot, Position
from qlibx.errors import OperationError, OutcomeStatus
from qlibx.evidence import (
    ArtifactContract,
    DependencyEdge,
    LocalArtifactBackend,
)
from qlibx.models import QlibxModel


class PendingExecutionRecovery(QlibxModel):
    """Enough durable identity to reload a published DecisionIntent."""

    decision_id: str = Field(min_length=1)
    intent_artifact_id: str = Field(min_length=1)
    execution_time: datetime
    commit_strategy_memory: bool


class RecoveryPublication(QlibxModel):
    artifact_type: Literal[
        "execution_result",
        "mark_result",
        "memory_commit",
    ]
    logical_identity: str = Field(min_length=1)
    producer_id: str = Field(min_length=1)
    artifact_schema_version: int = Field(ge=1)
    payload_json: str = Field(min_length=2)
    dependencies: tuple[DependencyEdge, ...] = ()


class SimulationRecoveryPointV1(QlibxModel):
    """A durable serialization of Account, Memory, and scheduler progress."""

    recovery_schema_version: Literal[1] = 1
    run_id: str = Field(min_length=1)
    request_fingerprint: str = Field(min_length=1)
    config_fingerprint: str = Field(min_length=1)
    profile_fingerprint: str = Field(min_length=1)
    registry_fingerprint: str = Field(min_length=1)
    strategy_id: str | None
    sequence: int = Field(ge=0)
    last_event_time: datetime | None = None
    last_event_priority: int | None = None
    last_event_name: str | None = None
    account_checkpoint: AccountCheckpoint
    memory_snapshots: tuple[MemorySnapshot, ...] = ()
    event_trace: tuple[str, ...] = ()
    completed_decision_ids: tuple[str, ...] = ()
    pending_executions: tuple[PendingExecutionRecovery, ...] = ()
    pending_publications: tuple[RecoveryPublication, ...] = ()

    @model_validator(mode="after")
    def validate_position(self) -> "SimulationRecoveryPoint":
        values = (
            self.last_event_time,
            self.last_event_priority,
            self.last_event_name,
        )
        if any(value is None for value in values) and any(value is not None for value in values):
            raise ValueError("recovery event position must be entirely present or absent")
        decision_ids = [item.decision_id for item in self.pending_executions]
        if len(decision_ids) != len(set(decision_ids)):
            raise ValueError("pending recovery decisions must be unique")
        return self


class SimulationRecoveryPoint(QlibxModel):
    """Latest live state plus deltas linked to the previous durable point."""

    recovery_schema_version: Literal[2] = 2
    run_id: str = Field(min_length=1)
    request_fingerprint: str = Field(min_length=1)
    config_fingerprint: str = Field(min_length=1)
    profile_fingerprint: str = Field(min_length=1)
    registry_fingerprint: str = Field(min_length=1)
    strategy_id: str | None
    sequence: int = Field(ge=0)
    previous_recovery_artifact_id: str | None = None
    last_event_time: datetime | None = None
    last_event_priority: int | None = None
    last_event_name: str | None = None
    account_id: str = Field(min_length=1)
    account_base_currency: str = Field(min_length=1)
    account_cash: float
    account_instrument_ids: tuple[str, ...]
    account_positions: tuple[Position, ...]
    account_version: int = Field(ge=0)
    account_as_of: datetime | None = None
    account_realized_pnl: tuple[tuple[str, float], ...] = ()
    account_journal_delta: tuple[JournalEntry, ...] = ()
    memory_snapshots: tuple[MemorySnapshot, ...] = ()
    event_trace_delta: tuple[str, ...] = ()
    completed_decision_ids_delta: tuple[str, ...] = ()
    pending_executions: tuple[PendingExecutionRecovery, ...] = ()
    pending_publications: tuple[RecoveryPublication, ...] = ()

    @model_validator(mode="after")
    def validate_position(self) -> "SimulationRecoveryPoint":
        values = (self.last_event_time, self.last_event_priority, self.last_event_name)
        if any(value is None for value in values) and any(value is not None for value in values):
            raise ValueError("recovery event position must be entirely present or absent")
        if self.sequence == 0 and self.previous_recovery_artifact_id is not None:
            raise ValueError("initial recovery point cannot link to a previous point")
        decision_ids = [item.decision_id for item in self.pending_executions]
        if len(decision_ids) != len(set(decision_ids)):
            raise ValueError("pending recovery decisions must be unique")
        return self


SIMULATION_RECOVERY_POINT_V1_CONTRACT = ArtifactContract(
    artifact_type="simulation_recovery_point",
    artifact_schema_version=1,
    payload_model=SimulationRecoveryPointV1,
)

SIMULATION_RECOVERY_POINT_CONTRACT = ArtifactContract(
    artifact_type="simulation_recovery_point",
    artifact_schema_version=2,
    payload_model=SimulationRecoveryPoint,
)


@dataclass(frozen=True, slots=True)
class DailyRecoveryIdentity:
    """Frozen identity shared by every point in one daily recovery chain."""

    run_id: str
    request_fingerprint: str
    config_fingerprint: str
    profile_fingerprint: str
    registry_fingerprint: str
    strategy_id: str | None


@dataclass(frozen=True, slots=True)
class DailyRecoveryWrite:
    """Complete state needed to append one recovery point without owning authorities."""

    account_checkpoint: AccountCheckpoint
    memory_snapshots: tuple[MemorySnapshot, ...]
    event_trace: tuple[str, ...]
    completed_decision_ids: tuple[str, ...]
    pending_executions: tuple[PendingExecutionRecovery, ...] = ()
    pending_publications: tuple[RecoveryPublication, ...] = ()
    event_time: datetime | None = None
    event_priority: int | None = None
    event_name: str | None = None


@dataclass(frozen=True, slots=True)
class RestoredDailyRecovery:
    """Validated authority snapshots and scheduler state returned to the daily Flow."""

    account_checkpoint: AccountCheckpoint
    memory_snapshots: tuple[MemorySnapshot, ...]
    event_trace: tuple[str, ...]
    completed_decision_ids: tuple[str, ...]
    pending_executions: tuple[PendingExecutionRecovery, ...]
    pending_publications: tuple[RecoveryPublication, ...]
    resume_position: tuple[datetime, int] | None


class DailyRecoveryIssue(Exception):
    """A recovery-specific failure that the Flow maps to its stable error contract."""

    def __init__(
        self,
        stage: str,
        code: str,
        *,
        context: dict[str, object] | None = None,
    ) -> None:
        super().__init__(code)
        self.stage = stage
        self.code = code
        self.context = context or {}


class DailyRecoveryDependencyErrors(Exception):
    """Typed artifact-loading errors that must pass through without remapping."""

    def __init__(self, errors: tuple[OperationError, ...]) -> None:
        super().__init__("daily recovery dependency failed")
        self.errors = errors


class DailyRecoveryCoordinator:
    """Own daily recovery identity, delta cursors, publication, and chain restore."""

    _MAX_SEQUENCE = 10**8

    def __init__(
        self,
        *,
        artifacts: LocalArtifactBackend,
        identity: DailyRecoveryIdentity,
        producer_id: str,
    ) -> None:
        self._artifacts = artifacts
        self._identity = identity
        self._producer_id = producer_id
        self._sequence = 0
        self._previous_artifact_id: str | None = None
        self._journal_cursor = 0
        self._trace_cursor = 0
        self._completed_cursor = 0

    @staticmethod
    def publication(
        *,
        artifact_type: Literal["execution_result", "mark_result", "memory_commit"],
        logical_identity: str,
        producer_id: str,
        payload: QlibxModel,
        artifact_schema_version: int = 1,
        dependencies: tuple[DependencyEdge, ...] = (),
    ) -> RecoveryPublication:
        return RecoveryPublication(
            artifact_type=artifact_type,
            logical_identity=logical_identity,
            producer_id=producer_id,
            artifact_schema_version=artifact_schema_version,
            payload_json=payload.model_dump_json(),
            dependencies=dependencies,
        )

    def publish(self, write: DailyRecoveryWrite) -> SimulationRecoveryPoint:
        initial = write.event_time is None
        sequence = 0 if initial else self._sequence + 1
        if sequence >= self._MAX_SEQUENCE:
            raise DailyRecoveryIssue(
                "recovery.sequence",
                "RECOVERY_SEQUENCE_EXHAUSTED",
                context={
                    "sequence": sequence,
                    "maximum_exclusive": self._MAX_SEQUENCE,
                },
            )
        if (
            len(write.account_checkpoint.journal) < self._journal_cursor
            or len(write.event_trace) < self._trace_cursor
            or len(write.completed_decision_ids) < self._completed_cursor
        ):
            raise DailyRecoveryIssue(
                "recovery.delta",
                "RECOVERY_DELTA_CURSOR_INVALID",
            )
        point = SimulationRecoveryPoint(
            run_id=self._identity.run_id,
            request_fingerprint=self._identity.request_fingerprint,
            config_fingerprint=self._identity.config_fingerprint,
            profile_fingerprint=self._identity.profile_fingerprint,
            registry_fingerprint=self._identity.registry_fingerprint,
            strategy_id=self._identity.strategy_id,
            sequence=sequence,
            previous_recovery_artifact_id=self._previous_artifact_id,
            last_event_time=write.event_time,
            last_event_priority=write.event_priority,
            last_event_name=write.event_name,
            account_id=write.account_checkpoint.account_id,
            account_base_currency=write.account_checkpoint.base_currency,
            account_cash=write.account_checkpoint.cash,
            account_instrument_ids=write.account_checkpoint.instrument_ids,
            account_positions=write.account_checkpoint.positions,
            account_version=write.account_checkpoint.version,
            account_as_of=write.account_checkpoint.as_of,
            account_realized_pnl=write.account_checkpoint.realized_pnl,
            account_journal_delta=(write.account_checkpoint.journal[self._journal_cursor :]),
            memory_snapshots=write.memory_snapshots,
            event_trace_delta=write.event_trace[self._trace_cursor :],
            completed_decision_ids_delta=(write.completed_decision_ids[self._completed_cursor :]),
            pending_executions=write.pending_executions,
            pending_publications=write.pending_publications,
        )
        suffix = (
            "initial"
            if initial
            else (
                f"{write.event_time.isoformat().replace('+00:00', 'Z')}:"
                f"{write.event_priority}:{write.event_name.lower()}"
            )
        )
        publication = self._artifacts.publish_model(
            logical_identity=(
                f"simulation-recovery:{self._identity.run_id}:{sequence:08d}:{suffix}"
            ),
            artifact_type="simulation_recovery_point",
            artifact_schema_version=2,
            producer_id=self._producer_id,
            payload=point,
            dependencies=(
                DependencyEdge(
                    dependency_kind="state",
                    dependency_id=(f"account:{point.account_id}:v{point.account_version}"),
                    consumer_role="recoverable_actual_state",
                ),
                *(
                    ()
                    if point.previous_recovery_artifact_id is None
                    else (
                        DependencyEdge(
                            dependency_kind="artifact",
                            dependency_id=point.previous_recovery_artifact_id,
                            consumer_role="previous_recovery_point",
                        ),
                    )
                ),
            ),
        )
        if publication.status is not OutcomeStatus.COMPLETE:
            raise DailyRecoveryIssue(
                "recovery.publish",
                "RECOVERY_POINT_PUBLICATION_FAILED",
                context={
                    "publication_errors": [
                        error.model_dump(mode="json") for error in publication.errors[:5]
                    ],
                },
            )
        self._sequence = sequence
        self._previous_artifact_id = publication.result.artifact_id
        self._journal_cursor = len(write.account_checkpoint.journal)
        self._trace_cursor = len(write.event_trace)
        self._completed_cursor = len(write.completed_decision_ids)
        return point

    def restore(self) -> RestoredDailyRecovery:
        prefix = f"simulation-recovery:{self._identity.run_id}:"
        envelope = self._artifacts.latest_envelope(
            artifact_type="simulation_recovery_point",
            logical_identity_prefix=prefix,
        )
        if envelope is None:
            raise DailyRecoveryIssue(
                "resume",
                "RECOVERY_POINT_NOT_FOUND",
                context={"run_id": self._identity.run_id},
            )
        latest_envelope = envelope
        seen: set[str] = set()
        v2_points: list[SimulationRecoveryPoint] = []
        anchor: SimulationRecoveryPointV1 | None = None
        expected_identity = self._identity_dict()
        while True:
            if envelope.artifact_id in seen:
                raise DailyRecoveryIssue(
                    "resume.chain",
                    "RECOVERY_CHAIN_CYCLE",
                    context={"artifact_id": envelope.artifact_id},
                )
            seen.add(envelope.artifact_id)
            contract = (
                SIMULATION_RECOVERY_POINT_CONTRACT
                if envelope.artifact_schema_version == 2
                else SIMULATION_RECOVERY_POINT_V1_CONTRACT
            )
            loaded = self._artifacts.load_model(envelope.artifact_id, contract)
            if loaded.status is not OutcomeStatus.COMPLETE:
                raise DailyRecoveryDependencyErrors(loaded.errors)
            loaded_point = loaded.result.payload
            actual_identity = self._point_identity(loaded_point)
            mismatches = self._mismatches(expected_identity, actual_identity)
            if mismatches and envelope.artifact_id == latest_envelope.artifact_id:
                raise DailyRecoveryIssue(
                    "resume.identity",
                    "RESUME_BRANCH_REQUIRED",
                    context={"mismatches": mismatches},
                )
            if not envelope.logical_identity.startswith(prefix) or mismatches:
                raise DailyRecoveryIssue(
                    "resume.chain",
                    "RECOVERY_CHAIN_IDENTITY_MISMATCH",
                    context={
                        "artifact_id": envelope.artifact_id,
                        "logical_identity": envelope.logical_identity,
                        "mismatches": mismatches,
                    },
                )
            if isinstance(loaded_point, SimulationRecoveryPointV1):
                anchor = loaded_point
                break
            v2_points.append(loaded_point)
            previous_id = loaded_point.previous_recovery_artifact_id
            if previous_id is None:
                break
            previous = self._artifacts.load_envelope(previous_id)
            if previous.status is not OutcomeStatus.COMPLETE:
                raise DailyRecoveryDependencyErrors(previous.errors)
            if previous.result.artifact_type != "simulation_recovery_point":
                raise DailyRecoveryIssue(
                    "resume.chain",
                    "RECOVERY_CHAIN_IDENTITY_MISMATCH",
                    context={"artifact_id": previous_id},
                )
            envelope = previous.result

        chronological = tuple(reversed(v2_points))
        journal = list(anchor.account_checkpoint.journal if anchor is not None else ())
        event_trace = list(anchor.event_trace if anchor is not None else ())
        completed = list(anchor.completed_decision_ids if anchor is not None else ())
        previous_version = anchor.account_checkpoint.version if anchor is not None else 0
        previous_sequence = anchor.sequence if anchor is not None else -1
        for candidate in chronological:
            if candidate.sequence != previous_sequence + 1:
                raise DailyRecoveryIssue(
                    "resume.chain",
                    "RECOVERY_CHAIN_SEQUENCE_GAP",
                    context={
                        "previous_sequence": previous_sequence,
                        "sequence": candidate.sequence,
                    },
                )
            if candidate.account_version != previous_version + len(candidate.account_journal_delta):
                raise DailyRecoveryIssue(
                    "resume.chain",
                    "RECOVERY_CHAIN_ACCOUNT_VERSION_GAP",
                    context={
                        "previous_version": previous_version,
                        "account_version": candidate.account_version,
                        "delta_length": len(candidate.account_journal_delta),
                    },
                )
            journal.extend(candidate.account_journal_delta)
            event_trace.extend(candidate.event_trace_delta)
            completed.extend(candidate.completed_decision_ids_delta)
            previous_version = candidate.account_version
            previous_sequence = candidate.sequence

        point: SimulationRecoveryPoint | SimulationRecoveryPointV1 = (
            v2_points[0] if v2_points else anchor
        )
        assert point is not None
        actual_identity = self._point_identity(point)
        mismatches = self._mismatches(expected_identity, actual_identity)
        if mismatches:
            raise DailyRecoveryIssue(
                "resume.identity",
                "RESUME_BRANCH_REQUIRED",
                context={"mismatches": mismatches},
            )
        if isinstance(point, SimulationRecoveryPointV1):
            restored_checkpoint = point.account_checkpoint
        else:
            restored_checkpoint = AccountCheckpoint(
                account_id=point.account_id,
                base_currency=point.account_base_currency,
                cash=point.account_cash,
                instrument_ids=point.account_instrument_ids,
                positions=point.account_positions,
                version=point.account_version,
                applied_events=tuple(sorted(entry.event_id for entry in journal)),
                journal=tuple(journal),
                as_of=point.account_as_of,
                realized_pnl=point.account_realized_pnl,
            )
        try:
            Account.from_checkpoint(restored_checkpoint)
        except ValueError as exc:
            raise DailyRecoveryIssue(
                "resume.chain",
                "RECOVERY_CHAIN_ACCOUNT_INVALID",
                context={"message": str(exc)[:500]},
            ) from exc

        self._sequence = point.sequence
        self._previous_artifact_id = latest_envelope.artifact_id
        self._journal_cursor = len(journal)
        self._trace_cursor = len(event_trace)
        self._completed_cursor = len(completed)
        resume_position = (
            (point.last_event_time, point.last_event_priority)
            if point.last_event_time is not None and point.last_event_priority is not None
            else None
        )
        return RestoredDailyRecovery(
            account_checkpoint=restored_checkpoint,
            memory_snapshots=point.memory_snapshots,
            event_trace=tuple(event_trace),
            completed_decision_ids=tuple(completed),
            pending_executions=point.pending_executions,
            pending_publications=point.pending_publications,
            resume_position=resume_position,
        )

    def _identity_dict(self) -> dict[str, object]:
        return {
            "run_id": self._identity.run_id,
            "request_fingerprint": self._identity.request_fingerprint,
            "config_fingerprint": self._identity.config_fingerprint,
            "profile_fingerprint": self._identity.profile_fingerprint,
            "registry_fingerprint": self._identity.registry_fingerprint,
            "strategy_id": self._identity.strategy_id,
        }

    @staticmethod
    def _point_identity(
        point: SimulationRecoveryPoint | SimulationRecoveryPointV1,
    ) -> dict[str, object]:
        return {
            "run_id": point.run_id,
            "request_fingerprint": point.request_fingerprint,
            "config_fingerprint": point.config_fingerprint,
            "profile_fingerprint": point.profile_fingerprint,
            "registry_fingerprint": point.registry_fingerprint,
            "strategy_id": point.strategy_id,
        }

    @staticmethod
    def _mismatches(
        expected: dict[str, object],
        actual: dict[str, object],
    ) -> dict[str, dict[str, object]]:
        return {
            key: {"expected": expected[key], "actual": actual[key]}
            for key in expected
            if expected[key] != actual[key]
        }
