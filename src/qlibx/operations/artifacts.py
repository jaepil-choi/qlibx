"""Portable research artifact payload models."""

from datetime import datetime

from pydantic import Field, model_validator

from qlibx.models import QlibxModel


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