"""The shapes data takes between a registered table and a Component: what a value IS, by axis.

Record `183`. The framework moves data in five shapes and, until now, named one and a half of
them: the wide `Panel` (instant x instrument, Arrow-backed, `data/panel.py`) had a type, the
long `Observation` sat on the author surface, and the three shapes every judgment is spoken in
had none -- a cross-section (one instant, instrument -> value) was `dict[str, Decimal]` in
fifty-eight places, a series (one instrument, instant -> value) a bare tuple, and the account
history's own wide table a dict of tuples. The owner's point
(`docs/code-review/2026-09-08-four-readers-one-loop-and-the-missing-shapes.md` §3): the grain
decides the shape (owner ruling B, 2026-09-02), and that is a domain fact that never reached
the domain layer.

So the shapes live here, below everything, and the grain with them:

| shape | axes | grain it comes from | where it is used |
|---|---|---|---|
| `Grain` | -- | declared on the dataset | registration, panel building, lookback steering |
| `Observation` | (instant, instrument) -> values | `rows` | `call.rows(alias)` |
| `Panel` (protocol) | instant x instrument | panel grains | `call.read(alias, field)` |
| `CrossSection` | instrument -> value at one instant | a panel row; a judgment | weights, bounds |
| `Series` | instant -> value for one instrument | a panel column | a strategy's arithmetic |

`CrossSection` and `Series` are thin: a validated mapping or sequence with the operations their
consumers kept re-writing (elementwise `max`/`min` for merging bounds, `abs`, a total). Their
cells stay `Decimal` where the owner ruled exactness (the optimiser, the account); the shape
is independent of the dtype, and an Arrow-backed cross-section was measured to be not worth
having yet (`scratchpad/bench_xs.py`, issue `068`: a run spends its time moving data, not on
this arithmetic).

The row-shape helpers (`Scalar`, `Row`, `Rows`, `normalize_rows`) moved here from
`domain/values.py`, where they were a banner-folded section: a row is the long shape's unit.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Protocol, runtime_checkable

from vqapr.domain.values import require_tz_aware

# ------------------------------------------------------------------------------------------
# Grain -- what one row of a registered dataset IS. Moved from `data/datasets.py`.
# ------------------------------------------------------------------------------------------


class Grain(StrEnum):
    """What one row of the dataset IS, declared by the author and never derived.

    `docs/design/the-panel-the-surface-and-the-run.md` §2.2. The grain decides what registration
    checks for uniqueness, whether a panel can be built from the table, and -- with the lookback
    types that follow it (§2.4) -- what `RowsLookback` means on it. An `aggregated` projection is
    a *means* of reaching `instrument_instant` from a long source; it is not the grain itself, and
    a fact derived from expressions gives the author no place to state intent. `049`'s story --
    registered long, six hundred times slower, and nobody said why -- is what a declared grain
    prevents.

    It is a property of the TABLE, not of a read. "At or before the instant" and "exactly at the
    instant" are two ways of reading a table, decided by the event that reads it (`flow/loop.py`),
    and neither is a grain (owner ruling, 2026-09-08: no `Grain.POINT`).
    """

    INSTRUMENT_INSTANT = "instrument_instant"
    """One value per field per (available_at, instrument). A panel can be built."""

    INSTANT = "instant"
    """One value per available_at; no instrument axis (`docs/issues/archive/038`). A one-column panel."""

    ROWS = "rows"
    """The vendor's grain: long / EAV. Unique on the declared `key_fields`. No panel."""


# ------------------------------------------------------------------------------------------
# Rows -- the long shape's unit. Moved from `domain/values.py`.
# ------------------------------------------------------------------------------------------

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


def _identifier(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not value or any(char.isspace() for char in value):
        raise ValueError(f"{name} must be a non-empty string without whitespace")
    return value


def _copy_values(values: object, *, name: str) -> Mapping[str, object]:
    if not isinstance(values, Mapping):
        raise TypeError(f"{name} must be a mapping")
    normalized: dict[str, object] = {}
    for key, value in values.items():
        if not isinstance(key, str) or not key or any(char.isspace() for char in key):
            raise ValueError(f"{name} keys must be non-empty strings without whitespace")
        normalized[key] = normalize_scalar(value)
    return MappingProxyType(dict(sorted(normalized.items())))


# ------------------------------------------------------------------------------------------
# Observation -- one row of the long shape, as a Component receives it. Moved from `authoring`.
# ------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Observation:
    """One PIT row returned from a declared, aliased read.

    Constructing one by hand validates every field: the instrument id is a non-empty identifier,
    `available_at` is tz-aware, every value key is an identifier and every value a portable
    scalar. A row the framework itself produced is built through `_framework_row` instead and
    skips all of that -- `docs/issues/archive/054` measured the per-row re-check at 70% of a `rows` read,
    proving per value what the registration proved once (`docs/issues/035`: validation happens at
    registration, and the read path is trusted). The distinction is who built the row, not
    whether rows are checked: an author's `Observation(values={"a b": 1})` is still refused.
    """

    instrument_id: str
    available_at: datetime
    values: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "instrument_id", _identifier(self.instrument_id, name="instrument_id")
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


# ------------------------------------------------------------------------------------------
# CrossSection -- one instant, instrument -> value.
# ------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, eq=False)
class CrossSection[T](Mapping[str, T]):
    """Instrument -> value at one instant: the shape every judgment is spoken in.

    A `Mapping`, so `weights["A"]`, `"A" in weights`, `weights.items()` and `weights == {...}`
    all mean what they did when this was a dict. What it adds is a name, an optional instant
    (`at`: the instant the values are the cross-section OF -- a panel's last row knows it, a
    strategy's target does not), and the operations its consumers kept writing by hand.

    Keys are validated as instrument ids and kept sorted; the mapping is read-only. A
    cross-section built by the framework from cells it already proved goes through `_trusted`.
    """

    cells: Mapping[str, T]
    at: datetime | None = None
    _keys: tuple[str, ...] = field(default=(), init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.cells, Mapping):
            raise TypeError("cells must be a mapping of instrument id to value")
        normalized: dict[str, T] = {}
        for key, value in self.cells.items():
            normalized[_identifier(key, name="instrument id")] = value
        ordered = dict(sorted(normalized.items()))
        object.__setattr__(self, "cells", MappingProxyType(ordered))
        object.__setattr__(self, "_keys", tuple(ordered))
        if self.at is not None:
            require_tz_aware(self.at, name="at")

    @classmethod
    def _trusted(cls, cells: dict[str, T], at: datetime | None = None) -> CrossSection[T]:
        """From cells the framework built in sorted order: no re-validation, same shape."""
        section = object.__new__(cls)
        object.__setattr__(section, "cells", MappingProxyType(cells))
        object.__setattr__(section, "_keys", tuple(cells))
        object.__setattr__(section, "at", at)
        return section

    def __getitem__(self, instrument_id: str) -> T:
        return self.cells[instrument_id]

    def __iter__(self) -> Iterator[str]:
        return iter(self._keys)

    def __len__(self) -> int:
        return len(self._keys)

    def __contains__(self, instrument_id: object) -> bool:
        return instrument_id in self.cells

    @property
    def instruments(self) -> tuple[str, ...]:
        return self._keys

    def map[U](self, fn: Callable[[T], U]) -> CrossSection[U]:
        """The same names, each value passed through `fn`."""
        return CrossSection._trusted(
            {name: fn(value) for name, value in self.cells.items()}, self.at
        )

    def elementwise[U](
        self, fn: Callable[..., U], *others: Mapping[str, T]
    ) -> CrossSection[U]:
        """`fn` applied name by name across this and `others`, which must cover the same names.

        What `merged_constraint_bounds` does with `max` and `min`: a projection that misses a name
        is refused rather than defaulted, because a missing bound would silently widen the box.
        """
        for other in others:
            if set(other) != set(self._keys):
                raise ValueError(
                    "elementwise operands must cover the same instruments: "
                    f"{sorted(set(other) ^ set(self._keys))!r} differ"
                )
        return CrossSection._trusted(
            {
                name: fn(self.cells[name], *(other[name] for other in others))
                for name in self._keys
            },
            self.at,
        )

    def total(self, zero: T) -> T:
        """The sum of every value, starting from `zero` so the type is the caller's."""
        return sum(self.cells.values(), zero)  # type: ignore[arg-type]

    def where(self, predicate: Callable[[T], bool]) -> tuple[str, ...]:
        """The names whose value satisfies `predicate`, in id order: what a rule blames."""
        return tuple(name for name in self._keys if predicate(self.cells[name]))


# ------------------------------------------------------------------------------------------
# Series -- one instrument, instant -> value.
# ------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Series[T]:
    """Instant -> value for one instrument: a panel's column over a window, oldest first.

    `cells` is a tuple aligned with `instants`; `None` where the name had no value at that
    instant, never a fabricated zero. `latest()` is the newest non-null value, or `None`.
    """

    instrument: str
    instants: tuple[datetime, ...]
    cells: tuple[T | None, ...]

    def __post_init__(self) -> None:
        if len(self.instants) != len(self.cells):
            raise ValueError("a series has one cell per instant")

    def __len__(self) -> int:
        return len(self.cells)

    def __iter__(self) -> Iterator[T | None]:
        return iter(self.cells)

    def __getitem__(self, index: int) -> T | None:
        return self.cells[index]

    def latest(self) -> T | None:
        for value in reversed(self.cells):
            if value is not None:
                return value
        return None

    def present(self) -> tuple[T, ...]:
        """The non-null values, oldest first: what a lookback arithmetic reads."""
        return tuple(value for value in self.cells if value is not None)


# ------------------------------------------------------------------------------------------
# Panel -- instant x instrument. The Arrow-backed implementation is `data/panel.py`.
# ------------------------------------------------------------------------------------------


@runtime_checkable
class Panel(Protocol):
    """The wide shape a panel-grain read returns: instants x instruments, one field.

    `data.panel.PanelWindow` is the implementation; this is what a Component is promised.
    """

    @property
    def instants(self) -> tuple[datetime, ...]: ...

    @property
    def instruments(self) -> tuple[str, ...]: ...

    def current(self) -> CrossSection[object]: ...

    def latest(self) -> CrossSection[object]: ...

    def series(self, instrument: str = ...) -> Series[object]: ...


__all__ = [
    "CrossSection",
    "Grain",
    "Observation",
    "Panel",
    "Row",
    "Rows",
    "Scalar",
    "Series",
    "normalize_rows",
    "normalize_scalar",
]
