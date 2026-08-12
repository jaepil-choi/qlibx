"""Shared models for validated package boundaries."""

from pydantic import BaseModel, ConfigDict


class QlibxModel(BaseModel):
    """Strict, immutable base for data crossing a qlibx boundary."""

    model_config = ConfigDict(
        strict=True,
        extra="forbid",
        frozen=True,
        validate_default=True,
    )
