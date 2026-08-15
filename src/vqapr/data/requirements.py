"""Logical observation requirements declared by consumers."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from vqapr.data.lookback import CalendarLookback, Lookback, RowsLookback
from vqapr.domain.identifiers import DatasetId, dataset_id

_RESERVED_FIELDS = frozenset({"available_at", "instrument"})


def _name(kind: str, raw: str) -> str:
    if not isinstance(raw, str):
        raise TypeError(f"{kind} must be a string")
    if not raw or any(character.isspace() for character in raw):
        raise ValueError(f"{kind} must be non-empty without whitespace")
    return raw


@dataclass(frozen=True, slots=True)
class DataRequirement:
    consumer_id: str
    dataset_id: DatasetId
    fields: tuple[str, ...]
    lookback: Lookback

    @classmethod
    def of(
        cls,
        raw_consumer_id: str,
        raw_dataset_id: str,
        *,
        fields: Sequence[str],
        lookback: Lookback,
    ) -> DataRequirement:
        consumer = _name("consumer_id", raw_consumer_id)
        selected = tuple(_name("framework field", field) for field in fields)
        if not selected:
            raise ValueError("fields must contain at least one framework field")
        if len(set(selected)) != len(selected):
            raise ValueError("framework fields must be unique")
        reserved = sorted(set(selected) & _RESERVED_FIELDS)
        if reserved:
            raise ValueError(f"framework fields are reserved by ModelWindow: {reserved}")
        if not isinstance(lookback, (RowsLookback, CalendarLookback)):
            raise TypeError("lookback must be RowsLookback or CalendarLookback")
        return cls(consumer, dataset_id(raw_dataset_id), selected, lookback)
