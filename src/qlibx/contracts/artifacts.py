"""Portable research artifact payload and input contracts."""

from datetime import datetime
from typing import TypeAlias

from pydantic import Field, field_validator, model_validator

from qlibx.models import QlibxModel

ArtifactSemanticScalar: TypeAlias = str | int | float | bool | None


class ArtifactSemanticConstraint(QlibxModel):
    """Require strict equality for one top-level scalar payload field."""

    field: str = Field(min_length=1)
    expected: ArtifactSemanticScalar

    @field_validator("field")
    @classmethod
    def validate_top_level_field(cls, value: str) -> str:
        if "." in value:
            raise ValueError("semantic constraint field must be a top-level field")
        return value


class StrategyArtifactRequirement(QlibxModel):
    """Declare one artifact contract consumed under a Strategy-local role."""

    requirement_id: str = Field(min_length=1)
    consumer_role: str = Field(min_length=1)
    artifact_type: str = Field(min_length=1)
    artifact_schema_version: int = Field(ge=1)
    semantic_constraints: tuple[ArtifactSemanticConstraint, ...] = ()

    @model_validator(mode="after")
    def validate_semantic_fields(self) -> "StrategyArtifactRequirement":
        fields = [constraint.field for constraint in self.semantic_constraints]
        if len(fields) != len(set(fields)):
            raise ValueError("semantic constraint fields must be unique")
        return self


class StrategyArtifactBinding(QlibxModel):
    """Freeze one Strategy consumer role to one exact artifact identity."""

    consumer_role: str = Field(min_length=1)
    artifact_id: str = Field(min_length=1)


class StoredSignalEntry(QlibxModel):
    instrument: str = Field(min_length=1)
    value: float


class StoredSignalResult(QlibxModel):
    signal_schema_version: int = 1
    signal_semantics: str = Field(min_length=1)
    observation_time: datetime
    entries: tuple[StoredSignalEntry, ...]

    @model_validator(mode="after")
    def validate_entries(self) -> "StoredSignalResult":
        instruments = [entry.instrument for entry in self.entries]
        if not instruments or len(instruments) != len(set(instruments)):
            raise ValueError("stored signal requires unique instrument entries")
        return self