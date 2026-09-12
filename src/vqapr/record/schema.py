"""What a run record IS on disk: its layout, its field sets, and how a value is spelled.

The shape half of the record package. Nothing here touches the filesystem: the names of the
files and directories, the three pydantic models whose fields ARE the record, the path each
record lives at, and the two encodings a record round-trips through -- Arrow for the tables and
JSON for the facts.

Imported by `reader.py` and `writer.py`, and importing neither. That is the package's layering
(schema, then reader, then writer), and it is what lets the record be read by a process that
never runs anything.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow as pa
from pydantic import BaseModel, ConfigDict

RUNS_DIRECTORY = "runs"
RECORD_FILENAME = "record.json"
RUN_FILENAME = "run.json"
STRATEGY_FILENAME = "strategy.json"
STRATEGIES_DIRECTORY = "strategies"
DATAMODEL_FILENAME = "datamodel.json"
DATAMODELS_DIRECTORY = "datamodels"
"""Two records per run since record `139` (design §4.2).

`<root>/runs/<run-id>/run.json` is the configuration every strategy shared, written before
any strategy starts; `<root>/runs/<run-id>/strategies/<id>@<fp8>/strategy.json` is one
strategy's output, beside its `tables/`. `record.json` remains the materialization record
(and a run record written before `139`, which `read_record` still reads).
"""
TABLES_DIRECTORY = "tables"
PART_SUFFIX = ".parquet"
"""Each table is a directory of parquet: `all.parquet` once the run has ended, spill parts
(`000000.parquet`, ...) only while it is still running and only when the buffer overflowed.

Record `146` (deletion campaign Step 5). The rows were JSONL with a `.types.json` sidecar that
said which Python type each column had been stringified from, because JSON cannot carry a type
and a reader guessing from the text shifted every instant by its offset (the testbed's A5).
Parquet carries the types: an instant is a `timestamp[us, tz]` and comes back as the same
instant in the same zone through pyarrow and through duckdb alike. A `Decimal` is the one
value stored as text -- exact and unbounded, where a parquet decimal would need a fixed scale
and a weight of one third has twenty-eight places -- and the column's field metadata says so
(`vqapr.type: decimal`), so `read_table` restores it and a duckdb reader casts it knowingly.

**Written once, at the end (`docs/issues/archive/087`).** Record `146` wrote one complete file per
accepted event, because a parquet file is readable only once its footer is written and a
killed run was to leave every chunk that landed (record `135`). Measured, that was a physical
write per event per table -- about a fifth of a real strategy's wall clock -- and a
finished table of six hundred 8 KB files whose framing outweighed their data a hundredfold.
The owner's ruling (2026-09-07): rows stay in memory as Arrow batches and land as one file
per table when the run ENDS -- normally, or through an exception or an interrupt, since the
writer's `release` runs on both paths. What no code can save is a hard kill (`terminate`, an
OOM kill, a power cut): then only what `SPILL_BYTES` had already forced to disk survives. A
reader prefers `all.parquet` and ignores spill parts beside it, so a crash between the compact
write and the parts' removal cannot double-count.
"""

COMPACT_FILENAME = "all.parquet"
"""The one file a finished table or dataset is: written when the run ends, after which any spill
part beside it is stale input. Shared with `vqapr.run.engine.output`, which writes an output
dataset the same way (`docs/issues/archive/087`).

Here rather than beside that writer -- where both lived until campaign M6 Step 3 -- because a
compaction filename and a spill threshold are facts about how bytes reach the disk, not about the
datamodel phase. They were also the last thing that would have forced this package to import
`flow/`, which is the one edge the promotion exists to remove."""

SPILL_BYTES = 256 * 1024 * 1024
"""The safety valve, for both writers: buffered Arrow bytes above this are written as one spill
part. A run of a few million rows would otherwise hold them all; at this size a part is a few
seconds of disk and the buffer never exceeds a quarter gigabyte. It is not a flush cadence -- a
run below the line writes nothing until it ends -- and a hard kill loses at most this much."""

PROGRESS_FILENAME = "progress.json"
LOCK_TOUCH_EVERY = 1.0
"""How often the heartbeat touches the run lock, at most. `LOCK_STALE_AFTER` is two minutes, so a
touch a second says "alive" a hundred times over; touching on every record chunk instead was one
`utime` per row batch (record `248`: 110 for a ten-decision run, 330 for thirty-seven), and on a
network share each is a round trip."""
PROGRESS_EVERY = 5.0
"""What a running member says about itself while its rows are still in memory: accepted
events, rows per table and the last `event_time`, rewritten by the heartbeat at most every
`PROGRESS_EVERY` seconds. `list strategies --run` reads it (`member_progress`); before `087`
it counted part files, and there are none to count now."""

DEFAULT_TABLE_PREFIX = "vqapr."
"""Table ids the package owns. A Strategy declaring one is refused when its recorder is built."""

WEIGHT_TABLE = f"{DEFAULT_TABLE_PREFIX}weight"
ACCOUNT_TABLE = f"{DEFAULT_TABLE_PREFIX}account"
MONITORING_TABLE = f"{DEFAULT_TABLE_PREFIX}monitoring"
FILL_TABLE = f"{DEFAULT_TABLE_PREFIX}fill"
FRAMEWORK_TABLES = (WEIGHT_TABLE, ACCOUNT_TABLE, MONITORING_TABLE, FILL_TABLE)
"""The tables the package records on a strategy's behalf, which nobody declares. Named here, where a
record is described, so a reader of records never imports the engine that writes them; the engine
builds their column specs from these names. `vqapr.monitoring` is written only by a run that
declared a Compliance rule, but it is the package's table either way."""

SCHEMA = "vqapr-run-record/v2"
"""Bumped from `v1` by record `115`, when the record gained a `kind` discriminator.

A reader is now entitled to branch on this. `read_record` refuses a major version it does not know
instead of handing back a mapping whose fields mean something else -- see `_require_known_schema`.

Since record `139` this is the schema of `record.json` only: a materialization, or a run written
before the two-level layout. `run.json` and `strategy.json` carry their own schemas below.
"""

RUN_KIND = "run"
"""A simulation record written before record `139`: one directory, one strategy, `record.json`."""

STRATEGY_KIND = "strategy"
"""One strategy's output inside a run: `strategies/<id>@<fp8>/strategy.json` (record `139`)."""

RUN_SCHEMA = "vqapr-run/v2"
"""The schema of `run.json`: configuration, written by `write_run_record`.

v2 since vqapr 0.16.0 (record `278`), with the strategy and datamodel schemas: `agenda` is
`schedule` and `occurrence` is `event`. A v1 record is refused with a re-run fix, not translated.
"""

STRATEGY_SCHEMA = "vqapr-strategy-record/v2"
DATAMODEL_SCHEMA = "vqapr-datamodel-record/v2"
"""The schema of `strategy.json`, written by `RunRecordWriter.finish(kind=STRATEGY_KIND)`."""

DATAMODEL_KIND = "datamodel"
"""One datamodel of a run (record `148`): the schema of `datamodel.json`."""

_RUN_FIELDS = (
    "run_id",
    "account",
    "tables",
    "contract",
    "source_digest",
    "declared_digest",
    "roster",
    "period",
)
"""The field set a run record carries, named once and read by both the writer and every reader.

AC-R5 asks that `show run`'s output and the frozen record carry the same fields. This lives here,
beside the record itself, rather than in the CLI that displays it: the record is the artifact and
the CLI is one of its readers, so the CLI importing this is the right direction and the core
package importing from the CLI was not.

`schema` is deliberately absent: it is the record's own metadata, not one of its answers.

`declared_digest` and `roster_digest` had builders in `_freeze_record` and were absent from this
tuple, so the writer's comprehension never called them: two facts computed on every run and
dropped before they reached disk. Same shape as the `Fill.kind` column record `067` added -- the
object was right and the record did not carry it.

`roster` is the successor to that `roster_digest`, not the same field renamed: it carries a mapping
with the declared tables and the per-category counts, and `null` when the run read no roster at
all. Only `declared_digest` is the original builder, wired up.

**`roster` is `null` here and `{"known": false, "note": ...}` in the run's success envelope, and
that difference is deliberate.** This tuple guarantees the key exists, so `null` cannot be read as
"this version does not report one" -- the ambiguity the envelope has to defend against, since a
JSON envelope carries no schema with it. The envelope also carries a note naming the consequence
and the remedy, which belongs where someone is about to act and not in an archive of what a past
run did.
"""


class _Record(BaseModel):
    """A record's field set, named once (one-shape campaign Step 6, record 161).

    The same list used to be written three times: a tuple here, a builder dict in `records.py`,
    and every reader's `record.get(field)`. The model is the one place now: a freeze function
    constructs it (a field missing or unknown is refused at construction, before anything
    reaches disk), the tuples below derive from `model_fields` for the readers that still ask by
    name, and `RunRecordWriter.finish` dumps it through `_encode` so the JSON on disk did not
    move. Values are typed loosely on purpose -- the record is the writer's contract about
    *which answers exist*, and `_encode` already fixes how each value is spelled.

    Readers keep their dict shape behind the schema-string gate: a `strategy.json` written under
    the same schema before `timing` existed must still read, and that compatibility is the
    schema string's business, not a validator's.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    def as_record(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in type(self).model_fields}


class RunRecord(_Record):
    """`run.json`: the configuration every strategy of this run shares (record `139`) --
    architecture §17.3.1's missing rows: the universe, the venue and the execution dataset with its
    fill convention (`docs/issues/archive/034`), the initial account declaration, the datasets and
    their
    source digests (A7), and which strategies the run names."""

    run_id: str
    writes: str
    declared_digest: str
    instruments: list[str]
    period: dict[str, Any]
    exchange: dict[str, Any] | None
    execution: dict[str, Any] | None
    initial_account: dict[str, Any] | None
    datasets: list[dict[str, Any]]
    strategies: list[dict[str, Any]]
    datamodels: list[dict[str, Any]]


class StrategyRecord(_Record):
    """`strategy.json`: what one strategy's record answers (record `139`) -- which `.py` ran
    (`component.path`) and the strategy's OWN fingerprint, registered (`fingerprint`) and as
    loaded (`source_digest`, per component rather than folded) -- beside the final account, the
    tables, the contract report, the roster, the period, and where the wall clock went."""

    run_id: str
    strategy_ref: str
    strategy_id: str
    fingerprint: str
    component: dict[str, Any]
    schedule: dict[str, Any]
    compliance: list[dict[str, Any]]
    exchange: dict[str, Any] | None
    """The venue this strategy filled on: its component id, its registered fingerprint and its
    `settings` -- what it declared it models (design §6.1), so a reader learns which regimes a
    past run measured under without opening the venue's source at its digest."""
    account: dict[str, Any] | None
    tables: dict[str, Any]
    contract: dict[str, Any]
    source_digest: dict[str, str]
    declared_digest: str
    roster: dict[str, Any] | None
    period: dict[str, Any]
    timing: dict[str, float]


class DatamodelRecord(_Record):
    """`datamodel.json`: what one datamodel's record answers (record `148`) -- the component that
    ran, registered and as loaded; the dataset it wrote and the fields it declared; one row per
    session and no per-instrument lineage (`docs/issues/archive/059`)."""

    run_id: str
    datamodel_ref: str
    datamodel_id: str
    fingerprint: str
    component: dict[str, Any]
    schedule: dict[str, Any]
    dataset_id: str
    value_fields: list[str]
    rows: int
    sessions: list[dict[str, Any]]
    source_digest: dict[str, str]
    declared_digest: str
    period: dict[str, Any]


_STRATEGY_FIELDS = tuple(StrategyRecord.model_fields)
_DATAMODEL_FIELDS = tuple(DatamodelRecord.model_fields)
RUN_JSON_FIELDS = tuple(RunRecord.model_fields)
"""Derived from the models, for the readers that ask a record's field set by name. `_RUN_FIELDS`
above is not derived: it is the field set of `record.json`, the per-run record written before
record `139`, which no source path writes any more and `read_record` still reads."""

RECORD_FIELDS_BY_KIND: dict[str, tuple[str, ...]] = {
    RUN_KIND: _RUN_FIELDS,
    STRATEGY_KIND: _STRATEGY_FIELDS,
    DATAMODEL_KIND: _DATAMODEL_FIELDS,
}

MEMBER_KINDS: dict[str, tuple[str, str, str, str]] = {
    STRATEGY_KIND: (STRATEGIES_DIRECTORY, STRATEGY_FILENAME, STRATEGY_SCHEMA, "strategy_ref"),
    DATAMODEL_KIND: (DATAMODELS_DIRECTORY, DATAMODEL_FILENAME, DATAMODEL_SCHEMA, "datamodel_ref"),
}
"""The two kinds of member a run holds (record `148`): where each records, the file that marks
it complete, its schema, and the head key naming its directory."""


def record_fields(kind: str) -> tuple[str, ...]:
    """The field set for one record kind, refusing an unknown kind rather than guessing.

    A `KeyError` here is the same deliberate guarantee the flat tuple gave: a builder named without
    a field, or a field named without a builder, fails at the write rather than producing a record
    that is quietly missing an answer.
    """
    try:
        return RECORD_FIELDS_BY_KIND[kind]
    except KeyError:
        raise KeyError(
            f"unknown run-record kind {kind!r}; known kinds are "
            f"{', '.join(sorted(RECORD_FIELDS_BY_KIND))}"
        ) from None


def record_directory(
    root: Path, run_id: str, strategy_ref: str | None = None, *, kind: str = STRATEGY_KIND
) -> Path:
    """Where one record lives: the run's directory, or one member's directory beneath it."""
    directory = root / RUNS_DIRECTORY / run_id
    if strategy_ref is None:
        return directory
    return directory / MEMBER_KINDS[kind][0] / strategy_ref


def record_path(root: Path, run_id: str) -> Path:
    return root / RUNS_DIRECTORY / run_id / RECORD_FILENAME


def run_record_path(root: Path, run_id: str) -> Path:
    return root / RUNS_DIRECTORY / run_id / RUN_FILENAME


_DECIMAL = {b"vqapr.type": b"decimal"}
_NONE = type(None)
"""Field metadata marking a string column that holds `Decimal` text; see `PART_SUFFIX`."""


def _zone_name(value: datetime) -> str:
    """The zone a `timestamp[us, tz]` column is declared in, from the first aware value seen."""
    zone = value.tzinfo
    name = getattr(zone, "key", None) or getattr(zone, "zone", None)
    if isinstance(name, str) and name:
        return name
    offset = value.utcoffset() or timedelta()
    sign = "+" if offset >= timedelta() else "-"
    minutes = abs(int(offset.total_seconds())) // 60
    return f"{sign}{minutes // 60:02d}:{minutes % 60:02d}"


def _arrow_type(values: Sequence[object], table_id: str, column: str) -> pa.Field:
    """One column's Arrow field from its Python values, refusing a column of two kinds.

    `int` and `float` together are `float64`; `bool` is its own type and never an int here,
    which is why it is tested first. A column of two kinds (a `Decimal` beside text) is
    refused rather than downgraded: the recorder wrote both, so the run's own table is the
    thing that is wrong, and a silent common type would hide it (`prefer fast, explicit
    failure`).
    """
    # One pass that stays in C finds the distinct Python types; the few types are then classified
    # once each. Asking every cell in turn cost as much as building the column (record `221`).
    kinds: set[str] = set()
    for kind in {type(value) for value in values}:
        if kind is _NONE:
            continue
        if issubclass(kind, bool):
            kinds.add("bool")
        elif issubclass(kind, Decimal):
            kinds.add("decimal")
        elif issubclass(kind, datetime):
            kinds.add("datetime")
        elif issubclass(kind, int):
            kinds.add("int")
        elif issubclass(kind, float):
            kinds.add("float")
        else:
            kinds.add("string")
    first_instant: datetime | None = (
        next((value for value in values if isinstance(value, datetime)), None)
        if "datetime" in kinds
        else None
    )
    if kinds <= {"int", "float"} and kinds:
        return pa.field(column, pa.float64() if "float" in kinds else pa.int64())
    if len(kinds) > 1:
        raise ValueError(
            f"table {table_id!r} column {column!r} holds values of two kinds "
            f"({', '.join(sorted(kinds))}); a recorded column holds one"
        )
    kind = next(iter(kinds), None)
    if kind is None:
        return pa.field(column, pa.null())
    if kind == "decimal":
        return pa.field(column, pa.string(), metadata=_DECIMAL)
    if kind == "datetime":
        assert first_instant is not None
        if first_instant.tzinfo is None:
            raise ValueError(f"table {table_id!r} column {column!r} holds a naive datetime")
        return pa.field(column, pa.timestamp("us", tz=_zone_name(first_instant)))
    return pa.field(column, {"bool": pa.bool_(), "string": pa.string()}[kind])


def _arrow_table(
    columns: Mapping[str, Sequence[object]], table_id: str, remembered: dict[str, pa.Field]
) -> pa.Table:
    """One chunk as an Arrow table, each column typed as this writer first saw it.

    A column's type is fixed the first time a non-null value is seen and every later chunk is
    cast to it; a column that was null in an earlier chunk was written `null`-typed there,
    which every reader unions with the later type. A later chunk that cannot be cast is
    refused by name.

    Takes the chunk as columns (record `221`): the recorder staged them that way, so nothing
    here walks rows.
    """
    fields: list[pa.Field] = []
    arrays: list[pa.Array] = []
    for column in sorted(columns):
        values = columns[column]
        seen = _arrow_type(values, table_id, column)
        field = remembered.get(column)
        if field is None:
            field = seen
            if not pa.types.is_null(seen.type):
                remembered[column] = seen
        elif not pa.types.is_null(seen.type) and (
            seen.type != field.type or (seen.metadata or {}) != (field.metadata or {})
        ):
            if pa.types.is_integer(seen.type) and pa.types.is_floating(field.type):
                pass
            elif pa.types.is_timestamp(seen.type) and pa.types.is_timestamp(field.type):
                pass  # another zone, the same instants: cast below converts them
            else:
                raise ValueError(
                    f"table {table_id!r} column {column!r} was recorded as {field.type} and "
                    f"this chunk holds {seen.type}; a recorded column holds one kind"
                )
        if field.metadata == _DECIMAL:
            values = [None if value is None else str(value) for value in values]
        arrays.append(pa.array(values, type=field.type))
        fields.append(field)
    return pa.Table.from_arrays(arrays, schema=pa.schema(fields))


def _python_rows(
    batch: pa.RecordBatch, recorded_as_text: frozenset[str] = frozenset()
) -> Iterator[dict[str, Any]]:
    """Rows back as the values they were written from, `Decimal` included.

    `recorded_as_text` names number columns a record written before record `264` holds as
    untagged text; such a column is restored as `Decimal` as well, so an old record and a new one
    read the same. A tagged column needs no name.
    """
    decimal_columns = {
        field.name
        for field in batch.schema
        if (field.metadata and field.metadata == _DECIMAL)
        or (
            field.name in recorded_as_text
            and pa.types.is_string(field.type)
            and not field.metadata
        )
    }
    for row in batch.to_pylist():
        for column in decimal_columns:
            if row.get(column) is not None:
                row[column] = Decimal(row[column])
        yield row


def _encode(value: object) -> object:
    """One value in a form JSON round-trips without changing what it means.

    `Decimal` becomes a string rather than a float, because a float is a different number. That is
    the whole reason this is not `json.dumps(default=str)`: `str` on a datetime is not ISO-8601 in
    every locale, and silently producing an unparseable instant is worse than refusing.
    """
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return _encode_mapping(value)
    if isinstance(value, (list, tuple)):
        return [_encode(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _encode_mapping(value: Mapping[str, object]) -> dict[str, object]:
    """A record body in the same JSON-safe form, keeping the shape a writer spreads."""
    return {str(key): _encode(item) for key, item in value.items()}

