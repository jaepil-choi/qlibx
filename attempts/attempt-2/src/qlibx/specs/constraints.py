"""Public configuration for the current MVP constraint workflow."""

import hashlib
import json
from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from qlibx.models import QlibxModel
from qlibx.portfolio import (
    ConstraintAdjustmentRequest,
    ConstraintDeclaration,
    ConstraintMonitoringRequest,
    ConstraintValidationRequest,
    ExecutionLotInput,
)
from qlibx.runtime.clock import require_aware


def _fingerprint(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


class MvpConstraintPolicy(QlibxModel):
    """Supported no-short and PIT benchmark-relative single-name-cap policy."""

    policy_schema_version: Literal[1] = 1
    policy_id: str = Field(min_length=1)
    benchmark_weight_role: str = Field(default="benchmark_weight", min_length=1)
    benchmark_dataset_id: str | None = Field(default=None, min_length=1)
    single_name_floor: Literal[0.1] = 0.1
    no_short: Literal[True] = True

    def to_declaration(self) -> ConstraintDeclaration:
        """Translate the honest public support boundary to the internal operation contract."""

        return ConstraintDeclaration(
            declaration_id=self.policy_id,
            benchmark_weight_role=self.benchmark_weight_role,
            benchmark_dataset_id=self.benchmark_dataset_id,
            single_name_floor=self.single_name_floor,
            no_short=self.no_short,
        )


class ConstraintAdjustmentSpec(QlibxModel):
    """Frozen public input for one optional constraint-adjustment operation."""

    spec_schema_version: Literal[1] = 1
    invocation_id: str = Field(min_length=1)
    source_portfolio_artifact_id: str = Field(min_length=1)
    evaluation_time: datetime
    policy: MvpConstraintPolicy
    account_state_identity: str = Field(min_length=1)
    capital: float = Field(gt=0)
    lots: tuple[ExecutionLotInput, ...]

    @model_validator(mode="after")
    def validate_public_adjustment(self) -> "ConstraintAdjustmentSpec":
        require_aware(self.evaluation_time)
        instruments = tuple(item.instrument for item in self.lots)
        if len(instruments) != len(set(instruments)):
            raise ValueError("constraint execution lot inputs must be unique")
        return self

    def normalized_lots(self) -> tuple[ExecutionLotInput, ...]:
        """Return the mapping-like lot inputs in canonical instrument order."""

        return tuple(sorted(self.lots, key=lambda item: item.instrument))

    def frozen_config_fingerprint(self) -> str:
        """Hash policy and sizing configuration separately from invocation identity."""

        return _fingerprint(
            {
                "spec_schema_version": self.spec_schema_version,
                "policy": self.policy.model_dump(mode="json"),
                "capital": self.capital,
                "lots": [
                    item.model_dump(mode="json") for item in self.normalized_lots()
                ],
            }
        )

    def to_request(self) -> ConstraintAdjustmentRequest:
        return ConstraintAdjustmentRequest(
            invocation_id=self.invocation_id,
            source_portfolio_artifact_id=self.source_portfolio_artifact_id,
            evaluation_time=self.evaluation_time,
            config_fingerprint=self.frozen_config_fingerprint(),
            account_state_identity=self.account_state_identity,
            capital=self.capital,
            lots=self.normalized_lots(),
        )


class ConstraintValidationSpec(QlibxModel):
    """Frozen public input for independent validation of an adjustment artifact."""

    spec_schema_version: Literal[1] = 1
    invocation_id: str = Field(min_length=1)
    adjustment_artifact_id: str = Field(min_length=1)
    evaluation_time: datetime
    policy: MvpConstraintPolicy

    @model_validator(mode="after")
    def validate_public_validation(self) -> "ConstraintValidationSpec":
        require_aware(self.evaluation_time)
        return self

    def frozen_config_fingerprint(self) -> str:
        """Hash the independently selected validation policy."""

        return _fingerprint(
            {
                "spec_schema_version": self.spec_schema_version,
                "policy": self.policy.model_dump(mode="json"),
            }
        )

    def to_request(self) -> ConstraintValidationRequest:
        return ConstraintValidationRequest(
            invocation_id=self.invocation_id,
            adjustment_artifact_id=self.adjustment_artifact_id,
            evaluation_time=self.evaluation_time,
            config_fingerprint=self.frozen_config_fingerprint(),
        )


class ConstraintMonitoringSpec(QlibxModel):
    """Frozen public input for independent monitoring of committed Account state.

    ``evaluation_time`` is the single instant used for both Account valuation and the PIT
    benchmark cutoff. It should match the checkpoint's last mark time; a later instant makes any
    older held-position mark stale and returns ``ACCOUNT_VALUATION_STALE``.
    """

    spec_schema_version: Literal[1] = 1
    invocation_id: str = Field(min_length=1)
    checkpoint_artifact_id: str = Field(min_length=1)
    evaluation_time: datetime
    policy: MvpConstraintPolicy

    @model_validator(mode="after")
    def validate_public_monitoring(self) -> "ConstraintMonitoringSpec":
        require_aware(self.evaluation_time)
        return self

    def frozen_config_fingerprint(self) -> str:
        """Hash the independently selected monitoring policy."""

        return _fingerprint(
            {
                "spec_schema_version": self.spec_schema_version,
                "policy": self.policy.model_dump(mode="json"),
            }
        )

    def to_request(self) -> ConstraintMonitoringRequest:
        return ConstraintMonitoringRequest(
            invocation_id=self.invocation_id,
            config_fingerprint=self.frozen_config_fingerprint(),
        )
