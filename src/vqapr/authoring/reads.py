"""What a Component declares it reads from a registered dataset, and that as engine requirements.

`inputs()` is how every role -- a DataModel, a StrategyModel, a Constraint -- says what it needs,
and it says it the same way: a `DatasetInput` per alias the author names. `requirements_for` is the
translation the engine applies to one of those, one `DataRequirement` per field.

This module sits below `component.py` rather than beside it, because `Component.requirements()`
reads a `DatasetInput` and `DataModel` is a `Component`: keeping the declaration below the class
that consumes it is what stops the two from importing each other.
"""

from __future__ import annotations

from pydantic import BaseModel, field_validator

from vqapr.authoring._validation import (
    _ROW_RESERVED_FIELDS,
    _VALUE_CONFIG,
    _identifier,
    _reject_reserved,
    _unique_identifiers,
)
from vqapr.data.lookback import Lookback
from vqapr.data.requirements import DataRequirement


class DatasetInput(BaseModel):
    """One declared, aliasable read of a registered dataset."""

    model_config = _VALUE_CONFIG

    dataset_id: str
    fields: tuple[str, ...]
    lookback: Lookback

    @field_validator("dataset_id")
    @classmethod
    def _dataset_id(cls, value: str) -> str:
        return _identifier(value, name="dataset_id")

    @field_validator("fields", mode="before")
    @classmethod
    def _fields(cls, value: object) -> tuple[str, ...]:
        # Before, not after: a list of names is accepted and becomes the detached tuple.
        fields = _unique_identifiers(value, name="fields")
        _reject_reserved(fields, _ROW_RESERVED_FIELDS, name="fields")
        return fields


def requirements_for(declaration: DatasetInput) -> tuple[DataRequirement, ...]:
    """One declared alias, as the engine's requirements: one per field (`docs/issues/archive/049`).

    The single place the fan-out is written. Every role that declares reads derives its
    requirements through here, so a Model cannot declare one thing to preflight and read another
    at the callback.
    """
    if not isinstance(declaration, DatasetInput):
        raise TypeError("declaration must be an authoring.DatasetInput")
    return tuple(
        DataRequirement.of(declaration.dataset_id, field, lookback=declaration.lookback)
        for field in declaration.fields
    )
