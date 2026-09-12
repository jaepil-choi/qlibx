"""The Panel: a materialized instant x instrument table between the file and the window.

`docs/design/the-panel-the-surface-and-the-run.md` §2.3, §2.5; record `137`. Until now the data
plane had two layers, the declaration and the window, and no table between them: every read
re-cut its window on the parquet with SQL, and `docs/issues/049` measured what that costs -- the
same model, the same output, 806.61 s against 1.31 s, with `compute` at 0.36 s on both sides.
Ninety-eight percent of a rolling-window run was moving data.

A `Panel` is built **once per run** per (dataset, declared fields, instruments): one scan, the
columns pivoted into **one block per field** over one shared instant axis, immutable and
columnar. A `PanelWindow` is a **slice** of it -- two indices on the instant axis, taken by
arithmetic -- not a copy, and not a query. The read path validates nothing here for the same
reason lane A gave: there are no cells to validate.

Since record `232` (`docs/issues/096`) a field is one block, not one array per name, and every
accessor that used to walk the names in Python -- `counts`, `current`, `latest` -- is one
vectorised step over it. Since record `235` (`docs/issues/098`) a **numeric** field is held
exactly once: an `(instants x instruments)` float64 matrix, `NaN` where the source had no value,
which `PanelWindow.matrix()` hands a model as a view of its rows. The Arrow copy that used to sit
beside it, and the validity bitmap beside that, are gone; `values[name]` and `series` convert one
column when asked and hand `None` where the source had none, an `int` for an INTEGER field. A
non-numeric field (a string, a date) has no `NaN` and stays an Arrow array, name-major.

A panel also knows the **bounds** it was scanned over. Since record `235` the store scans the
run's horizon rather than the registered span, so a window asked for an instant the panel never
read is refused, never silently truncated.

Only a panel grain (`instrument_instant`, `instant`) has a panel. A `rows` grain keeps the row
stream (`rows(alias)`), because the vendor's long table has no shared instant axis to pivot on.

A panel's row at one instant is a `CrossSection` (instrument -> value) and its column for one
instrument is a `Series` (instant -> value); both live here beside the panel they slice.
"""

from __future__ import annotations

import hashlib
from bisect import bisect_left, bisect_right
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from dataclasses import field as dataclass_field
from datetime import datetime
from types import MappingProxyType

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

from vqapr.data.lookback import CalendarLookback, RowsLookback
from vqapr.domain.identifiers import require_identifier
from vqapr.domain.instants import require_tz_aware

__all__ = [
    "NO_INSTRUMENT",
    "CrossSection",
    "Panel",
    "PanelWindow",
    "Series",
    "panel_identity",
]


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
            normalized[require_identifier(key, name="instrument id")] = value
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

        What `vqapr.portfolio.bounds.intersect` does with `max` and `min`: a box that misses a
        name is refused rather than defaulted, because a missing bound would silently widen it.
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


NO_INSTRUMENT = ""
"""The one column key of a panel built from a dataset with no instrument axis (`grain: instant`).

There is no name to file its values under (`docs/issues/038`), so the panel carries exactly one
column and this is its key. `PanelWindow.latest()` on such a panel is a one-entry mapping.
"""


def panel_identity(
    source_digest: str,
    dataset_id: str,
    fields: Sequence[str],
    instruments: Sequence[str],
    span: tuple[datetime, datetime] | None,
) -> str:
    """sha256 over what decides a panel's content, so two builders of the same panel agree.

    `span` is the bounds the panel was scanned over: the run's horizon since record `235`, the
    registered span before it. Two panels over different bounds hold different rows.
    """
    digest = hashlib.sha256()
    digest.update(source_digest.encode("utf-8"))
    digest.update(b"\x00" + dataset_id.encode("utf-8"))
    for name in fields:
        digest.update(b"\x00" + name.encode("utf-8"))
    digest.update(b"\x01")
    for name in instruments:
        digest.update(b"\x00" + name.encode("utf-8"))
    if span is not None:
        digest.update(b"\x02" + span[0].isoformat().encode())
        digest.update(b"\x00" + span[1].isoformat().encode())
    return digest.hexdigest()


def _is_numeric(kind: pa.DataType) -> bool:
    """The types a field can hand a model as a float matrix: integers and floats."""
    return pa.types.is_floating(kind) or pa.types.is_integer(kind)


def placement(
    table: pa.Table, names: Sequence[str], keyed_by_instrument: bool
) -> tuple[tuple[datetime, ...], np.ndarray, np.ndarray, np.ndarray]:
    """Where each row of a scan lands in an `(instants x names)` block.

    The instant axis is every distinct `available_at` the table carries, ascending. Returns it
    with three arrays: `keep`, true for the rows whose instrument is one of `names`; and for
    those rows, their instant index and their name index. No row is walked in Python. Shared by
    `Panel.from_table` and the cube bake (record `236`), so the two lay a field out identically.
    """
    available = table.column("available_at").combine_chunks()
    # pyarrow's stubs omit these kernels; each exists at runtime.
    distinct = pc.unique(available)  # type: ignore[attr-defined]
    instants_array = pc.take(distinct, pc.sort_indices(distinct))  # type: ignore[attr-defined]
    instants = tuple(instants_array.to_pylist())
    at = pc.index_in(available, value_set=instants_array).to_numpy(  # type: ignore[attr-defined]
        zero_copy_only=False
    )
    if keyed_by_instrument:
        instrument = table.column("instrument").combine_chunks()
        value_set = pa.array(names).cast(instrument.type)
        placed = pc.fill_null(pc.index_in(instrument, value_set=value_set), -1)  # type: ignore[attr-defined]
        name_index = placed.to_numpy(zero_copy_only=False).astype(np.int64)
    else:
        name_index = np.zeros(len(table), dtype=np.int64)
    keep = name_index >= 0
    return instants, keep, at.astype(np.int64)[keep], name_index[keep]


def dense_block(
    values: pa.Array,
    count: int,
    width: int,
    keep: np.ndarray,
    rows: np.ndarray,
    cols: np.ndarray,
) -> np.ndarray:
    """One numeric field as an `(count x width)` float64 matrix, `NaN` where no row landed."""
    dense = np.full((count, width), np.nan)
    dense[rows, cols] = pc.cast(values, pa.float64()).to_numpy(zero_copy_only=False)[keep]
    return dense


@dataclass(frozen=True, slots=True)
class Panel:
    """One dataset's declared fields over a shared instant axis, one block per field.

    `blocks[field]` is an `(instants x names)` float64 matrix for a numeric field, `NaN` where the
    source had no value at that instant for that name; `kinds[field]` is the Arrow type the field
    was declared as, so an INTEGER field's cells come back as `int`. `columns[field]` is the
    name-major Arrow array of a non-numeric field: the history of the `j`-th name is
    `slice(j * len(instants), len(instants))`, null where absent. Built by `from_table` from the
    columns one scan returned, and never mutated: a window slices it.

    `bounds` is the pair of instants the panel was scanned between, or `None` for a panel built
    over everything the registration holds.
    """

    dataset_id: str
    fields: tuple[str, ...]
    instruments: tuple[str, ...]
    instants: tuple[datetime, ...]
    blocks: Mapping[str, np.ndarray]
    kinds: Mapping[str, pa.DataType]
    columns: Mapping[str, pa.Array]
    identity: str
    source_digest: str
    bounds: tuple[datetime, datetime] | None = None
    # Per-field caches, filled on first use: the validity mask of a field, `(instants x names)`
    # and contiguous. The dataclass is frozen; these are memo slots.
    _validity: dict[str, np.ndarray] = dataclass_field(
        default_factory=dict, init=False, repr=False, compare=False
    )
    _positions: dict[str, int] = dataclass_field(
        default_factory=dict, init=False, repr=False, compare=False
    )

    @classmethod
    def from_table(
        cls,
        table: pa.Table,
        *,
        dataset_id: str,
        fields: Sequence[str],
        instruments: Sequence[str],
        keyed_by_instrument: bool,
        identity: str,
        source_digest: str,
        bounds: tuple[datetime, datetime] | None = None,
    ) -> Panel:
        """Pivot the scan's columns -- `available_at`, `instrument`, one per field -- into blocks.

        The instant axis is every distinct `available_at` the table carries, ascending. A name
        absent at an instant is `NaN` (null, for a non-numeric field) there, never a fabricated
        zero. No row is walked in Python: each source row's place in a block is one pair of
        integers, computed for every row at once.
        """
        names = tuple(instruments) if keyed_by_instrument else (NO_INSTRUMENT,)
        instants, keep, rows, cols = placement(table, names, keyed_by_instrument)
        count = len(instants)
        blocks: dict[str, np.ndarray] = {}
        kinds: dict[str, pa.DataType] = {}
        columns: dict[str, pa.Array] = {}
        for name in fields:
            values = table.column(name).combine_chunks()
            if _is_numeric(values.type):
                # The float path: one matrix, nulls as NaN. An integer field rides in it and is
                # cast back when a cell is handed to a model, so `values[name]` still hands ints.
                blocks[name] = dense_block(values, count, len(names), keep, rows, cols)
                kinds[name] = values.type
            else:
                cells = np.full(len(names) * count, None, dtype=object)
                present = np.empty(len(values), dtype=object)
                present[:] = values.to_pylist()
                cells[cols * count + rows] = present[keep]
                columns[name] = pa.array(cells.tolist(), type=values.type)
        return cls(
            dataset_id=str(dataset_id),
            fields=tuple(fields),
            instruments=names if keyed_by_instrument else (),
            instants=instants,
            blocks=MappingProxyType(blocks),
            kinds=MappingProxyType(kinds),
            columns=MappingProxyType(columns),
            identity=identity,
            source_digest=source_digest,
            bounds=bounds,
        )

    @property
    def names(self) -> tuple[str, ...]:
        """The column keys: the instruments, or the one key of a panel with no instrument axis."""
        return self.instruments or (NO_INSTRUMENT,)

    def position(self, instrument: str) -> int:
        """Where a name sits on the name axis; `KeyError` naming the panel's names otherwise."""
        if not self._positions:
            self._positions.update({name: index for index, name in enumerate(self.names)})
        try:
            return self._positions[instrument]
        except KeyError:
            raise KeyError(
                f"{instrument!r} is not an instrument of this panel; it holds "
                f"{', '.join(self.instruments) or 'no instrument axis'}"
            ) from None

    def _require_field(self, field: str) -> None:
        if field not in self.blocks and field not in self.columns:
            raise KeyError(f"panel for {self.dataset_id!r} carries no field {field!r}")

    def column(self, field: str, instrument: str) -> pa.Array:
        """One name's whole history of one field, as an Arrow array; null where absent.

        A non-numeric field's column is a slice of its array and shares the panel's buffers. A
        numeric field's column is that name's column of the block, converted once: this is the
        per-name door (`values[name]`, `series`), not the matrix.
        """
        self._require_field(field)
        count = len(self.instants)
        block = self.blocks.get(field)
        if block is None:
            return self.columns[field].slice(self.position(instrument) * count, count)
        history = np.ascontiguousarray(block[:, self.position(instrument)])
        cells = pa.array(history, from_pandas=True)
        kind = self.kinds[field]
        return cells if pa.types.is_floating(kind) else cells.cast(kind)

    def block(self, field: str) -> np.ndarray:
        """The field as an `(instants x names)` float64 matrix, `NaN` where the source had none.

        Held once per panel; a window's `matrix()` is a view of rows of it. Only a numeric field
        has one: a string or a timestamp has no `NaN`, and a model reads those through
        `values`/`series`.
        """
        self._require_field(field)
        block = self.blocks.get(field)
        if block is None:
            raise TypeError(
                f"field {field!r} of {self.dataset_id!r} is {self.columns[field].type}, not "
                "numeric; matrix() is for numeric fields -- read it through values[name] or "
                "series()"
            )
        return block

    def validity(self, field: str) -> np.ndarray:
        """Where the field has a value, as an `(instants x names)` boolean matrix; any type."""
        cached = self._validity.get(field)
        if cached is None:
            self._require_field(field)
            block = self.blocks.get(field)
            if block is not None:
                cached = ~np.isnan(block)
            else:
                flat = pc.is_valid(self.columns[field]).to_numpy(  # type: ignore[attr-defined]
                    zero_copy_only=False
                )
                cached = np.ascontiguousarray(flat.reshape(len(self.names), len(self.instants)).T)
            self._validity[field] = cached
        return cached

    def cells_at(self, field: str, instant_index: np.ndarray, name_index: np.ndarray) -> list:
        """The cells at `(instant, name)` pairs, as Python values: one gather, no step per name."""
        block = self.blocks.get(field)
        if block is None:
            count = len(self.instants)
            flat = self.columns[field].take(pa.array(name_index * count + instant_index))
            return flat.to_pylist()
        picked = block[instant_index, name_index].tolist()
        if pa.types.is_integer(self.kinds[field]):
            return [int(cell) for cell in picked]
        return picked

    def window(
        self,
        field: str,
        *,
        evaluation_time: datetime,
        lookback: RowsLookback | CalendarLookback,
    ) -> PanelWindow:
        """The slice one requirement admits: at or before the cutoff, back by the lookback.

        Two indices on the instant axis. `RowsLookback(n)` is the last n instants at or before
        the cutoff -- the same n for every name -- and `CalendarLookback` is every instant from its
        calendar bound. A `rows` window larger than the table is the whole table up to the cutoff.

        A panel scanned over bounds refuses a cutoff past its upper bound, and a calendar bound
        below its lower one: the rows are not there, and a window that quietly held fewer instants
        than the lookback named would be a look-behind hole nothing downstream could see.
        """
        self._require_field(field)
        if self.bounds is not None and evaluation_time > self.bounds[1]:
            raise RuntimeError(
                f"panel for {self.dataset_id!r} was scanned up to {self.bounds[1].isoformat()} "
                f"and cannot serve a window at {evaluation_time.isoformat()}"
            )
        stop = bisect_right(self.instants, evaluation_time)  # type: ignore[type-var]
        if isinstance(lookback, RowsLookback):
            start = max(stop - lookback.rows, 0)
        elif isinstance(lookback, CalendarLookback):
            lower = lookback.lower_bound(evaluation_time)
            if self.bounds is not None and lower < self.bounds[0]:
                raise RuntimeError(
                    f"panel for {self.dataset_id!r} was scanned from "
                    f"{self.bounds[0].isoformat()} and cannot serve a window from "
                    f"{lower.isoformat()}"
                )
            start = bisect_left(self.instants, lower)  # type: ignore[type-var]
            start = min(start, stop)
        else:
            raise TypeError("a panel window takes a RowsLookback or a CalendarLookback")
        return PanelWindow(
            panel=self, field=field, start=start, stop=stop, evaluation_time=evaluation_time
        )


@dataclass(frozen=True, slots=True)
class PanelWindow:
    """What a Model receives for one field of a panel-grain alias: a 2d slice, not a copy.

    `instants` is the window's instant axis, common to every name; `instruments` its columns;
    `matrix()` the window as an `(instants x instruments)` float matrix, the shape a
    cross-sectional decision computes on; `values[name]` that name's values over `instants`
    (`None` where absent); `current()` the cross-section at the window's last instant, a name
    absent when it has no row there; `latest()` the newest non-null value per name anywhere in
    the window.

    **What an access costs.** `matrix()` is a view of rows of the field's block, the one copy
    the panel holds. `counts()`, `current()` and `latest()` are one vectorised step over the
    field's validity mask and one gather -- no Python step per name (`docs/issues/096`).
    `values[name]` converts that one column, once per window (`docs/issues/061`); iterating
    `values` converts every column, which is what asking for every column costs.
    """

    panel: Panel
    field: str
    start: int
    stop: int
    evaluation_time: datetime
    # The window's own `field` attribute above owns that name; the dataclasses helper is aliased.
    _values: dict[str, tuple[object, ...]] = dataclass_field(
        default_factory=dict, init=False, repr=False
    )

    @property
    def instants(self) -> tuple[datetime, ...]:
        return self.panel.instants[self.start : self.stop]

    @property
    def instruments(self) -> tuple[str, ...]:
        return self.panel.instruments

    def __len__(self) -> int:
        return self.stop - self.start

    def matrix(self) -> np.ndarray:
        """The window as `(instants x instruments)` float64, `NaN` where a name had no value.

        A view of the panel's block: no copy, no conversion per name. Row `-1` is the newest
        instant; column `j` is `instruments[j]`. A cross-sectional decision -- a return over the
        window, a rank across names -- is one numpy expression on it, which is what makes 3,000
        names cost the same as ten (`docs/issues/096`). Numeric fields only; `TypeError` names
        the field otherwise.
        """
        return self.panel.block(self.field)[self.start : self.stop]

    def series(self, instrument: str = NO_INSTRUMENT) -> Series[object]:
        """One name's values over the window's instants as a `Series`, `None` where it had none."""
        return Series(instrument, self.instants, self._cells(instrument))

    def _cells(self, instrument: str) -> tuple[object, ...]:
        """One name's cells over the window, converted once per window (`docs/issues/061`)."""
        cached = self._values.get(instrument)
        if cached is None:
            cached = self._values[instrument] = tuple(self._column(instrument).to_pylist())
        return cached

    def _column(self, instrument: str) -> pa.Array:
        """This window's slice of one name's column."""
        return self.panel.column(self.field, instrument).slice(self.start, self.stop - self.start)

    @property
    def values(self) -> Mapping[str, tuple[object, ...]]:
        """Every column of the window, keyed by instrument (`""` for a panel with no axis).

        Lazy: `values[name]` converts that column and no other (`docs/issues/061`).
        """
        return _LazyColumns(self)

    def current(self) -> CrossSection[object]:
        """The cross-section at the window's last instant: one value per name that has a row there.

        A name with no row -- or a null -- at `max_available_at` is absent, never carried forward.
        This is the accessor a decision wants on a sparse panel, where "no row today" means the
        name is not in today's universe: a monthly-rebalanced residual table had rows for a name
        only on sessions it was eligible, and reading it with `latest()` traded ineligible names
        on loadings up to a week stale for about 1% of name-days (`docs/issues/072`). Nothing
        inside the package can see that mistake, because every value involved was legitimately
        available; only the accessor's meaning was wrong for the question asked.
        """
        if self.stop <= self.start:
            return CrossSection._trusted({})
        last = self.stop - 1
        present = np.flatnonzero(self.panel.validity(self.field)[last])
        names = self.panel.names
        cells = self.panel.cells_at(self.field, np.full(len(present), last), present)
        # The panel's names are sorted at build time, so `found` is already in id order.
        found = {names[index]: cell for index, cell in zip(present.tolist(), cells, strict=True)}
        return CrossSection._trusted(found, self.panel.instants[last])

    def latest(self) -> CrossSection[object]:
        """The newest non-null value per name ANYWHERE in the window; a name with none is absent.

        A time-series read: the last value each name carried, however old. On a sparse panel this
        is not the cross-section at the evaluation instant -- a name whose newest value is a week
        old returns it without a word, and the mapping does not say which values are current.
        `current()` answers that question (`docs/issues/072`).
        """
        if self.stop <= self.start:
            return CrossSection._trusted({})
        valid = self.panel.validity(self.field)[self.start : self.stop]
        present = np.flatnonzero(valid.any(axis=0))
        # The newest valid row per present name: the first hit scanning from the bottom.
        newest = (len(valid) - 1) - np.argmax(valid[::-1][:, present], axis=0)
        cells = self.panel.cells_at(self.field, self.start + newest, present)
        names = self.panel.names
        found = {names[index]: cell for index, cell in zip(present.tolist(), cells, strict=True)}
        # No single instant: each name's newest value may sit on a different row.
        return CrossSection._trusted(found)

    def counts(self) -> dict[str, int]:
        """Non-null values per name inside the window: the access record's `actual_rows`."""
        valid = self.panel.validity(self.field)[self.start : self.stop]
        totals = valid.sum(axis=0, dtype=np.int64).tolist()
        return dict(zip(self.panel.names, totals, strict=True))

    @property
    def max_available_at(self) -> datetime | None:
        return self.panel.instants[self.stop - 1] if self.stop > self.start else None

    @property
    def lower_bound(self) -> datetime | None:
        return self.panel.instants[self.start] if self.stop > self.start else None


class _LazyColumns(Mapping[str, tuple[object, ...]]):
    """`PanelWindow.values`: a read-only mapping that converts a column when it is asked for.

    A `Mapping` rather than a dict so that `values[name]` is one column and `values == {...}`,
    `len(values)`, `for name in values` still mean what they did. Building every column up
    front was `docs/issues/061`.
    """

    __slots__ = ("_window",)

    def __init__(self, window: PanelWindow) -> None:
        self._window = window

    def _keys(self) -> tuple[str, ...]:
        return self._window.panel.names

    def __getitem__(self, instrument: str) -> tuple[object, ...]:
        return self._window._cells(instrument)

    def __iter__(self):
        return iter(self._keys())

    def __len__(self) -> int:
        return len(self._keys())

    def __contains__(self, instrument: object) -> bool:
        return instrument in self._keys()

    def __repr__(self) -> str:
        return f"PanelWindow.values({', '.join(self._keys())})"
