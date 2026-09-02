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
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType

import pyarrow as pa

from vqapr.data.lookback import CalendarLookback, RowsLookback

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
    `values[name]` that name's values over `instants` (`None` where absent); `latest()` the
    newest non-null value per name -- the cross-section a one-instant lookback means.
    """

    panel: Panel
    field: str
    start: int
    stop: int
    evaluation_time: datetime
    _values: dict[str, tuple[object, ...]] = field(default_factory=dict, init=False, repr=False)

    @property
    def instants(self) -> tuple[datetime, ...]:
        return self.panel.instants[self.start : self.stop]

    @property
    def instruments(self) -> tuple[str, ...]:
        return self.panel.instruments

    def __len__(self) -> int:
        return self.stop - self.start

    def series(self, instrument: str = NO_INSTRUMENT) -> tuple[object, ...]:
        """One name's values over the window's instants, `None` where it had none."""
        cached = self._values.get(instrument)
        if cached is None:
            columns = self.panel.columns[self.field]
            if instrument not in columns:
                raise KeyError(
                    f"{instrument!r} is not an instrument of this window; it holds "
                    f"{', '.join(self.panel.instruments) or 'no instrument axis'}"
                )
            # An Arrow slice shares the panel's buffers; only this window's cells are converted.
            cached = self._values[instrument] = tuple(
                columns[instrument].slice(self.start, self.stop - self.start).to_pylist()
            )
        return cached

    @property
    def values(self) -> Mapping[str, tuple[object, ...]]:
        """Every column of the window, keyed by instrument (`""` for a panel with no axis)."""
        keys = self.panel.instruments or (NO_INSTRUMENT,)
        return MappingProxyType({name: self.series(name) for name in keys})

    def latest(self) -> Mapping[str, object]:
        """The newest non-null value per name inside the window; a name with none is absent."""
        found: dict[str, object] = {}
        keys = self.panel.instruments or (NO_INSTRUMENT,)
        for name in keys:
            for value in reversed(self.series(name)):
                if value is not None:
                    found[name] = value
                    break
        return MappingProxyType(found)

    def counts(self) -> dict[str, int]:
        """Non-null values per name inside the window: the access record's `actual_rows`."""
        keys = self.panel.instruments or (NO_INSTRUMENT,)
        return {name: sum(1 for value in self.series(name) if value is not None) for name in keys}

    @property
    def max_available_at(self) -> datetime | None:
        return self.panel.instants[self.stop - 1] if self.stop > self.start else None

    @property
    def lower_bound(self) -> datetime | None:
        return self.panel.instants[self.start] if self.stop > self.start else None


__all__ = ["NO_INSTRUMENT", "Panel", "PanelWindow", "panel_identity"]
