"""Portable row values shared by Model input, output, and publication."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal

from vqapr.domain.timestamps import require_tz_aware

type Scalar = bool | int | float | Decimal | str | date | datetime | None
type Row = dict[str, Scalar]
type Rows = tuple[Row, ...]


def normalize_scalar(value: object) -> Scalar:
    """Validate one portable scalar without silently stringifying unknown objects."""
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("row float values must be finite")
        return value
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("row decimal values must be finite")
        return value
    if isinstance(value, datetime):
        return require_tz_aware(value, name="row datetime")
    if isinstance(value, date):
        return value
    raise TypeError(f"row values must be portable scalars; got {type(value).__name__}")


def normalize_rows(value: object) -> Rows:
    """Return detached rows after strict key and scalar validation."""
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise TypeError("rows must be a sequence of mappings")
    normalized: list[Row] = []
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise TypeError(f"row {index} must be a mapping")
        row: Row = {}
        for key, scalar in item.items():
            if not isinstance(key, str) or not key or any(char.isspace() for char in key):
                raise ValueError(f"row {index} field names must be non-empty without whitespace")
            row[key] = normalize_scalar(scalar)
        normalized.append(row)
    return tuple(normalized)
