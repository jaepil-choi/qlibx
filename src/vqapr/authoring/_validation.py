"""Shared validation for every authored value: implementation detail, not public algebra.

Each of the four Components hands the engine values it constructed, and every one of those is
refused rather than coerced when it is the wrong shape (owner ruling 2026-09-08). The checks are
the same across the roles -- a finite `Decimal`, a tz-aware instant, a non-empty identifier, a
read-only copy of a mapping -- so they are written once here and imported by the modules that
declare the values.

Nothing in this module is exported by `vqapr.authoring`. It is named with a leading underscore for
that reason: a reader looking for the contract will not find it here, and a caller outside the
package has no reason to.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from types import MappingProxyType

from pydantic import ConfigDict

from vqapr.domain.shapes import CrossSection
from vqapr.domain.values import require_tz_aware

_ROW_RESERVED_FIELDS = frozenset({"available_at", "instrument"})
"""Reserved because `ModelWindow`/`Observation` rows already carry them as named fields."""


_ENVELOPE_RESERVED_FIELDS = frozenset(
    {
        "observed_at",
        "producer",
        "stage",
        "event_time",
        "sequence",
        "source_refs",
        "source_references",
        "lineage",
        "account_version",
        "version",
        "state_ref",
        "state_reference",
        "compliance_id",
        "correlation_id",
    }
)
"""Reserved because the framework stamps these identity/provenance facts itself."""


def _finite_decimal(value: object, *, name: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must be a Decimal")
    if not value.is_finite():
        raise ValueError(f"{name} must be finite")
    return value


def _tz_aware(value: object, *, name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{name} must be a datetime")
    return require_tz_aware(value, name=name)


_WHITESPACE = re.compile(r"\s")


def _identifier(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not value or _WHITESPACE.search(value):
        raise ValueError(f"{name} must be a non-empty string without whitespace")
    return value


def _unique_identifiers(values: object, *, name: str) -> tuple[str, ...]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes, bytearray)):
        raise TypeError(f"{name} must be a sequence of strings")
    normalized = tuple(_identifier(value, name=f"{name} entry") for value in values)
    if not normalized:
        raise ValueError(f"{name} must contain at least one entry")
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{name} entries must be unique")
    return normalized


def _reject_reserved(names: Sequence[str], reserved: frozenset[str], *, name: str) -> None:
    collided = sorted(set(names) & reserved)
    if collided:
        raise ValueError(f"{name} must not use framework-reserved names: {collided}")


def _scalar(value: object, *, name: str) -> object:
    """Validate one portable value: finite float/Decimal, tz-aware datetime, else as-is."""
    if value is None or isinstance(value, (bool, str, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{name} float values must be finite")
        return value
    if isinstance(value, Decimal):
        return _finite_decimal(value, name=name)
    if isinstance(value, datetime):
        return _tz_aware(value, name=name)
    if isinstance(value, date):
        return value
    raise TypeError(f"{name} values must be portable scalars; got {type(value).__name__}")


def _copy_values(
    values: object, *, name: str, reserved: frozenset[str] = frozenset()
) -> Mapping[str, object]:
    if not isinstance(values, Mapping):
        raise TypeError(f"{name} must be a mapping")
    normalized: dict[str, object] = {}
    for key, value in values.items():
        if not isinstance(key, str) or not key or any(char.isspace() for char in key):
            raise ValueError(f"{name} keys must be non-empty strings without whitespace")
        normalized[key] = _scalar(value, name=f"{name}[{key!r}]")
    if reserved:
        _reject_reserved(tuple(normalized), reserved, name=name)
    return MappingProxyType(dict(sorted(normalized.items())))


def _copy_weights(values: object, *, name: str) -> CrossSection[Decimal]:
    """A validated, read-only cross-section of `Decimal` per instrument (record `183`).

    Every weight-shaped value on this surface -- a target, a bound, a position, a marked value
    -- is one instant's instrument -> value, and that shape has a name now. It is still a
    `Mapping`, so an author's `weights["A"]` and `weights.items()` are unchanged.
    """
    if not isinstance(values, Mapping):
        raise TypeError(f"{name} must be a mapping")
    normalized: dict[str, Decimal] = {}
    for key, value in values.items():
        instrument_id = _identifier(key, name=f"{name} key")
        normalized[instrument_id] = _finite_decimal(value, name=f"{name}[{instrument_id!r}]")
    return CrossSection._trusted(dict(sorted(normalized.items())))


# The one configuration every authored value shares. Strict, so an `int` where a `Decimal` was
# declared is refused rather than widened; `arbitrary_types_allowed` because a weight-shaped
# field is stored as the `CrossSection` `_copy_weights` builds, which is the package's own type.
_VALUE_CONFIG = ConfigDict(extra="forbid", frozen=True, strict=True, arbitrary_types_allowed=True)
