"""Typed contracts and built-ins for optional research-data materialization."""

import math
from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar, Generic, Literal, Protocol, TypeVar

import pandas as pd
from pydantic import Field, model_validator

from qlibx.context import MaterializeView
from qlibx.data import ComponentRequirement
from qlibx.models import QlibxModel

PayloadModel = TypeVar("PayloadModel", bound=QlibxModel)


@dataclass(frozen=True, slots=True)
class MaterializationOutputContract(Generic[PayloadModel]):
    """Operation-owned output declaration translated to storage only by a Flow."""

    artifact_type: str
    artifact_schema_version: int
    payload_model: type[PayloadModel]

    def __post_init__(self) -> None:
        if not self.artifact_type:
            raise ValueError("materialization artifact_type must not be empty")
        if self.artifact_schema_version < 1:
            raise ValueError("materialization artifact_schema_version must be positive")
        if not isinstance(self.payload_model, type) or not issubclass(
            self.payload_model,
            QlibxModel,
        ):
            raise TypeError("materialization payload_model must be a QlibxModel subclass")


class MaterializationInvocation(QlibxModel):
    invocation_id: str = Field(min_length=1)
    evaluation_time: datetime
    config_fingerprint: str = Field(min_length=1)
    resolves_error_artifact_id: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_evaluation_time(self) -> "MaterializationInvocation":
        if self.evaluation_time.tzinfo is None or self.evaluation_time.utcoffset() is None:
            raise ValueError("materialization evaluation_time must be timezone-aware")
        return self


class MaterializationOperation(Protocol[PayloadModel]):
    producer_id: str
    output_contract: MaterializationOutputContract[PayloadModel]

    def requirements(self) -> tuple[ComponentRequirement, ...]: ...

    def run(self, view: MaterializeView) -> PayloadModel: ...


class MaterializationComputationError(ValueError):
    """Known deterministic rejection of frozen materialization inputs."""

    def __init__(self, code: str, message: str, *, context: dict[str, object] | None = None):
        self.code = code
        self.context = context or {}
        super().__init__(message)


class ForwardReturnLabelEntry(QlibxModel):
    instrument: str = Field(min_length=1)
    observation_time: datetime
    horizon_end: datetime
    available_at: datetime
    start_value: float
    end_value: float
    value: float

    @model_validator(mode="after")
    def validate_label(self) -> "ForwardReturnLabelEntry":
        for field_name in ("observation_time", "horizon_end", "available_at"):
            timestamp = getattr(self, field_name)
            if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                raise ValueError(f"{field_name} must be timezone-aware")
        if not self.observation_time < self.horizon_end <= self.available_at:
            raise ValueError(
                "forward label requires observation_time < horizon_end <= available_at"
            )
        if not math.isfinite(self.start_value) or self.start_value <= 0:
            raise ValueError("forward label start_value must be finite and positive")
        if not math.isfinite(self.end_value) or self.end_value <= 0:
            raise ValueError("forward label end_value must be finite and positive")
        expected = self.end_value / self.start_value - 1.0
        if not math.isfinite(self.value) or not math.isclose(
            self.value,
            expected,
            rel_tol=1e-12,
            abs_tol=1e-15,
        ):
            raise ValueError("forward label value does not match end_value / start_value - 1")
        return self


class ForwardReturnLabelResult(QlibxModel):
    label_schema_version: Literal[1] = 1
    semantic_category: Literal["label"] = "label"
    label_semantics: Literal["simple_forward_return"] = "simple_forward_return"
    axis: Literal["instrument_time"] = "instrument_time"
    unit: Literal["decimal_return"] = "decimal_return"
    evaluation_time: datetime
    entries: tuple[ForwardReturnLabelEntry, ...]

    @model_validator(mode="after")
    def validate_result(self) -> "ForwardReturnLabelResult":
        if self.evaluation_time.tzinfo is None or self.evaluation_time.utcoffset() is None:
            raise ValueError("forward label evaluation_time must be timezone-aware")
        if not self.entries:
            raise ValueError("forward label result requires at least one entry")
        keys = tuple((entry.observation_time, entry.instrument) for entry in self.entries)
        if len(keys) != len(set(keys)):
            raise ValueError("forward label result keys must be unique")
        if keys != tuple(sorted(keys)):
            raise ValueError("forward label result entries must use canonical key order")
        if any(entry.available_at > self.evaluation_time for entry in self.entries):
            raise ValueError("forward label result contains a future-hidden entry")
        return self


FORWARD_RETURN_LABEL_OUTPUT = MaterializationOutputContract(
    artifact_type="forward_return_label_result",
    artifact_schema_version=1,
    payload_model=ForwardReturnLabelResult,
)


@dataclass(frozen=True, slots=True)
class ForwardReturnLabelModel:
    """Materialize simple forward returns from explicitly bound start/end/horizon data."""

    price_dataset_id: str
    horizon_dataset_id: str
    producer_id: str = "qlibx.forward-return-label.v1"

    output_contract: ClassVar[MaterializationOutputContract[ForwardReturnLabelResult]] = (
        FORWARD_RETURN_LABEL_OUTPUT
    )

    def __post_init__(self) -> None:
        if not self.price_dataset_id or not self.horizon_dataset_id:
            raise ValueError("forward label dataset IDs must not be empty")
        if not self.producer_id:
            raise ValueError("forward label producer_id must not be empty")

    def requirements(self) -> tuple[ComponentRequirement, ...]:
        return (
            ComponentRequirement(
                requirement_id="label.start_value",
                semantic_role="label_start_value",
                dataset_id=self.price_dataset_id,
            ),
            ComponentRequirement(
                requirement_id="label.end_value",
                semantic_role="label_end_value",
                dataset_id=self.price_dataset_id,
            ),
            ComponentRequirement(
                requirement_id="label.horizon_end",
                semantic_role="horizon_end",
                dataset_id=self.horizon_dataset_id,
            ),
        )

    def run(self, view: MaterializeView) -> ForwardReturnLabelResult:
        start = self._role_frame(view, "label_start_value")
        end = self._role_frame(view, "label_end_value")
        horizon = self._role_frame(view, "horizon_end")
        frames = {
            "label_start_value": start,
            "label_end_value": end,
            "horizon_end": horizon,
        }
        if any(frame.empty for frame in frames.values()):
            raise MaterializationComputationError(
                "FORWARD_LABEL_INPUT_EMPTY",
                "no complete forward-label input is visible at the evaluation time",
                context={role: len(frame) for role, frame in frames.items()},
            )

        key_columns = ["instrument", "observation_time"]
        key_sets = {
            role: set(frame[key_columns].itertuples(index=False, name=None))
            for role, frame in frames.items()
        }
        expected_keys = key_sets["label_start_value"]
        if any(keys != expected_keys for keys in key_sets.values()):
            union = set().union(*key_sets.values())
            raise MaterializationComputationError(
                "FORWARD_LABEL_COVERAGE_MISMATCH",
                "forward-label roles do not have identical instrument/time coverage",
                context={
                    "role_counts": {role: len(keys) for role, keys in key_sets.items()},
                    "mismatched_keys": [
                        {"instrument": str(instrument), "observation_time": str(timestamp)}
                        for instrument, timestamp in sorted(union)
                        if any((instrument, timestamp) not in keys for keys in key_sets.values())
                    ][:20],
                },
            )

        merged = start.merge(end, on=key_columns, how="inner", validate="one_to_one").merge(
            horizon,
            on=key_columns,
            how="inner",
            validate="one_to_one",
        )
        start_values = pd.to_numeric(merged["label_start_value"], errors="coerce")
        end_values = pd.to_numeric(merged["label_end_value"], errors="coerce")
        invalid_values = (
            ~start_values.map(math.isfinite)
            | ~end_values.map(math.isfinite)
            | (start_values <= 0)
            | (end_values <= 0)
        )
        if bool(invalid_values.any()):
            raise MaterializationComputationError(
                "FORWARD_LABEL_VALUE_INVALID",
                "forward-label start/end values must be finite and positive",
                context={"invalid_rows": int(invalid_values.sum())},
            )

        horizon_ends = pd.to_datetime(merged["horizon_end"], utc=True, errors="coerce")
        effective_available = merged[
            [
                "label_start_value_available_at",
                "label_end_value_available_at",
                "horizon_end_available_at",
            ]
        ].max(axis=1)
        invalid_horizons = (
            horizon_ends.isna()
            | (merged["observation_time"] >= horizon_ends)
            | (horizon_ends > effective_available)
            | (effective_available > view.as_of)
        )
        if bool(invalid_horizons.any()):
            raise MaterializationComputationError(
                "FORWARD_LABEL_HORIZON_INVALID",
                "forward-label horizon or availability ordering is invalid",
                context={"invalid_rows": int(invalid_horizons.sum())},
            )

        entries = tuple(
            ForwardReturnLabelEntry(
                instrument=str(row.instrument),
                observation_time=row.observation_time.to_pydatetime(),
                horizon_end=row.horizon_end.to_pydatetime(),
                available_at=row.effective_available.to_pydatetime(),
                start_value=float(row.label_start_value),
                end_value=float(row.label_end_value),
                value=float(row.label_end_value / row.label_start_value - 1.0),
            )
            for row in (
                merged.assign(
                    label_start_value=start_values,
                    label_end_value=end_values,
                    horizon_end=horizon_ends,
                    effective_available=effective_available,
                )
                .sort_values(["observation_time", "instrument"], kind="mergesort")
                .itertuples(index=False)
            )
        )
        return ForwardReturnLabelResult(evaluation_time=view.as_of, entries=entries)

    @staticmethod
    def _role_frame(view: MaterializeView, role: str) -> pd.DataFrame:
        frame = view.history(role)
        keys = ["instrument", "observation_time"]
        if frame["observation_time"].isna().any():
            raise MaterializationComputationError(
                "FORWARD_LABEL_HORIZON_INVALID",
                "forward-label inputs require observation_time",
                context={"semantic_role": role},
            )
        duplicates = frame.duplicated(subset=keys)
        if bool(duplicates.any()):
            raise MaterializationComputationError(
                "FORWARD_LABEL_COVERAGE_MISMATCH",
                "forward-label input keys must be unique per role",
                context={"semantic_role": role, "duplicate_rows": int(duplicates.sum())},
            )
        return frame[[*keys, "available_at", role]].rename(
            columns={"available_at": f"{role}_available_at"}
        )
