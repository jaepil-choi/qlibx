"""The Panel: a materialized instant x instrument table between the file and the window.

`docs/design/the-panel-the-surface-and-the-run.md` §2.3, §2.5; record `137`. Until now the data
plane had two layers, the declaration and the window, and no table between them: every read
re-cut its window on the parquet with SQL, and `docs/issues/049` measured what that costs -- the
same model, the same output, 806.61 s against 1.31 s, with `compute` at 0.36 s on both sides.
Ninety-eight percent of a rolling-window run was moving data.

A `Panel` is built **once per run** per (dataset, declared fields, instruments): one scan, the
columns pivoted into **one array per field** over one shared instant axis, immutable and
columnar. A `PanelWindow` is a **slice** of it -- two indices on the instant axis, taken by
arithmetic -- not a copy, and not a query. The read path validates nothing here for the same
reason lane A gave: there are no cells to validate.

Since record `232` (`docs/issues/096`) a field is one block, not one array per name: the array
is laid out name-major (`index = name * len(instants) + instant`), so one name's history is a
contiguous slice and the whole field is one `(instants x instruments)` matrix by a reshape. A
numeric field exposes that matrix as `numpy` (`PanelWindow.matrix()`, `NaN` where the source had
no value) and every accessor that used to walk the names in Python -- `counts`, `current`,
`latest` -- is one vectorised step over it. `values[name]` and `series` keep their shape.

Only a panel grain (`instrument_instant`, `instant`) has a panel. A `rows` grain keeps the row
stream (`rows(alias)`), because the vendor's long table has no shared instant axis to pivot on.
"""

from __future__ import annotations

import hashlib
from bisect import bisect_left, bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import datetime
from types import MappingProxyType

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

from vqapr.data.lookback import CalendarLookback, RowsLookback
from vqapr.domain.shapes import CrossSection, Series

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
    """sha256 over what decides a panel's content, so two builders of the same panel agree."""
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


@dataclass(frozen=True, slots=True)
class Panel:
    """One dataset's declared fields over a shared instant axis, one Arrow array per field.

    `columns[field]` is an Arrow array of length `len(names) * len(instants)`, name-major: the
    history of the `j`-th name is `slice(j * len(instants), len(instants))`, and a null is where
    the source had no value at that instant for that name. Built by `from_table` from the
    columns one scan returned, and never mutated: a window slices it.
    """

    dataset_id: str
    fields: tuple[str, ...]
    instruments: tuple[str, ...]
    instants: tuple[datetime, ...]
    columns: Mapping[str, pa.Array]
    identity: str
    source_digest: str
    # Per-field caches, filled on first use: the float matrix and the validity mask of a field,
    # each `(instants x names)` and contiguous. The dataclass is frozen; these are memo slots.
    _blocks: dict[str, np.ndarray] = dataclass_field(
        default_factory=dict, init=False, repr=False, compare=False
    )
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
    ) -> Panel:
        """Pivot the scan's columns -- `available_at`, `instrument`, one per field -- into blocks.

        The instant axis is every distinct `available_at` the table carries, ascending. A name
        absent at an instant is null there, never a fabricated zero. No row is walked in Python:
        each source row's place in a block is one integer, computed for every row at once.
        """
        names = tuple(instruments) if keyed_by_instrument else (NO_INSTRUMENT,)
        available = table.column("available_at").combine_chunks()
        # pyarrow's stubs omit these kernels; each exists at runtime.
        distinct = pc.unique(available)  # type: ignore[attr-defined]
        instants_array = pc.take(distinct, pc.sort_indices(distinct))  # type: ignore[attr-defined]
        instants = tuple(instants_array.to_pylist())
        count = len(instants)
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
        flat = name_index[keep] * count + at.astype(np.int64)[keep]
        size = len(names) * count
        columns: dict[str, pa.Array] = {}
        for name in fields:
            values = table.column(name).combine_chunks()
            if _is_numeric(values.type):
                # The float path: nulls are NaN in numpy and null again in Arrow; an integer
                # field is cast back so `values[name]` still hands a model integers.
                dense = np.full(size, np.nan)
                dense[flat] = pc.cast(values, pa.float64()).to_numpy(zero_copy_only=False)[keep]
                column = pa.array(dense, from_pandas=True)
                columns[name] = (
                    column if pa.types.is_floating(values.type) else column.cast(values.type)
                )
            else:
                cells = np.full(size, None, dtype=object)
                present = np.empty(len(values), dtype=object)
                present[:] = values.to_pylist()
                cells[flat] = present[keep]
                columns[name] = pa.array(cells.tolist(), type=values.type)
        return cls(
            dataset_id=str(dataset_id),
            fields=tuple(fields),
            instruments=names if keyed_by_instrument else (),
            instants=instants,
            columns=MappingProxyType(columns),
            identity=identity,
            source_digest=source_digest,
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

    def column(self, field: str, instrument: str) -> pa.Array:
        """One name's whole history of one field: a slice of the field's array, sharing buffers."""
        count = len(self.instants)
        return self.columns[field].slice(self.position(instrument) * count, count)

    def block(self, field: str) -> np.ndarray:
        """The field as an `(instants x names)` float64 matrix, `NaN` where the source had none.

        Built once per field from the Arrow array (one cast, one reshape) and kept; a window's
        `matrix()` is a view of rows of it. Only a numeric field has one: a string or a
        timestamp has no `NaN`, and a model reads those through `values`/`series`.
        """
        cached = self._blocks.get(field)
        if cached is None:
            column = self.columns[field]
            if not _is_numeric(column.type):
                raise TypeError(
                    f"field {field!r} of {self.dataset_id!r} is {column.type}, not numeric; "
                    "matrix() is for numeric fields -- read it through values[name] or series()"
                )
            flat = pc.cast(column, pa.float64()).to_numpy(zero_copy_only=False)
            cached = self._blocks[field] = np.ascontiguousarray(
                flat.reshape(len(self.names), len(self.instants)).T
            )
        return cached

    def validity(self, field: str) -> np.ndarray:
        """Where the field has a value, as an `(instants x names)` boolean matrix; any type."""
        cached = self._validity.get(field)
        if cached is None:
            flat = pc.is_valid(self.columns[field]).to_numpy(  # type: ignore[attr-defined]
                zero_copy_only=False
            )
            cached = self._validity[field] = np.ascontiguousarray(
                flat.reshape(len(self.names), len(self.instants)).T
            )
        return cached

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
        """
        if field not in self.columns:
            raise KeyError(f"panel for {self.dataset_id!r} carries no field {field!r}")
        stop = bisect_right(self.instants, evaluation_time)  # type: ignore[type-var]
        if isinstance(lookback, RowsLookback):
            start = max(stop - lookback.rows, 0)
        elif isinstance(lookback, CalendarLookback):
            start = bisect_left(self.instants, lookback.lower_bound(evaluation_time))  # type: ignore[type-var]
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

    **What an access costs.** The window is a slice of Arrow buffers and nothing is converted
    until asked. `matrix()` is a view of rows of the field's block, built once per panel.
    `counts()`, `current()` and `latest()` are one vectorised step over the field's validity
    mask and one Arrow `take` -- no Python step per name (`docs/issues/096`). `values[name]`
    converts that one column, once per window (`docs/issues/061`); iterating `values` converts
    every column, which is what asking for every column costs.
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
            # An Arrow slice shares the panel's buffers; only this window's cells are converted.
            cached = self._values[instrument] = tuple(self._column(instrument).to_pylist())
        return cached

    def _column(self, instrument: str) -> pa.Array:
        """This window's slice of one name's Arrow column; shares the panel's buffers."""
        return self.panel.column(self.field, instrument).slice(self.start, self.stop - self.start)

    @property
    def values(self) -> Mapping[str, tuple[object, ...]]:
        """Every column of the window, keyed by instrument (`""` for a panel with no axis).

        Lazy: `values[name]` converts that column and no other (`docs/issues/061`).
        """
        return _LazyColumns(self)

    def _flat(self, name_index: np.ndarray, instant_index: np.ndarray) -> pa.Array:
        """The cells at `(instant, name)` pairs, as one Arrow `take` on the field's array."""
        count = len(self.panel.instants)
        return self.panel.columns[self.field].take(pa.array(name_index * count + instant_index))

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
        cells = self._flat(present, np.full(len(present), last)).to_pylist()
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
        cells = self._flat(present, self.start + newest).to_pylist()
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


__all__ = ["NO_INSTRUMENT", "Panel", "PanelWindow", "panel_identity"]
