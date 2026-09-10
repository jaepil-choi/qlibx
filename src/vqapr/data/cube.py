"""A cube: one dataset's numeric fields over every instrument, as files a batch memory-maps.

Record `236` (`docs/issues/098`). A `--jobs` batch of 671 runs read one 430 MB parquet 671
times, each worker scanning it into a panel of its own, and twelve of those panels would not fit
in 15.7 GB beside twelve interpreters. The data itself is small -- 309 names over seven years of
one field is 7 MB -- so what cost was the copies, and the scans that made them.

A cube is the panel a batch would build if it declared **every** instrument the source holds:
per numeric field one `(instants x instruments)` float64 matrix, `NaN` where the source had no
value, laid out exactly as `Panel.from_table` lays a field out (`panel.placement`), written as a
`.npy` beside an `instants.npy`, an `instruments.json` and a `present.npy` that says where a
source row existed at all. The driver bakes it once when the batch starts (`orchestration.
batch_cubes`) and removes it when the batch ends; a worker memory-maps the files and takes its
panel as a slice -- a view when the run declared the whole universe, a gather otherwise. The OS
page cache then holds the bytes once per machine for every worker that maps them
(`experiments/exp_236_the_panel_memory`: four processes, one 0.40 GB file, 0.48 GB of memory
and 0.00 private per process; `np.load` costs 1.58 GB), and pages nobody touches are never read.

A cube never persists beyond its batch (owner decision 2026-09-10): a single run scans as it
always did, and no file accumulates. A dataset whose declared field is not numeric, whose
registration is unverified, or whose grain is `rows` has no cube; its worker takes the scan path
and refuses what it must, by name, as before.
"""

from __future__ import annotations

import json
from bisect import bisect_left, bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import MappingProxyType

import numpy as np
import pyarrow as pa

from vqapr.data import scan
from vqapr.data.datasets import DatasetRegistration
from vqapr.data.panel import NO_INSTRUMENT, Panel, dense_block, placement
from vqapr.data.sources import SourceSpec

CUBE_META = "cube.json"
INSTANTS_FILE = "instants.npy"
INSTRUMENTS_FILE = "instruments.json"
PRESENT_FILE = "present.npy"

_KINDS: dict[str, pa.DataType] = {"DOUBLE": pa.float64(), "INTEGER": pa.int64()}
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class Cube:
    """One baked dataset: its axes, its field kinds, and where its matrices lie."""

    dataset_id: str
    source_digest: str
    directory: Path
    instants: tuple[datetime, ...]
    instruments: tuple[str, ...]
    kinds: Mapping[str, pa.DataType]

    @property
    def names(self) -> tuple[str, ...]:
        return self.instruments or (NO_INSTRUMENT,)

    @property
    def fields(self) -> tuple[str, ...]:
        return tuple(self.kinds)

    def field(self, name: str) -> np.ndarray:
        """The field's `(instants x names)` matrix, memory-mapped read-only: no bytes copied."""
        return np.load(self.directory / f"{name}.npy", mmap_mode="r")

    def present(self) -> np.ndarray:
        """Where a source row existed, `(instants x names)` bool, memory-mapped."""
        return np.load(self.directory / PRESENT_FILE, mmap_mode="r")


def bake(
    root: Path,
    *,
    registration: DatasetRegistration,
    source: SourceSpec,
    source_digest: str,
    fields: Sequence[str],
    session: scan.ScanSession | None = None,
) -> Cube | None:
    """Write `<root>/<dataset_id>/` for the numeric fields named; `None` when nothing can be.

    One scan over every instrument and the registered span, then one matrix per field, saved
    and dropped in turn so the driver holds one field at a time beside the scan's columns.
    `source_digest` is the digest of the bytes the scan read, measured by the caller; a worker
    compares it with its own before trusting the cube.
    """
    span = registration.span
    types = registration.field_types
    if span is None or types is None or registration.grain is None:
        return None
    numeric = [name for name in fields if str(types.get(name, "")) in _KINDS]
    if not numeric:
        return None
    keyed = registration.instrument_field is not None
    if keyed:
        found = scan.distinct_values(source, registration.instrument_field or "")
        names = tuple(sorted(str(value) for value in found if value is not None))
    else:
        names = (NO_INSTRUMENT,)
    table = scan.observation_table(
        source,
        instrument_field=registration.instrument_field,
        available_at_field=registration.available_at,
        key_fields=registration.key_fields,
        fields={name: registration.fields[name] for name in numeric},
        aggregated=registration.aggregated,
        instruments=None,
        evaluation_time=span[1],
        lower_bound=span[0],
        session=session,
    )
    instants, keep, rows, cols = placement(table, names, keyed)
    count = len(instants)
    directory = root / str(registration.dataset_id)
    directory.mkdir(parents=True, exist_ok=True)
    present = np.zeros((count, len(names)), dtype=bool)
    present[rows, cols] = True
    np.save(directory / PRESENT_FILE, present)
    del present
    for name in numeric:
        values = table.column(name).combine_chunks()
        np.save(directory / f"{name}.npy", dense_block(values, count, len(names), keep, rows, cols))
    np.save(
        directory / INSTANTS_FILE,
        np.array([_microseconds(instant) for instant in instants], dtype=np.int64),
    )
    (directory / INSTRUMENTS_FILE).write_text(
        json.dumps(list(names if keyed else ())), encoding="utf-8"
    )
    meta = {
        "dataset_id": str(registration.dataset_id),
        "source_digest": source_digest,
        "fields": {name: str(types[name]) for name in numeric},
    }
    (directory / CUBE_META).write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return open_cube(root, str(registration.dataset_id))


def open_cube(root: Path | None, dataset_id: str) -> Cube | None:
    """The cube baked for one dataset under `root`, or `None` when there is none to map."""
    if root is None:
        return None
    directory = root / dataset_id
    try:
        meta = json.loads((directory / CUBE_META).read_text(encoding="utf-8"))
        instruments = tuple(json.loads((directory / INSTRUMENTS_FILE).read_text(encoding="utf-8")))
        stamps = np.load(directory / INSTANTS_FILE)
    except (OSError, ValueError):
        return None
    if meta.get("dataset_id") != dataset_id:
        return None
    return Cube(
        dataset_id=dataset_id,
        source_digest=str(meta.get("source_digest", "")),
        directory=directory,
        instants=tuple(_EPOCH + timedelta(microseconds=int(stamp)) for stamp in stamps.tolist()),
        instruments=tuple(str(name) for name in instruments),
        kinds=MappingProxyType({name: _KINDS[kind] for name, kind in meta["fields"].items()}),
    )


def panel_from_cube(
    cube: Cube,
    *,
    fields: Sequence[str],
    instruments: Sequence[str],
    keyed_by_instrument: bool,
    identity: str,
    source_digest: str,
    bounds: tuple[datetime, datetime],
) -> Panel:
    """The panel a scan over `bounds` for `instruments` would have built, taken from the cube.

    The instant axis is the cube's instants inside `bounds` on which at least one of the names
    has a source row -- the same axis `Panel.from_table` derives from the rows a scan returns.
    When the names are the cube's names in order and every instant in range carries a row, each
    block is a **view** of the memory-mapped file: nothing copied, the pages shared with every
    other worker mapping them. Otherwise the block is one gather of the names' columns, the size
    of what the run declared.
    """
    names = tuple(instruments) if keyed_by_instrument else (NO_INSTRUMENT,)
    lo = bisect_left(cube.instants, bounds[0])  # type: ignore[type-var]
    hi = bisect_right(cube.instants, bounds[1])  # type: ignore[type-var]
    positions = {name: index for index, name in enumerate(cube.names)}
    where = [positions.get(name, -1) for name in names]
    found = np.array([index for index in where if index >= 0], dtype=np.int64)
    into = np.array([slot for slot, index in enumerate(where) if index >= 0], dtype=np.int64)
    present = cube.present()[lo:hi]
    if found.size:
        carried = np.asarray(present[:, found]).any(axis=1)
    else:
        carried = np.zeros(hi - lo, dtype=bool)
    whole = bool(carried.all())
    identical = names == cube.names
    if whole:
        instants = cube.instants[lo:hi]
    else:
        kept = np.flatnonzero(carried)
        instants = tuple(cube.instants[lo + int(index)] for index in kept.tolist())
    blocks: dict[str, np.ndarray] = {}
    for name in fields:
        matrix = cube.field(name)[lo:hi]
        if whole and identical:
            block = matrix
        elif whole and found.size == len(names):
            block = np.ascontiguousarray(matrix[:, found])
        else:
            block = np.full((len(instants), len(names)), np.nan)
            if found.size:
                selected = matrix if whole else matrix[np.flatnonzero(carried)]
                block[:, into] = selected[:, found]
        blocks[name] = block
    return Panel(
        dataset_id=cube.dataset_id,
        fields=tuple(fields),
        instruments=names if keyed_by_instrument else (),
        instants=instants,
        blocks=MappingProxyType(blocks),
        kinds=MappingProxyType({name: cube.kinds[name] for name in fields}),
        columns=MappingProxyType({}),
        identity=identity,
        source_digest=source_digest,
        bounds=bounds,
    )


def _microseconds(instant: datetime) -> int:
    return (instant - _EPOCH) // timedelta(microseconds=1)


__all__ = ["CUBE_META", "Cube", "bake", "open_cube", "panel_from_cube"]
