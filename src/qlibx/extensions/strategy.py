"""Contracts for validated project-local Strategy modules."""

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from qlibx.contracts import (
    StrategyArtifactBinding,
    StrategyArtifactRequirement,
    StrategyDraft,
)
from qlibx.data import ComponentRequirement
from qlibx.models import QlibxModel
from qlibx.view import (
    AccessRecord,
    ArtifactAccessRecord,
    FeedbackAccessRecord,
    SessionPerformanceAccessRecord,
    StateAccessRecord,
    StrategyStateAccessRecord,
)

_EXTENSION_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$"
_MODEL_SYMBOL_PATTERN = r"^[A-Za-z_][A-Za-z0-9_]*$"


class StrategyArtifactModelSpec(QlibxModel):
    artifact_type: str = Field(pattern=_EXTENSION_ID_PATTERN)
    artifact_schema_version: int = Field(ge=1)
    model_symbol: str = Field(pattern=_MODEL_SYMBOL_PATTERN)


class StrategyArtifactModelRegistration(QlibxModel):
    artifact_type: str
    artifact_schema_version: int = Field(ge=1)
    model_symbol: str
    json_schema_hash: str = Field(min_length=64, max_length=64)


class StrategyExtensionSpec(QlibxModel):
    extension_schema_version: Literal[1] = 1
    strategy_id: str = Field(pattern=_EXTENSION_ID_PATTERN)
    artifact_models: tuple[StrategyArtifactModelSpec, ...] = ()

    @model_validator(mode="after")
    def validate_artifact_models(self) -> "StrategyExtensionSpec":
        contracts = [
            (item.artifact_type, item.artifact_schema_version)
            for item in self.artifact_models
        ]
        symbols = [item.model_symbol for item in self.artifact_models]
        if len(contracts) != len(set(contracts)):
            raise ValueError("Strategy artifact model type/version pairs must be unique")
        if len(symbols) != len(set(symbols)):
            raise ValueError("Strategy artifact model symbols must be unique")
        return self


class StrategyExtensionValidationRequest(QlibxModel):
    invocation_id: str = Field(min_length=1)
    strategy_id: str = Field(pattern=_EXTENSION_ID_PATTERN)
    module_path: str = Field(min_length=1)
    evaluation_time: datetime
    config_fingerprint: str = Field(min_length=1)
    artifact_bindings: tuple[StrategyArtifactBinding, ...] = ()
    account_checkpoint_artifact_id: str | None = None
    session_performance_artifact_id: str | None = None
    feedback_entry_limit: int = Field(default=256, gt=0)

    @model_validator(mode="after")
    def validate_binding_roles(self) -> "StrategyExtensionValidationRequest":
        roles = [binding.consumer_role for binding in self.artifact_bindings]
        if len(roles) != len(set(roles)):
            raise ValueError("Strategy artifact binding roles must be unique")
        return self


class StrategyExtensionRegistration(QlibxModel):
    registration_schema_version: Literal[2] = 2
    extension_kind: Literal["strategy"] = "strategy"
    strategy_id: str
    module_path: str
    source_hash: str = Field(min_length=64, max_length=64)
    producer_id: str
    spec: StrategyExtensionSpec
    dataset_requirements: tuple[ComponentRequirement, ...]
    artifact_requirements: tuple[StrategyArtifactRequirement, ...]
    artifact_bindings: tuple[StrategyArtifactBinding, ...]
    artifact_models: tuple[StrategyArtifactModelRegistration, ...]
    evaluation_time: datetime
    config_fingerprint: str
    account_checkpoint_artifact_id: str | None = None
    session_performance_artifact_id: str | None = None
    validation_fingerprint: str = Field(min_length=64, max_length=64)
    validation_output_hash: str = Field(min_length=64, max_length=64)
    validation_output: StrategyDraft
    accesses: tuple[AccessRecord, ...] = ()
    artifact_accesses: tuple[ArtifactAccessRecord, ...] = ()
    state_accesses: tuple[StateAccessRecord, ...] = ()
    feedback_accesses: tuple[FeedbackAccessRecord, ...] = ()
    performance_accesses: tuple[SessionPerformanceAccessRecord, ...] = ()
    strategy_state_accesses: tuple[StrategyStateAccessRecord, ...] = ()


class RegisteredStrategyExtension(QlibxModel):
    registration_artifact_id: str = Field(min_length=1)
    registration: StrategyExtensionRegistration


class StrategyExtensionValidationResult(QlibxModel):
    registration_artifact_id: str = Field(min_length=1)
    registration: StrategyExtensionRegistration