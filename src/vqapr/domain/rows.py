"""Portable rows: the scalar values a DataModel returns and a record stores.

A row is a mapping of field name to a portable scalar -- bool, int, float, Decimal, str, date or a
timezone-aware datetime. Values are validated where they cross into the framework and never
silently stringified; a column is checked by type rather than cell by cell.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal

from vqapr.domain.instants import require_tz_aware

__all__ = [
    "Row",
    "Rows",
    "Scalar",
    "normalize_column",
    "normalize_rows",
    "normalize_scalar",
]


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


_NONE = type(None)


def normalize_column(values: object, *, name: str = "column") -> tuple[Scalar, ...]:
    """One column of portable scalars, checked by type rather than by cell.

    The rule is `normalize_scalar`'s; the pass is different. A column of 3,000 marked prices is
    3,000 `Decimal`s, and asking each cell what it is cost as much as the arithmetic that
    produced it (record `221`). The distinct types are found in one pass that stays in C, and
    only the kinds that carry a per-value rule -- a float or a `Decimal` must be finite, a
    datetime must be aware -- are visited again, and only their own cells.
    """
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes, bytearray)):
        raise TypeError(f"{name} must be a sequence of scalars")
    column = tuple(values)
    for kind in {type(value) for value in column}:
        if kind is _NONE or issubclass(kind, (bool, str, int)):
            continue
        if issubclass(kind, float):
            if not all(math.isfinite(value) for value in column if isinstance(value, float)):
                raise ValueError(f"{name} float values must be finite")
        elif issubclass(kind, Decimal):
            if not all(value.is_finite() for value in column if isinstance(value, Decimal)):
                raise ValueError(f"{name} decimal values must be finite")
        elif issubclass(kind, datetime):
            for value in column:
                if isinstance(value, datetime):
                    require_tz_aware(value, name=f"{name} datetime")
        elif issubclass(kind, date):
            continue
        else:
            raise TypeError(f"{name} values must be portable scalars; got {kind.__name__}")
    return column
