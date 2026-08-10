"""Boundary contracts for logical dataset registration."""

from enum import StrEnum
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, model_validator

from qlibx.models import QlibxModel


class SourceFormat(StrEnum):
    CSV = "csv"
    PARQUET = "parquet"


class AvailableAtField(QlibxModel):
    kind: Literal["field"] = "field"
    field: str = Field(min_length=1)


class ConfirmedDelayRule(QlibxModel):
    kind: Literal["confirmed_delay"] = "confirmed_delay"
    source_field: str = Field(min_length=1)
    delay_seconds: int = Field(ge=0)
    rule_id: str = Field(min_length=1)
    user_confirmed: Literal[True]


AvailabilityBinding = Annotated[
    AvailableAtField | ConfirmedDelayRule,
    Field(discriminator="kind"),
]


class RowsLookback(QlibxModel):
    kind: Literal["rows"] = "rows"
    rows: int = Field(gt=0)


class CalendarLookback(QlibxModel):
    kind: Literal["calendar"] = "calendar"
    years: int = Field(default=0, ge=0)
    months: int = Field(default=0, ge=0)
    days: int = Field(default=0, ge=0)
    timezone: str = Field(min_length=1)
    month_end_policy: Literal["clamp"] = "clamp"

    @model_validator(mode="after")
    def validate_period(self) -> "CalendarLookback":
        if not (self.years or self.months or self.days):
            raise ValueError("calendar lookback requires a positive period")
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"unknown lookback timezone: {self.timezone!r}") from exc
        return self


Lookback = Annotated[
    RowsLookback | CalendarLookback,
    Field(discriminator="kind"),
]


class DatasetRegistration(QlibxModel):
    """User-confirmed minimal meaning for one physical dataset."""

    dataset_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
    source: str = Field(min_length=1)
    source_format: SourceFormat
    instrument_field: str = Field(min_length=1)
    observation_time_field: str | None = None
    source_timezone: str | None = Field(default=None, min_length=1)
    available_at: AvailabilityBinding
    logical_key: tuple[str, ...] = Field(min_length=1)
    semantic_bindings: dict[str, str] = Field(default_factory=dict)
    semantic_category: str | None = None
    source_provenance: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_minimal_key(self) -> "DatasetRegistration":
        if self.source_timezone is not None:
            try:
                ZoneInfo(self.source_timezone)
            except ZoneInfoNotFoundError as exc:
                raise ValueError(f"unknown source_timezone: {self.source_timezone!r}") from exc
        if len(set(self.logical_key)) != len(self.logical_key):
            raise ValueError("logical_key fields must be unique")
        if self.instrument_field not in self.logical_key:
            raise ValueError("logical_key must contain instrument_field")
        if (
            self.observation_time_field is not None
            and self.observation_time_field not in self.logical_key
        ):
            raise ValueError("logical_key must contain observation_time_field")
        time_field = (
            self.available_at.field
            if isinstance(self.available_at, AvailableAtField)
            else self.available_at.source_field
        )
        if time_field not in self.logical_key:
            raise ValueError("logical_key must contain the availability source field")
        if "instrument" in self.semantic_bindings or "available_at" in self.semantic_bindings:
            raise ValueError("instrument and available_at bindings use dedicated fields")
        return self


class RegistrationEvidence(QlibxModel):
    row_count: int = Field(ge=0)
    columns: tuple[str, ...]
    logical_key_unique: bool
    logical_key_null_count: int = Field(ge=0)
    available_at_min: str | None = None
    available_at_max: str | None = None
    localized_source_timezone: str | None = None


class DatasetQuerySnapshot(QlibxModel):
    path: str = Field(min_length=1)
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    row_count: int = Field(ge=0)
    columns: tuple[str, ...]
    logical_order_columns: tuple[str, ...]


class DatasetReindexItem(QlibxModel):
    dataset_id: str
    registration_identity: str
    snapshot_fingerprint: str
    changed: bool


class DatasetReindexResult(QlibxModel):
    items: tuple[DatasetReindexItem, ...]


class RegisteredDataset(QlibxModel):
    registration_schema_version: Literal[1, 2] = 1
    dataset_id: str
    registration_identity: str
    physical_fingerprint: str
    schema_fingerprint: str
    source: str
    source_format: SourceFormat
    instrument_field: str
    observation_time_field: str | None = None
    source_timezone: str | None = None
    available_at: AvailabilityBinding
    logical_key: tuple[str, ...]
    bindings: dict[str, str]
    source_bindings: dict[str, str] = Field(default_factory=dict)
    semantic_category: str | None = None
    source_provenance: str
    evidence: RegistrationEvidence
    query_snapshot: DatasetQuerySnapshot | None = None
