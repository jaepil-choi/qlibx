"""Portable contracts for validated project-local transforms."""

import math
from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from qlibx.context import AccessRecord
from qlibx.data import ComponentRequirement
from qlibx.models import QlibxModel


class NeutralizationExtensionSpec(QlibxModel):
    """Declared data needs and identity for one neutralization transform."""

    extension_schema_version: Literal[1] = 1
    extension_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
    value_requirement: ComponentRequirement
    group_requirement: ComponentRequirement

    @model_validator(mode="after")
    def validate_roles(self) -> "NeutralizationExtensionSpec":
        if self.value_requirement.semantic_role == self.group_requirement.semantic_role:
            raise ValueError("value and group requirements must use different semantic roles")
        return self

    def requirements(self) -> tuple[ComponentRequirement, ...]:
        return self.value_requirement, self.group_requirement


class NeutralizationInputRow(QlibxModel):
    instrument: str = Field(min_length=1)
    group: str = Field(min_length=1)
    value: float

    @model_validator(mode="after")
    def validate_finite(self) -> "NeutralizationInputRow":
        if not math.isfinite(self.value):
            raise ValueError("neutralization input value must be finite")
        return self


class NeutralizationInput(QlibxModel):
    input_schema_version: Literal[1] = 1
    evaluation_time: datetime
    rows: tuple[NeutralizationInputRow, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_axis(self) -> "NeutralizationInput":
        instruments = [row.instrument for row in self.rows]
        if instruments != sorted(instruments):
            raise ValueError("neutralization input axis must be stably sorted")
        if len(instruments) != len(set(instruments)):
            raise ValueError("neutralization input instruments must be unique")
        return self


class NeutralizedValue(QlibxModel):
    instrument: str = Field(min_length=1)
    value: float

    @model_validator(mode="after")
    def validate_finite(self) -> "NeutralizedValue":
        if not math.isfinite(self.value):
            raise ValueError("neutralized value must be finite")
        return self


class NeutralizationResult(QlibxModel):
    result_schema_version: Literal[1] = 1
    extension_id: str = Field(min_length=1)
    values: tuple[NeutralizedValue, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_axis(self) -> "NeutralizationResult":
        instruments = [item.instrument for item in self.values]
        if len(instruments) != len(set(instruments)):
            raise ValueError("neutralization output instruments must be unique")
        return self


class ExtensionValidationRequest(QlibxModel):
    invocation_id: str = Field(min_length=1)
    extension_id: str = Field(min_length=1)
    module_path: str = Field(min_length=1)
    evaluation_time: datetime
    config_fingerprint: str = Field(min_length=1)


class ExtensionRegistration(QlibxModel):
    registration_schema_version: Literal[1] = 1
    extension_id: str
    extension_kind: Literal["neutralization_transform"] = "neutralization_transform"
    module_path: str
    source_hash: str
    producer_id: str
    spec: NeutralizationExtensionSpec
    validation_input_hash: str
    validation_output_hash: str
    validation_output: NeutralizationResult
    evaluation_time: datetime
    accesses: tuple[AccessRecord, ...]
