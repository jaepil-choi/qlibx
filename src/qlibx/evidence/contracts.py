"""Portable artifact boundary contracts."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Generic, Literal, TypeVar

from pydantic import Field

from qlibx.models import QlibxModel


class ArtifactStatus(StrEnum):
    COMPLETE = "complete"
    FAILURE = "failure"


class PayloadFormat(StrEnum):
    JSON = "json"


class PublicationPhase(StrEnum):
    STAGED = "staged"
    PAYLOAD_STAGED = "payload_staged"
    PAYLOAD_PROMOTED = "payload_promoted"
    CATALOG_COMMITTED = "catalog_committed"
    RECOVERED_ABANDONED = "recovered_abandoned"


class RecoveryAction(StrEnum):
    REMOVED_ABANDONED = "removed_abandoned"


class DependencyEdge(QlibxModel):
    dependency_kind: Literal["artifact", "dataset", "config", "state", "error", "trigger"]
    dependency_id: str = Field(min_length=1)
    consumer_role: str = Field(min_length=1)
    selected_fields: tuple[str, ...] = ()
    compatibility_fingerprint: str | None = None


class ArtifactEnvelope(QlibxModel):
    envelope_schema_version: int = 1
    artifact_id: str
    logical_identity: str
    artifact_type: str
    artifact_schema_version: int = Field(ge=1)
    producer_id: str
    content_hash: str
    payload_format: PayloadFormat
    status: ArtifactStatus
    dependencies: tuple[DependencyEdge, ...] = ()


class PublicationEvent(QlibxModel):
    event_schema_version: Literal[1] = 1
    event_order: int = Field(ge=1)
    event_id: str = Field(min_length=1)
    attempt_id: str = Field(min_length=1)
    artifact_id: str = Field(min_length=1)
    logical_identity: str = Field(min_length=1)
    phase: PublicationPhase
    content_hash: str = Field(min_length=1)
    staging_path: str = Field(min_length=1)
    payload_path: str = Field(min_length=1)


class CatalogRecoveryRecord(QlibxModel):
    attempt_id: str = Field(min_length=1)
    artifact_id: str = Field(min_length=1)
    action: RecoveryAction
    removed_paths: tuple[str, ...] = ()


class CatalogRecoveryResult(QlibxModel):
    records: tuple[CatalogRecoveryRecord, ...] = ()


PayloadModel = TypeVar("PayloadModel", bound=QlibxModel)


@dataclass(frozen=True, slots=True)
class ArtifactContract(Generic[PayloadModel]):
    artifact_type: str
    artifact_schema_version: int
    payload_model: type[PayloadModel]


@dataclass(frozen=True, slots=True)
class LoadedArtifact(Generic[PayloadModel]):
    envelope: ArtifactEnvelope
    payload: PayloadModel
