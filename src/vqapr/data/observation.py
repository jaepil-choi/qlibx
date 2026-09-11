"""One point-in-time row read from a long (`grain: rows`) dataset.

A read of a panel-grain alias returns a panel window; a read of a rows-grain alias returns
`Observation`s -- the instrument, the instant it became available, and the row's values as
portable scalars. Constructing one by hand validates every field.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType

from vqapr.domain.identifiers import require_identifier
from vqapr.domain.instants import require_tz_aware
from vqapr.domain.rows import normalize_scalar

__all__ = [
    "Observation",
]


def _copy_values(values: object, *, name: str) -> Mapping[str, object]:
    if not isinstance(values, Mapping):
        raise TypeError(f"{name} must be a mapping")
    normalized: dict[str, object] = {}
    for key, value in values.items():
        if not isinstance(key, str) or not key or any(char.isspace() for char in key):
            raise ValueError(f"{name} keys must be non-empty strings without whitespace")
        normalized[key] = normalize_scalar(value)
    return MappingProxyType(dict(sorted(normalized.items())))


@dataclass(frozen=True, slots=True)
class Observation:
    """One PIT row returned from a declared, aliased read.

    Constructing one by hand validates every field: the instrument id is a non-empty identifier,
    `available_at` is tz-aware, every value key is an identifier and every value a portable scalar.
    A row the framework itself produced is built through `_framework_row` instead and skips all of
    that -- `docs/issues/archive/054` measured the per-row re-check at 70% of a `rows` read, proving
    per value what the registration proved once (`docs/issues/035`: validation happens at
    registration, and the read path is trusted). The distinction is who built the row, not whether
    rows are checked: an author's `Observation(values={"a b": 1})` is still refused.
    """

    instrument_id: str
    available_at: datetime
    values: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "instrument_id", require_identifier(self.instrument_id, name="instrument_id")
        )
        if not isinstance(self.available_at, datetime):
            raise TypeError("available_at must be a datetime")
        object.__setattr__(
            self, "available_at", require_tz_aware(self.available_at, name="available_at")
        )
        object.__setattr__(self, "values", _copy_values(self.values, name="values"))

    @classmethod
    def _framework_row(
        cls, instrument_id: str, available_at: datetime, values: dict[str, object]
    ) -> Observation:
        """An observation from a row the scan returned: no validation, same immutable shape.

        The field names are the alias's declared `fields`, validated when the `DatasetInput` was
        declared; `available_at` comes from the scan's own `TIMESTAMPTZ` column, which cannot
        hold a naive value; the values are what the parquet column holds, which `normalize_scalar`
        would pass through unchanged. `values` is wrapped, not copied: the caller built that dict
        for this row and hands it over.
        """
        observation = object.__new__(cls)
        object.__setattr__(observation, "instrument_id", instrument_id)
        object.__setattr__(observation, "available_at", available_at)
        object.__setattr__(observation, "values", MappingProxyType(values))
        return observation
