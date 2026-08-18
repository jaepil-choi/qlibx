"""Declared diagnostic table schemas and Flow-owned recorder envelope fields."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

FLOW_ENVELOPE_FIELDS = frozenset({"run_id", "producer_id", "stage", "event_time", "sequence"})


@dataclass(frozen=True, slots=True)
class TableSpec:
    """A closed user-column declaration for one write-only recorder table."""

    table_id: str
    fields: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.table_id, str) or not self.table_id.strip():
            raise ValueError("table_id must be a non-empty string")
        # A table id is a name a human reads back later. Control and format characters are
        # invisible, so they cannot help a reader and can only disguise one name as another --
        # including as a package-owned name. Rejecting them here closes that at the validation
        # boundary rather than leaving each consumer to normalise defensively.
        hidden = sorted({ch for ch in self.table_id if unicodedata.category(ch) in {"Cc", "Cf"}})
        if hidden:
            raise ValueError(
                "table_id must not contain control or format characters: "
                f"{[hex(ord(ch)) for ch in hidden]}"
            )
        if not isinstance(self.fields, tuple):
            raise TypeError("fields must be a tuple of field names")
        if not self.fields:
            raise ValueError("fields must not be empty")
        if any(not isinstance(field, str) or not field.strip() for field in self.fields):
            raise ValueError("fields must contain non-empty strings")
        if len(set(self.fields)) != len(self.fields):
            raise ValueError("fields must be unique")
        reserved = sorted(set(self.fields) & FLOW_ENVELOPE_FIELDS)
        if reserved:
            raise ValueError(f"Flow envelope fields are reserved: {reserved}")
