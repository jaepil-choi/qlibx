"""The Panel: a materialized instant x instrument table between the file and the window.

`docs/design/the-panel-the-surface-and-the-run.md` §2.3, §2.5; record `137`. Until now the data
plane had two layers, the declaration and the window, and no table between them: every read
re-cut its window on the parquet with SQL, and `docs/issues/049` measured what that costs -- the
same model, the same output, 806.61 s against 1.31 s, with `compute` at 0.36 s on both sides.
Ninety-eight percent of a rolling-window run was moving data.

A `Panel` is built **once per run** per (dataset, declared fields, instruments): one scan, the
rows pivoted into one column per (field, instrument) over one shared instant axis, immutable and
columnar (Arrow arrays). A `PanelWindow` is a **slice** of it -- two indices on the instant axis,
taken by arithmetic -- not a copy, and not a query. The read path validates nothing here for the
same reason lane A gave: there are no cells to validate.

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


@dataclass(frozen=True, slots=True)
class Panel:
    """One dataset's declared fields over a shared instant axis, one Arrow column per name.

    `columns[field][instrument]` is an Arrow array of length `len(instants)`; a null where the
    source had no value at that instant for that name. Built by `from_rows` from the rows one
    scan returned, and never mutated: a window slices it.
    """

    dataset_id: str
    fields: tuple[str, ...]
    instruments: tuple[str, ...]
    instants: tuple[datetime, ...]
    columns: Mapping[str, Mapping[str, pa.Array]]
    identity: str
    source_digest: str

    @classmethod
    def from_rows(
        cls,
        rows: Sequence[Mapping[str, object]],
        *,
        dataset_id: str,
        fields: Sequence[str],
        instruments: Sequence[str],
        keyed_by_instrument: bool,
        identity: str,
        source_digest: str,
    ) -> Panel:
        """Pivot scan rows -- `available_at`, `instrument`, one value per field -- into columns.

        The instant axis is every distinct `available_at` the rows carry, ascending. A name absent
        at an instant is null there, never a fabricated zero.
        """
        names = tuple(instruments) if keyed_by_instrument else (NO_INSTRUMENT,)
        instants = tuple(sorted({row["available_at"] for row in rows}))  # type: ignore[type-var]
        position = {instant: index for index, instant in enumerate(instants)}
        cells: dict[str, dict[str, list[object]]] = {
            name: {instrument: [None] * len(instants) for instrument in names} for name in fields
        }
        for row in rows:
            index = position[row["available_at"]]
            instrument = str(row["instrument"]) if keyed_by_instrument else NO_INSTRUMENT
            per_field = cells
            for name in fields:
                column = per_field[name].get(instrument)
                if column is not None:
                    column[index] = row[name]
        columns = {
            name: MappingProxyType(
                {instrument: pa.array(values) for instrument, values in per_name.items()}
            )
            for name, per_name in cells.items()
        }
        return cls(
            dataset_id=str(dataset_id),
            fields=tuple(fields),
            instruments=names if keyed_by_instrument else (),
            instants=instants,
            columns=MappingProxyType(columns),
            identity=identity,
            source_digest=source_digest,
        )

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
    `values[name]` that name's values over `instants` (`None` where absent); `current()` the
    cross-section at the window's last instant, a name absent when it has no row there;
    `latest()` the newest non-null value per name anywhere in the window.

    **What an access costs.** The window is a slice of Arrow buffers and nothing is converted
    until asked. `values[name]` converts that one column, once per window (`docs/issues/061`
    measured the version that converted every column on each `values` access: 2.2M cells for
    64K wanted, per callback). `latest()` and `counts()` stay in Arrow and convert one scalar
    per name at most. Iterating `values` converts every column, which is what asking for every
    column costs; a model that wants a short daily read beside a long periodic one declares two
    `DatasetInput`s with two lookbacks.
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

    def series(self, instrument: str = NO_INSTRUMENT) -> Series[object]:
        """One name's values over the window's instants as a `Series`, `None` where it had none."""
        return Series(instrument, self.instants, self._cells(instrument))

    def _cells(self, instrument: str) -> tuple[object, ...]:
        """One name's cells over the window, converted once per window (`docs/issues/061`)."""
        cached = self._values.get(instrument)
        if cached is None:
            # An Arrow slice shares the panel's buffers; only this window's cells are converted.
            cached = self._values[instrument] = tuple(
                self._column(instrument).to_pylist()
            )
        return cached

    def _column(self, instrument: str) -> pa.Array:
        """This window's slice of one name's Arrow column; shares the panel's buffers."""
        columns = self.panel.columns[self.field]
        if instrument not in columns:
            raise KeyError(
                f"{instrument!r} is not an instrument of this window; it holds "
                f"{', '.join(self.panel.instruments) or 'no instrument axis'}"
            )
        return columns[instrument].slice(self.start, self.stop - self.start)

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
        found: dict[str, object] = {}
        if self.stop <= self.start:
            return CrossSection._trusted(found)
        last = self.stop - self.start - 1
        for name in self.panel.instruments or (NO_INSTRUMENT,):
            cell = self._column(name)[last]
            if cell.is_valid:
                found[name] = cell.as_py()
        # The panel's instruments are sorted at build time, so `found` is already in id order.
        return CrossSection._trusted(found, self.panel.instants[self.stop - 1])

    def latest(self) -> CrossSection[object]:
        """The newest non-null value per name ANYWHERE in the window; a name with none is absent.

        A time-series read: the last value each name carried, however old. On a sparse panel this
        is not the cross-section at the evaluation instant -- a name whose newest value is a week
        old returns it without a word, and the mapping does not say which values are current.
        `current()` answers that question (`docs/issues/072`).
        """
        found: dict[str, object] = {}
        keys = self.panel.instruments or (NO_INSTRUMENT,)
        for name in keys:
            # pyarrow's stubs omit `drop_null`; the kernel exists at runtime.
            present = pc.drop_null(self._column(name))  # type: ignore[attr-defined]
            if len(present):
                found[name] = present[len(present) - 1].as_py()
        # No single instant: each name's newest value may sit on a different row.
        return CrossSection._trusted(found)

    def counts(self) -> dict[str, int]:
        """Non-null values per name inside the window: the access record's `actual_rows`."""
        keys = self.panel.instruments or (NO_INSTRUMENT,)
        counts: dict[str, int] = {}
        for name in keys:
            column = self._column(name)
            counts[name] = len(column) - column.null_count
        return counts

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
        return self._window.panel.instruments or (NO_INSTRUMENT,)

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
