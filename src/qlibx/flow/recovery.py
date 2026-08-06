"""Durable recovery contracts for local daily simulation."""

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from qlibx.account import AccountCheckpoint, MemorySnapshot
from qlibx.evidence import ArtifactContract, DependencyEdge
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


class SimulationRecoveryPoint(QlibxModel):
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


SIMULATION_RECOVERY_POINT_CONTRACT = ArtifactContract(
    artifact_type="simulation_recovery_point",
    artifact_schema_version=1,
    payload_model=SimulationRecoveryPoint,
)
