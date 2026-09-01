"""Logical observation requirements declared by consumers."""

from __future__ import annotations

from dataclasses import dataclass

from vqapr.data.lookback import CalendarLookback, Lookback, RowsLookback

_RESERVED_FIELDS = frozenset({"available_at", "instrument"})


def _name(kind: str, raw: str) -> str:
    if not isinstance(raw, str):
        raise TypeError(f"{kind} must be a string")
    if not raw or any(character.isspace() for character in raw):
        raise ValueError(f"{kind} must be non-empty without whitespace")
    return raw


@dataclass(frozen=True, slots=True)
class DataRequirement:
    """One field, and how far back to read it. Nothing else (`docs/issues/049`).

    **No `dataset_id`.** A field id is an id, unique across the workspace, and the registration
    that declares it already knows which dataset it belongs to. Naming both said one fact twice,
    and the second saying could disagree with the first.

    **No `consumer_id`.** The component that declares a requirement *is* the consumer, so the
    framework stamps it rather than asking the author to repeat what it already knows. It still
    reaches `AccessRecord` exactly as before -- see `ModelWindow.for_consumer`.

    **One field, not a tuple.** Requirements are all declared before any read, so expressions over
    one dataset fuse into a single scan; asking for one field at a time therefore does not
    multiply scans (`docs/issues/046`).
    """

    field_id: str
    lookback: Lookback

    @classmethod
    def of(cls, raw_field_id: str, *, lookback: Lookback) -> DataRequirement:
        field_id = _name("framework field", raw_field_id)
        if field_id in _RESERVED_FIELDS:
            raise ValueError(f"framework field is reserved by ModelWindow: {field_id!r}")
        if not isinstance(lookback, (RowsLookback, CalendarLookback)):
            raise TypeError("lookback must be RowsLookback or CalendarLookback")
        return cls(field_id, lookback)
