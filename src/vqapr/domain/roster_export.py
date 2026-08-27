"""Write a declared roster to the kind-keyed parquet tables registration reads.

This is the half a user's `instruments.py` calls. That file is a **one-shot generation tool**: the
user reads their own data with whatever tool they have, derives each instrument's category, and
exports. The framework never registers, reads or fingerprints `instruments.py` itself -- its
status is exactly that of `scripts/prepare_dev_data.py`, and registration begins at the clean file
it produced.

Why a script rather than a mapping in the declaration: a category is a typed value and a real
universe is generated rather than typed. The motivating case is an instrument whose facts are not
columns at all -- an option named `2603만기 삼성전자 콜옵션` carries its expiry, underlying and
right inside a string, with no `right` column to map. No declaration syntax parses that; a few
lines of the user's own Python do.

The exporter validates while building, which is the first of the two validations this design runs.
It is not the guarantee: registration re-validates the written file, because a hand-written
parquet is an equally legitimate input.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path

from vqapr.domain.instruments import InstrumentKind
from vqapr.domain.roster import INSTRUMENT_ID_FIELD, KIND_FIELD, RosterEntry, _kind


def export_roster(
    universe: Mapping[str, str | InstrumentKind],
    directory: Path | str,
    *,
    stem: str = "instruments",
) -> dict[str, Path]:
    """Write one parquet per declared category and return `{kind: path}`.

    ``universe`` is the flat `{instrument_id: kind}` an author naturally builds. The split into
    per-kind tables happens here rather than in the author's head.

    Returns the mapping a declaration needs, so the emitted template can print exactly what to
    paste. Nothing is written for a category the universe does not use: an empty table would be a
    file whose only content is a schema, and a declaration pointing at one would claim the project
    trades a category it does not.
    """
    target = Path(directory)
    grouped: dict[InstrumentKind, list[RosterEntry]] = {}
    for instrument_id, declared in universe.items():
        entry = RosterEntry(instrument_id=str(instrument_id), kind=_kind(declared))
        grouped.setdefault(entry.kind, []).append(entry)
    if not grouped:
        raise ValueError("a roster must declare at least one instrument")

    target.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    for kind, entries in sorted(grouped.items(), key=lambda item: str(item[0])):
        path = target / f"{stem}_{kind}.parquet"
        _write_table(path, entries)
        written[str(kind)] = path
    return written


def _write_table(path: Path, entries: Iterable[RosterEntry]) -> None:
    """One table, sorted by id so a re-export of an unchanged universe is byte-identical.

    Determinism matters here for the same reason it matters for any committed fixture: a digest
    that moves because a dictionary iterated differently would report a change nobody made.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    rows = sorted((entry.row for entry in entries), key=lambda row: row[INSTRUMENT_ID_FIELD])
    if not rows:
        raise ValueError(f"instrument table {path.name!r} would be empty")
    table = pa.table(
        {
            INSTRUMENT_ID_FIELD: [row[INSTRUMENT_ID_FIELD] for row in rows],
            KIND_FIELD: [row[KIND_FIELD] for row in rows],
        }
    )
    pq.write_table(table, path)


def read_roster_table(path: Path | str) -> dict[str, str]:
    """Read one roster table back as `{instrument_id: kind}`, refusing a malformed one.

    Used by registration rather than by the exporter, and deliberately strict: the file may have
    been written by hand, by an older exporter, or by a script that got the schema wrong, and each
    of those must be refused with a message naming what is missing rather than producing a roster
    that is quietly short a column.
    """
    import pyarrow.parquet as pq

    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"instrument table is missing: {source}")
    table = pq.read_table(source)
    columns = set(table.column_names)
    missing = [field for field in (INSTRUMENT_ID_FIELD, KIND_FIELD) if field not in columns]
    if missing:
        raise ValueError(
            f"instrument table {source.name!r} is missing required column(s) "
            f"{', '.join(missing)}; it must carry {INSTRUMENT_ID_FIELD} and {KIND_FIELD}"
        )
    ids = [str(value) for value in table.column(INSTRUMENT_ID_FIELD).to_pylist()]
    kinds = [str(value) for value in table.column(KIND_FIELD).to_pylist()]
    if not ids:
        raise ValueError(f"instrument table {source.name!r} declares no instruments")
    resolved: dict[str, str] = {}
    for instrument_id, kind in zip(ids, kinds, strict=True):
        if instrument_id in resolved and resolved[instrument_id] != kind:
            raise ValueError(
                f"instrument {instrument_id!r} appears twice in {source.name!r} with "
                f"different kinds ({resolved[instrument_id]!r} and {kind!r})"
            )
        resolved[instrument_id] = kind
    return resolved
