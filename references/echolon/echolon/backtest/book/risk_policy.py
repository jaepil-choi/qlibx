"""Opaque risk-policy bindings for portfolio book backtests.

Echolon does not interpret how an upstream system estimated or selected a risk
policy.  It only binds the upstream artifact identity to the constructor target
that the book must actually use.
"""
from __future__ import annotations

import warnings
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


warnings.filterwarnings(
    "ignore",
    message='Field name "schema" in .* shadows an attribute in parent "BaseModel"',
    category=UserWarning,
    module=__name__,
)


RISK_POLICY_BINDING_SCHEMA = "risk-policy-binding/v1"


class RiskPolicyBinding(BaseModel):
    """Sealed identity and effective constructor target supplied by a policy owner.

    ``ConstructorConfig`` ultimately stores a Python ``float``.  Therefore an
    upstream owner must serialize this target as the canonical fixed-point form
    of ``Decimal(str(float(exact_decimal_target)))``.  Echolon compares that
    decimal exactly with ``Decimal(str(constructor_target_float))``.  This pins
    the value that can actually reach sizing, including Python's float rounding,
    while keeping the policy payload deliberately opaque.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    schema: Literal["risk-policy-binding/v1"] = RISK_POLICY_BINDING_SCHEMA
    policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    effective_constructor_vol_target_ann_pct: str

    @field_validator("effective_constructor_vol_target_ann_pct", mode="before")
    @classmethod
    def _canonical_positive_decimal(cls, value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError(
                "effective constructor volatility target must be a canonical "
                "decimal string"
            )
        try:
            number = Decimal(value)
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(
                "effective constructor volatility target must be a canonical "
                "decimal string"
            ) from exc
        if not number.is_finite() or number <= 0:
            raise ValueError(
                "effective constructor volatility target must be finite and positive"
            )

        fixed = format(number, "f")
        integer, separator, fraction = fixed.partition(".")
        fraction = fraction.rstrip("0")
        integer = integer.lstrip("0") or "0"
        canonical = f"{integer}.{fraction}" if separator and fraction else integer
        if value != canonical:
            raise ValueError(
                "effective constructor volatility target must use canonical "
                "fixed-point decimal notation"
            )
        return value
