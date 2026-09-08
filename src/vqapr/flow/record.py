"""Freeze a run's own record to disk while it runs, so a later process can read it.

`recorder_rows` lives in memory for the whole run (`run_state.py:65`). A run that crashes leaves
nothing; a run that finishes leaves nothing anyone else can read. Two things follow, and neither is
a convenience:

- **Parallel execution is impossible.** Five processes running five factors each hold their results
  in their own memory, and nobody can read all five afterwards. That is AC-R4.
- **`show run <id>` has nothing to show.** The only way to answer a question about a finished run is
  to run it again. That is AC-R5.

The layout is argued in `docs/design/run-record-layout.md`; the two decisions that shape this
module are repeated here because they are the ones a reader will otherwise try to "simplify".
The tables are parquet since record `146`; see `PART_SUFFIX`.

**A directory scan, not an index file.** An index would put every concurrent writer on one
atomic-replace target, which is exactly the lost-update the workspace lock exists for
(`workspace.py:53-55`): two processes read, both append, the second write erases the first, and
nothing fails. Each run writes only inside its own directory, so two runs cannot collide.

**The writer appends in chunks.** `append` takes a chunk at a time and never re-reads what it
already wrote, so a caller that streams rows as it produces them gets crash survival and bounded
memory for free. Note what the PRODUCT currently does with that: `public.run` hands over
`recorder_rows` once, after the run returns, so today's records are written in one pass at the end.
The chunked interface is what makes streaming possible later; it is not a claim that the run
streams now.
"""

from __future__ import annotations

import errno
import json
import os
import shutil
import time as _time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
from pydantic import BaseModel, ConfigDict

from vqapr._internal import atomic
from vqapr.flow.datamodel import COMPACT_FILENAME, SPILL_BYTES, DataModelResult
from vqapr.flow.frozen import FrozenDataModel, FrozenRun, FrozenStrategy
from vqapr.flow.run_state import LifecycleKind
from vqapr.flow.simulation import SimulationResult

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

**Written once, at the end (`docs/issues/087`).** Record `146` wrote one complete file per
accepted occurrence, because a parquet file is readable only once its footer is written and a
killed run was to leave every chunk that landed (record `135`). Measured, that was a physical
write per occurrence per table -- about a fifth of a real strategy's wall clock -- and a
finished table of six hundred 8 KB files whose framing outweighed their data a hundredfold.
The owner's ruling (2026-09-07): rows stay in memory as Arrow batches and land as one file
per table when the run ENDS -- normally, or through an exception or an interrupt, since the
writer's `release` runs on both paths. What no code can save is a hard kill (`terminate`, an
OOM kill, a power cut): then only what `SPILL_BYTES` had already forced to disk survives. A
reader prefers `all.parquet` and ignores spill parts beside it, so a crash between the compact
write and the parts' removal cannot double-count.
"""

PROGRESS_FILENAME = "progress.json"
PROGRESS_EVERY = 5.0
"""What a running member says about itself while its rows are still in memory: accepted
occurrences, rows per table and the last `event_time`, rewritten by the heartbeat at most every
`PROGRESS_EVERY` seconds. `list strategies --run` reads it (`member_progress`); before `087`
it counted part files, and there are none to count now."""

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

RUN_SCHEMA = "vqapr-run/v1"
"""The schema of `run.json`: configuration, written by `write_run_record`."""

STRATEGY_SCHEMA = "vqapr-strategy-record/v1"
DATAMODEL_SCHEMA = "vqapr-datamodel-record/v1"
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
    fill convention (`docs/issues/034`), the initial account declaration, the datasets and their
    source digests (A7), and which strategies the run names."""

    run_id: str
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
    agenda: dict[str, Any]
    constraints: list[dict[str, Any]]
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
    session and no per-instrument lineage (`docs/issues/059`)."""

    run_id: str
    datamodel_ref: str
    datamodel_id: str
    fingerprint: str
    component: dict[str, Any]
    agenda: dict[str, Any]
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


_DECIMAL = {b"vqapr.type": b"decimal"}
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
    kinds: set[str] = set()
    first_instant: datetime | None = None
    for value in values:
        if value is None:
            continue
        if isinstance(value, bool):
            kinds.add("bool")
        elif isinstance(value, Decimal):
            kinds.add("decimal")
        elif isinstance(value, datetime):
            kinds.add("datetime")
            first_instant = first_instant or value
        elif isinstance(value, int):
            kinds.add("int")
        elif isinstance(value, float):
            kinds.add("float")
        elif isinstance(value, str):
            kinds.add("string")
        else:
            kinds.add("string")
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
    rows: Sequence[Mapping[str, object]], table_id: str, remembered: dict[str, pa.Field]
) -> pa.Table:
    """One chunk as an Arrow table, each column typed as this writer first saw it.

    A column's type is fixed the first time a non-null value is seen and every later chunk is
    cast to it; a column that was null in an earlier chunk was written `null`-typed there,
    which every reader unions with the later type. A later chunk that cannot be cast is
    refused by name.
    """
    columns = sorted({str(key) for row in rows for key in row})
    fields: list[pa.Field] = []
    arrays: list[pa.Array] = []
    for column in columns:
        values = [row.get(column) for row in rows]
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


def _python_rows(batch: pa.RecordBatch) -> Iterator[dict[str, Any]]:
    """Rows back as the values they were written from, `Decimal` included."""
    decimal_columns = {
        field.name for field in batch.schema if field.metadata and field.metadata == _DECIMAL
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


_ENVIRONMENT_ERRNOS = frozenset(
    getattr(errno, name)
    for name in (
        "ENOSPC",
        "EROFS",
        "EDQUOT",
        "ENAMETOOLONG",
        "EINVAL",
        "ENOTDIR",
        "EMFILE",
        "ENFILE",
        "EIO",
        "ESTALE",
        "ELOOP",
    )
    if hasattr(errno, name)
)
"""Errnos that never mean "another run holds this id".

A full disk, a read-only mount, a quota, a malformed path, exhausted descriptors, a stale network
handle. None is resolved by choosing a different run id, so none may be reported as one.

`EACCES`/`EPERM` are deliberately absent, and not by oversight: on Windows they also cover a
sharing violation, which IS contention -- the case this boundary exists to absorb. Errno alone
cannot tell a permission problem from a busy file, so those two are discriminated by asking the
lock who holds it rather than by membership here.
"""

_AMBIGUOUS_ERRNOS = frozenset(
    getattr(errno, name) for name in ("EACCES", "EPERM") if hasattr(errno, name)
)
"""Errnos that mean either a permission problem or a busy file, depending on the platform.

Resolved by asking the lock who holds it, because the errno cannot tell them apart.
"""

LOCK_FILENAME = ".running"
LOCK_STALE_AFTER = 120.0
"""How long a lock may go unrefreshed before its holder is treated as dead.

This is a HEARTBEAT threshold, not a run-duration budget, and the difference is the whole reason
the run refreshes its lock. Read as a duration budget it is catastrophically wrong here: a factor
run over this testbed takes three to six minutes, so every real run would age past it while still
executing and any peer could then take its id. Measured against an unrefreshed lock, exactly that
happened -- a live run and a thief wrote into one directory and the surviving record held
`['B1', 'A2']`, which is neither run.

So `append` touches the lock as it goes. A run that is doing anything at all keeps its claim, and
only a run that has stopped touching it for two minutes -- because its process is gone -- reads as
abandoned.
"""


@dataclass(frozen=True, slots=True)
class LockClaim:
    """A run lock still inside its heartbeat window, and how long since it was last touched.

    `age` is carried out of the read rather than recomputed by the caller, because it is the one
    fact that separates the two states this claim cannot tell apart: a run that is executing, and a
    run whose process died in the last `LOCK_STALE_AFTER` seconds. Both present as a fresh lock;
    only the age says how long the operator would have to wait to find out (`docs/issues/037`).
    """

    pid: int
    age: float

    @property
    def releases_in(self) -> float:
        """Seconds until an unrefreshed lock is treated as abandoned, floored at zero."""
        return max(LOCK_STALE_AFTER - self.age, 0.0)


def _lock_claim(lock: Path) -> LockClaim | None:
    """The claim on this run id, or `None` if nobody live holds one.

    A lock file older than `LOCK_STALE_AFTER` is treated as abandoned: its process died without
    releasing, and refusing forever on a dead holder would make a crash unrecoverable.

    **What this can and cannot know.** A fresh lock means the file was touched recently, which is
    not the same as the pid inside it being alive -- nothing here interrogates that pid, by design,
    because a pid is not portable liveness evidence and a recycled one is worse than none. Callers
    that render this to a user must say "holds a lock, last refreshed Ns ago" rather than "is
    running now"; a reporter who checked the pid, found nothing, and concluded the package lies is
    what `docs/issues/037` records.
    """
    try:
        # Clamped at zero. A lock written microseconds ago can carry an `st_mtime` marginally
        # ahead of `time.time()` -- filesystem and clock resolution differ -- and the difference
        # is an artifact, not information. Unclamped it reaches the operator as "-0s ago".
        age = max(_time.time() - lock.stat().st_mtime, 0.0)
    except OSError:
        return None
    if age > LOCK_STALE_AFTER:
        return None
    try:
        return LockClaim(int(lock.read_text(encoding="ascii").strip() or "-1"), age)
    except (OSError, ValueError):
        # Present and fresh but unreadable: still a live claim, just an anonymous one. Reporting
        # it as free would be the destructive answer.
        return LockClaim(-1, age)


class RunRecordLive(FileExistsError):
    """A run id is held by a lock that is still inside its heartbeat window.

    Distinct from `RunRecordExists` because the remedy is opposite: an existing RECORD is replaced
    with `--force`, while a claim that may be live must not be, and telling an operator to force it
    would destroy the very rows they are waiting on.

    **Stated as a claim, not as liveness.** The old message said the run "is already running" and
    printed a pid nothing had interrogated. Inside the heartbeat window a killed run and an
    executing one are indistinguishable by construction, and that window is exactly when an
    operator retries after a Ctrl-C, a CI timeout or an OOM kill. So the message says what is
    known -- a lock, its age, and when it releases itself -- and `releases_in` is carried so the
    remedy that actually costs nothing can be named (`docs/issues/037`).
    """

    def __init__(self, run_id: str, directory: Path, claim: LockClaim) -> None:
        self.run_id = run_id
        self.directory = directory
        self.claim = claim
        super().__init__(
            f"run {run_id!r} holds a lock at {directory} last refreshed {claim.age:.0f}s ago "
            f"(pid {claim.pid}); a live run refreshes it continuously, and an abandoned one is "
            f"released automatically about {claim.releases_in:.0f}s from now. Wait; an "
            "abandoned record is removed with `vqapr rm strategy` once its lock has aged out"
        )


class RunRecordTaken(RuntimeError):
    """This run's id was taken over by another run before it could finish.

    Only reachable when someone forces an id that is already in use: the forcing run clears the
    directory this one is still writing into. The rows are gone either way -- what this changes is
    that the losing run SAYS so, instead of surfacing a raw `PermissionError` from deep inside
    `finish` that reads like a framework failure.
    """

    def __init__(self, run_id: str, directory: Path) -> None:
        self.run_id = run_id
        self.directory = directory
        super().__init__(
            f"run {run_id!r} lost its record directory at {directory} while finishing; "
            "another run claimed the same record. Re-run once the other writer has finished"
        )


class RunRecordExists(FileExistsError):
    """A run id already holds a record, and this run was not told to replace it.

    Its own type so the CLI can render it as a structured refusal naming the `--force` flag. A
    bare `FileExistsError` surfaces as `stage: "unhandled"`, which tells an agent the framework
    broke when the truth is that it chose a run id twice.
    """

    def __init__(self, run_id: str, directory: Path) -> None:
        self.run_id = run_id
        self.directory = directory
        super().__init__(f"run record {run_id!r} already exists at {directory}")


@dataclass(slots=True)
class _Buffer:
    """What a writer holds in memory between `append` and the end of the run."""

    tables: dict[str, list[pa.Table]] = field(default_factory=dict)
    nbytes: int = 0
    last_event_time: datetime | None = None
    progress_written_at: float | None = None
    occurrences: set[str] = field(default_factory=set)


def _unified_schema(schemas: Sequence[pa.Schema]) -> pa.Schema:
    """One schema for several chunks of one table: each column typed by the first chunk that
    typed it, its metadata (the Decimal marker) with it; a column no chunk typed stays null."""
    fields: dict[str, pa.Field] = {}
    for schema in schemas:
        for column in schema:
            known = fields.get(column.name)
            if known is None or (
                pa.types.is_null(known.type) and not pa.types.is_null(column.type)
            ):
                fields[column.name] = column
    return pa.schema(list(fields.values()))


def _conform(table: pa.Table, schema: pa.Schema) -> pa.Table:
    """One chunk in the unified schema: columns it lacks are null, columns it typed as null
    are cast, and a timestamp recorded in another zone is the same instant in the unified one."""
    arrays = []
    for column in schema:
        if column.name in table.column_names:
            arrays.append(table.column(column.name).cast(column.type))
        else:
            arrays.append(pa.nulls(table.num_rows, type=column.type))
    return pa.Table.from_arrays(arrays, schema=schema)


def _write_parquet(tables: Sequence[pa.Table], target: Path) -> None:
    """Several chunks as one complete file, written beside the target and moved into place, so a
    reader listing the directory never opens a file whose footer is not there yet."""
    schema = _unified_schema([table.schema for table in tables])
    joined = pa.concat_tables([_conform(table, schema) for table in tables])
    staging = target.with_name(f".{target.name}.tmp")
    pq.write_table(joined, staging, compression="zstd")
    os.replace(staging, target)


@dataclass(frozen=True, slots=True)
class RunRecordWriter:
    """Appends one run's rows and facts, inside that run's own directory.

    Holds no lock and shares no file with any other run, which is what lets five of these run at
    once without coordinating.
    """

    root: Path
    run_id: str
    strategy_ref: str | None = None
    """Which member of the run this writer records, as `<id>@<fp8>`, or `None` for the run
    directory itself -- a materialization record, or a run record written before `139`."""
    member_kind: str = STRATEGY_KIND
    """Which kind of member `strategy_ref` names (record `148`): a strategy or a datamodel."""
    spill_bytes: int = SPILL_BYTES
    """Buffered Arrow bytes above which a spill part is written; a test lowers it to force one."""
    _buffer: _Buffer = field(default_factory=_Buffer, init=False, repr=False, compare=False)
    _rows: dict[str, int] = field(default_factory=dict, init=False, repr=False, compare=False)
    _instants: dict[str, set[str]] = field(
        default_factory=dict, init=False, repr=False, compare=False
    )
    _fields: dict[str, dict[str, pa.Field]] = field(
        default_factory=dict, init=False, repr=False, compare=False
    )
    _parts: dict[str, int] = field(default_factory=dict, init=False, repr=False, compare=False)
    """What this writer has appended so far, per table: rows, and the distinct `event_time`s.

    Counted as chunks pass through `append`, so the record's `tables` block is right whether the
    run streamed its rows occurrence by occurrence or handed them over once at the end -- and so
    nothing has to hold the rows to count them. A set of instants is bounded by the run's
    instants, not its rows.
    """

    @property
    def directory(self) -> Path:
        return record_directory(self.root, self.run_id, self.strategy_ref, kind=self.member_kind)

    @property
    def label(self) -> str:
        """How this record is named in a refusal: the run id, or `<run>/<strategy_ref>`."""
        return self.run_id if self.strategy_ref is None else f"{self.run_id}/{self.strategy_ref}"

    @property
    def record_filename(self) -> str:
        return RECORD_FILENAME if self.strategy_ref is None else MEMBER_KINDS[self.member_kind][1]

    def counts(self) -> dict[str, dict[str, int]]:
        """Per table: rows appended so far, and the distinct instants they span."""
        return {
            table_id: {"rows": self._rows[table_id], "instants": len(self._instants[table_id])}
            for table_id in sorted(self._rows)
        }

    def open(self, *, replace: bool = False) -> None:
        """Create this run's directory, refusing to write into one that already exists.

        A second run under an existing id would interleave its rows with the first run's, and the
        result would be a record that is not either run. Refusing here is the same rule
        materialization applies to a published output: one producer, one artifact.

        `replace` is the deliberate override, and it is off by default for a measured reason: in a
        five-process factor loop a repeated run to the same id is far more often a retry than an
        intended overwrite, and an accidental clobber is unrecoverable while a refusal costs one
        flag. Replacing removes the old directory outright rather than merging into it, because a
        merge is exactly the interleaved record this refuses to produce.

        What counts as "already exists" is the RECORD, not the directory. A run killed partway
        leaves its rows and no `record.json`, and every reader here already calls that not-a-run:
        `run_ids` omits it, `read_record` refuses it. Refusing on the directory made the writer
        stricter than its own readers, so the obvious retry of a crashed run was blocked and the
        operator was routed to `--force` -- to delete a dead partial that no reader would ever
        have returned. A retry now simply overwrites it, which is what a retry means.

        `--force` is about a DEAD claim, never a live one. That distinction is the whole design,
        and getting it wrong is not a race: two terminals reproduce it deterministically. Run A
        holds an id and is appending; the operator forces the same id; B removes A's directory and
        creates its own; A's next append re-resolves the path -- `append` opens and closes per
        chunk and holds nothing -- and writes into B's. Both finish into one `record.json`, and
        `run_ids` then lists one complete run whose tables hold two runs' rows. Measured directly:
        rows came back `['B1', 'A2']`.

        So liveness is what is checked, using the lock this repository already uses for the
        workspace (`workspace.py:987`): `O_CREAT | O_EXCL` succeeds for exactly one process on
        Windows and POSIX alike, the holder's pid rides inside it, and a lock older than
        `LOCK_STALE_AFTER` belongs to a run that died. A live id is refused even under `--force`; a
        stale one is reclaimed.

        That also dissolves the cost the previous design accepted. A crashed run's lock is stale,
        so an ordinary retry reclaims its id with no flag at all -- the operator is not charged for
        someone else's crash.
        """
        directory = self.directory
        try:
            self._open(directory, replace=replace)
        except (RunRecordLive, RunRecordExists):
            raise
        except OSError as failure:
            # ONE boundary for every filesystem outcome CONTENTION can produce. Contending for an
            # id is not one error: it is `FileExistsError` when a directory is already there,
            # `PermissionError` (WinError 5 or 32) when another process holds a file open,
            # or a sharing violation when another process holds a file open. They mean the same
            # thing -- somebody else is working on this id -- and each one that escapes surfaces
            # as `stage: "unhandled"`, telling an agent the framework broke when two runs merely
            # collided. Handling them one at a time is what kept this failing: each fix moved the
            # error to the next call in the sequence.
            #
            # A mid-scan `FileNotFoundError` is deliberately NOT in that set: nothing in this
            # module removes the run directory itself, so its absence means something outside did
            # -- an operator, a tmp cleaner, a container teardown -- which is an environment
            # failure and stays loud.
            #
            # But the boundary is SCOPED, because an unscoped one is worse than what it replaced.
            # A full disk, a read-only mount or a bad store path would otherwise be reported as a
            # taken run id, and the remedy that refusal advertises -- pick another id, or --force
            # -- cannot fix any of them. An agent would cycle through ids, escalate to a
            # destructive flag, and never learn the store is unwritable. `stage: "unhandled"` at
            # least carries the errno; a confident wrong diagnosis carries nothing.
            #
            # Contention presupposes that somebody else created the directory. If it is not there,
            # nobody is competing and this is an environment failure that must stay loud.
            if failure.errno in _ENVIRONMENT_ERRNOS or not directory.exists():
                raise
            if failure.errno in _AMBIGUOUS_ERRNOS:
                # On Windows these cover both a permission problem and a sharing violation. The
                # lock answers which: a live holder means genuine contention, and naming the pid
                # is the more useful refusal anyway. No holder means the directory is simply not
                # writable, and reporting that as a taken id would advertise remedies -- another
                # id, or `--force` -- that cannot fix an ACL.
                claim = _lock_claim(directory / LOCK_FILENAME)
                if claim is None:
                    raise
                raise RunRecordLive(self.label, directory, claim) from failure
            raise RunRecordExists(self.label, directory) from failure

    def _open(self, directory: Path, *, replace: bool) -> None:
        """Claim the id, or raise. Every raise here is turned into a refusal by `open`.

        The directory create is the claim: `mkdir` without `exist_ok` succeeds for exactly one
        process and raises for every other. A narrow window remains between it and the lock write
        -- see the note at the recovery branch below -- which is documented rather than closed,
        because two attempts to close it by reordering both made the race MORE frequent, not less.
        """
        try:
            (directory / TABLES_DIRECTORY).mkdir(parents=True)
        except FileExistsError as taken:
            claim = _lock_claim(directory / LOCK_FILENAME)
            if claim is not None:
                # Somebody may be running under this id right now. `--force` does not override
                # this: forcing a live run destroys the rows it is still writing and blends both
                # into one record, which is unrecoverable, while waiting costs nothing -- at most
                # `claim.releases_in` seconds, after which a dead claim clears itself.
                raise RunRecordLive(self.label, directory, claim) from taken

            # Nobody live holds it. A COMPLETE record is a real conflict and still needs `--force`
            # -- replacing a finished result must stay deliberate. Abandoned leftovers are not:
            # the run that made them is dead, no reader ever returned them, and charging the
            # operator a destructive flag to clear someone else's crash is a cost with no benefit.
            if (directory / self.record_filename).is_file() and not replace:
                raise RunRecordExists(self.label, directory) from taken

            # Recovery contends on the LOCK rather than the directory, which is what stopped
            # several processes each clearing the same dead directory and each writing into it --
            # measured as a surviving record holding `['1', '2', '3']`.
            #
            # Recovery contends on the LOCK rather than the directory, which is what stopped
            # several processes each clearing the same dead directory and each writing into it --
            # measured as a surviving record holding `['1', '2', '3']`.
            #
            # Stated precisely, because the stronger claim is tempting and false: this serialises
            # against every process that has not yet passed its own liveness read, NOT against all
            # of them. A peer whose `_lock_claim` read landed before this run's `_claim` can still
            # take the id too. The window is microseconds wide and needs two processes reclaiming
            # the SAME id at once.
            #
            # KNOWN, MEASURED, AND NOT CLOSED. It produced two winners once in a full-suite run
            # and zero times in ten isolated runs. Two attempts to close it -- replacing the stale
            # lock atomically, then reordering so the lock precedes the directory -- each made the
            # race MORE frequent (9/12 and 12/12 failures), so both were reverted. A rare blend
            # that is documented beats a frequent one introduced while fixing it.
            with suppress(OSError):
                (directory / LOCK_FILENAME).unlink()
            self._claim()
            self._clear(directory)
            return

        self._claim()

    def _clear(self, directory: Path) -> None:
        """Remove a dead run's leftovers, having already won this id's lock."""
        for stale in directory.iterdir():
            # Never any lock file: this run holds its own, and a loser may have one open to read
            # its holder.
            if stale.name.startswith(LOCK_FILENAME):
                continue
            if stale.is_dir():
                shutil.rmtree(stale, ignore_errors=True)
            else:
                # A leftover this run could not remove is not a reason to fail: it holds the lock,
                # so the id is its own, and its own record will replace whatever survived.
                with suppress(OSError):
                    stale.unlink()
        (directory / TABLES_DIRECTORY).mkdir(exist_ok=True)

    def heartbeat(self) -> None:
        """Mark this run as still alive, and every `PROGRESS_EVERY` seconds say how far it got.

        Never raises: a lock that cannot be touched right now -- a peer reading it, a filesystem
        with coarse timestamps -- must not fail a run that is otherwise fine. The next occurrence
        tries again, and occurrences arrive far more often than the stale window.
        """
        with suppress(OSError):
            os.utime(self.directory / LOCK_FILENAME, None)
        written = self._buffer.progress_written_at
        if written is None or _time.monotonic() - written >= PROGRESS_EVERY:
            self.checkpoint()

    def checkpoint(self) -> None:
        """Write `progress.json` now: what `list strategies --run` shows for a running member.

        Never raises, for the heartbeat's reason. Rows stay in memory (`087`); this is the one
        thing about a running member that reaches the disk before the end.
        """
        self._buffer.progress_written_at = _time.monotonic()
        last = self._buffer.last_event_time
        payload = json.dumps(
            {
                "occurrences": len(self._buffer.occurrences),
                "rows": dict(sorted(self._rows.items())),
                "last_event_time": None if last is None else last.isoformat(),
            },
            sort_keys=True,
        )
        with suppress(OSError):
            atomic.write_atomically(
                self.directory / PROGRESS_FILENAME, payload + "\n", create_parent=False
            )

    def _spill(self) -> None:
        """Write everything buffered as one spill part per table; the safety valve."""
        for table_id, tables in self._buffer.tables.items():
            if not tables:
                continue
            directory = self.directory / TABLES_DIRECTORY / table_id
            directory.mkdir(parents=True, exist_ok=True)
            part = self._parts.get(table_id, 0)
            _write_parquet(tables, directory / f"{part:06d}{PART_SUFFIX}")
            self._parts[table_id] = part + 1
        self._buffer.tables.clear()
        self._buffer.nbytes = 0

    def _seal(self) -> None:
        """Every table as `all.parquet`: what is buffered, after whatever was spilled.

        Written before the record and before the lock goes, on the success path and the failure
        path alike. Spill parts are removed only once the compact file is in place, and a reader
        prefers the compact file, so a crash in between loses nothing and repeats nothing.
        """
        for table_id in sorted(set(self._buffer.tables) | set(self._parts)):
            directory = self.directory / TABLES_DIRECTORY / table_id
            parts = sorted(directory.glob(f"[0-9]*{PART_SUFFIX}")) if directory.is_dir() else []
            tables = [pq.read_table(part) for part in parts] + self._buffer.tables.get(table_id, [])
            if not tables:
                continue
            directory.mkdir(parents=True, exist_ok=True)
            _write_parquet(tables, directory / COMPACT_FILENAME)
            for part in parts:
                part.unlink()
        self._buffer.tables.clear()
        self._buffer.nbytes = 0
        with suppress(OSError):
            (self.directory / PROGRESS_FILENAME).unlink(missing_ok=True)

    def _claim(self) -> None:
        """Mark this run as live, so a concurrent `--force` refuses instead of destroying it.

        `O_CREAT | O_EXCL` succeeds for exactly one process and raises for every other, on Windows
        and POSIX alike.
        """
        lock = self.directory / LOCK_FILENAME
        handle = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        try:
            os.write(handle, str(os.getpid()).encode("ascii"))
        finally:
            os.close(handle)

    def release(self) -> None:
        """End this run's writing: its tables land, then its liveness claim goes.

        Called from `finish` and from the failure path of a run that is already ending. The
        rows are written here on BOTH paths (`087`): a strategy that raised, or was interrupted,
        keeps every row it recorded, beside no record -- `list strategies --run` shows it as
        `unfinished`. A table that cannot be written raises, on the failure path too, chained on
        the failure that ended the run: losing the rows silently would be the worse outcome.
        """
        try:
            self._seal()
        finally:
            self._unlock()

    def _unlock(self) -> None:
        """Drop the liveness claim. Never raises: a lock that cannot be removed right now --
        because a peer has it open to read the holder, which on Windows raises rather than waiting
        -- is not a reason to fail a run that otherwise succeeded. The lock ages out on its own."""
        with suppress(OSError):
            (self.directory / LOCK_FILENAME).unlink(missing_ok=True)

    def append(self, table_id: str, rows: Sequence[Mapping[str, object]]) -> None:
        """Take one chunk of one table into memory, typed; it reaches the disk when the run ends.

        Takes a chunk at a time so a caller CAN stream as it produces rows, and a run with a
        store does: each accepted occurrence's rows arrive here at publish. The chunk is turned
        into an Arrow table at once -- a column of two kinds is refused at the occurrence that
        wrote it, by name, and a columnar buffer is a fraction of the rows' size as Python
        objects -- and written only by `release`, or by `_spill` above `spill_bytes`.

        Also the run's heartbeat. `LOCK_STALE_AFTER` asks whether the holder is still alive, and
        without a refresh the answer is really "has this run been going longer than two minutes" --
        true of every real run here, which would let any peer take a live id.
        """
        if not rows:
            self.heartbeat()
            return
        table = _arrow_table(rows, table_id, self._fields.setdefault(table_id, {}))
        buffered = self._buffer.tables.setdefault(table_id, [])
        buffered.append(table)
        self._buffer.nbytes += table.nbytes
        instants = self._instants.setdefault(table_id, set())
        for row in rows:
            at = row.get("event_time")
            instants.add(str(at))
            if isinstance(at, datetime):
                self._buffer.occurrences.add(str(at))
                last = self._buffer.last_event_time
                if last is None or at > last:
                    self._buffer.last_event_time = at
        self._rows[table_id] = self._rows.get(table_id, 0) + len(rows)
        self.heartbeat()
        if self._buffer.nbytes >= self.spill_bytes:
            self._spill()

    def finish(self, record: _Record | Mapping[str, object], *, kind: str = RUN_KIND) -> Path:
        """Write the run's own facts, last, by atomic replace.

        Last because `record.json` existing is what makes the record complete: a reader that finds
        one knows the run reached its end. Atomically because a half-written record read by a cold
        process is indistinguishable from a run that recorded half its facts.

        `kind` defaults to `RUN_KIND`, the run directory's own record; a member writer passes its
        kind (record `148`: a strategy or a datamodel).
        """
        if kind not in RECORD_FIELDS_BY_KIND:
            raise KeyError(
                f"unknown run-record kind {kind!r}; known kinds are "
                f"{', '.join(sorted(RECORD_FIELDS_BY_KIND))}"
            )
        directory = self.directory
        if (kind in MEMBER_KINDS) != (self.strategy_ref is not None):
            raise ValueError(
                "a member record is written by a writer with a strategy_ref, and only by one"
            )
        if self.strategy_ref is not None and kind != self.member_kind:
            raise ValueError(f"this writer records a {self.member_kind}, not a {kind}")
        head: dict[str, object] = {
            "schema": MEMBER_KINDS[kind][2] if kind in MEMBER_KINDS else SCHEMA,
            # The discriminator, written before the answers so a reader scanning the head of
            # the file knows what it is holding. Record `115`.
            "kind": kind,
            "run_id": self.run_id,
        }
        if self.strategy_ref is not None:
            head[MEMBER_KINDS[kind][3]] = self.strategy_ref
        body = record.as_record() if isinstance(record, _Record) else dict(record)
        # The head stamps `run_id` and the member ref itself; a model carries them as fields, so
        # they are dropped here rather than written twice.
        for stamped in ("run_id", *(MEMBER_KINDS[kind][3:] if kind in MEMBER_KINDS else ())):
            body.pop(stamped, None)
        payload = json.dumps({**head, **_encode_mapping(body)}, indent=2, sort_keys=True)
        # The tables land BEFORE the record: the record existing is what says the run is
        # complete, and a reader that finds one must find every row beside it.
        self._seal()

        def taken(_error: OSError) -> BaseException:
            # The directory is no longer there, or no longer ours. Another run took this id while
            # this one was executing -- only possible when someone forced an id already in use --
            # and this run's rows went with it. Saying so beats an unhandled OSError that reads
            # like the framework broke.
            return RunRecordTaken(self.label, directory)

        # `create_parent=False` is load-bearing: the directory's ABSENCE is how this detects a
        # stolen run id. Recreating it would turn the detection into a silent re-claim of state
        # another run now owns.
        atomic.write_atomically(
            directory / self.record_filename,
            payload + "\n",
            on_error=taken,
            create_parent=False,
        )
        # The run is over, so it is no longer live. Released after the record lands, never before:
        # a reader that sees a complete record must never also see a live claim on it.
        self._unlock()
        return directory / self.record_filename


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


class RunRecordConflict(ValueError):
    """`run.json` already exists under this id and describes a different configuration.

    The strategy records beneath it belong to that configuration. Running a changed run under the
    same id would file new output beside old output that a reader could no longer tell apart, so
    the refusal names both digests; `vqapr rm run <id>` clears the old, or a new id keeps both.
    """

    def __init__(self, run_id: str, path: Path, existing: object, declared: str) -> None:
        self.run_id = run_id
        self.path = path
        self.existing = existing
        self.declared = declared
        super().__init__(
            f"run {run_id!r} already has records under configuration {existing!r} at {path}, "
            f"and this run freezes to {declared!r}; remove the old records with "
            f"`vqapr rm run {run_id}`, or register the changed run under a new id"
        )


def write_run_record(root: Path, run_id: str, record: RunRecord | Mapping[str, object]) -> Path:
    """Write `run.json`, the configuration every strategy of this run shares.

    Idempotent for the same configuration -- every process running a strategy of this run writes
    the same bytes, so no lock is needed -- and refused for a different one (`RunRecordConflict`).
    """
    path = run_record_path(root, run_id)
    body = record.as_record() if isinstance(record, _Record) else dict(record)
    body.pop("run_id", None)
    declared = str(body.get("declared_digest"))
    if path.is_file():
        existing = read_run_record(root, run_id)
        if str(existing.get("declared_digest")) != declared:
            raise RunRecordConflict(run_id, path, existing.get("declared_digest"), declared)
    payload = json.dumps(
        {"schema": RUN_SCHEMA, "kind": RUN_KIND, "run_id": run_id, **_encode_mapping(body)},
        indent=2,
        sort_keys=True,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic.write_atomically(path, payload + "\n")
    return path


def run_ids(root: Path) -> tuple[str, ...]:
    """Every run this root holds a record for, sorted.

    Derived by scanning rather than read from an index, so no two runs share a mutable target. A
    run directory holds `run.json` (record `139`) or, for a run written before `139`,
    `record.json`; a directory with neither did not get as far as a record.
    """
    directory = root / RUNS_DIRECTORY
    if not directory.is_dir():
        return ()
    return tuple(
        sorted(
            child.name
            for child in directory.iterdir()
            if child.is_dir()
            and ((child / RUN_FILENAME).is_file() or (child / RECORD_FILENAME).is_file())
        )
    )


def strategy_refs(root: Path, run_id: str) -> tuple[str, ...]:
    """Every FINISHED strategy record this run holds, as `<id>@<fp8>`, sorted.

    A strategy directory without `strategy.json` is still being written, or was killed or
    refused before it finished; omitted here, exactly as `run_ids` omits an unfinished run.
    `unfinished_strategy_refs` lists those, and `strategy_progress` says what state they are in.
    """
    directory = root / RUNS_DIRECTORY / run_id / STRATEGIES_DIRECTORY
    if not directory.is_dir():
        return ()
    return tuple(
        sorted(
            child.name
            for child in directory.iterdir()
            if child.is_dir() and (child / STRATEGY_FILENAME).is_file()
        )
    )


STATUS_COMPLETED = "completed"
STATUS_RUNNING = "running"
STATUS_UNFINISHED = "unfinished"
"""What a strategy directory says about its run. `completed` has `strategy.json`; `running` has
none and a lock touched inside `LOCK_STALE_AFTER`; `unfinished` has none and a lock that is stale
or gone -- a strategy that was killed, or whose flow ended in a refusal, both of which leave rows
and no record. The two cannot be told apart from the directory; the run envelope is where a
refusal is reported (`docs/issues/073`, `074`)."""


def unfinished_strategy_refs(root: Path, run_id: str) -> tuple[str, ...]:
    """Every strategy directory of this run WITHOUT `strategy.json`, as `<id>@<fp8>`, sorted.

    The complement of `strategy_refs`. A long run used to be invisible from the surface between
    its first accepted session and its record (`docs/issues/074`): `list` showed a record only
    once it was finished, so an author counted parquet files by hand to learn whether a strategy
    was still advancing.
    """
    return unfinished_member_refs(root, run_id, kind=STRATEGY_KIND)


def unfinished_datamodel_refs(root: Path, run_id: str) -> tuple[str, ...]:
    """Every datamodel directory of this run WITHOUT `datamodel.json`, as `<id>@<fp8>`, sorted.

    The datamodel side of `074`. Record `148` gave datamodels `datamodel_refs` and neither of the
    other two, so a datamodel run that died inside a callback left a directory nothing listed and
    nothing could name (`docs/issues/080`) -- and the skill's "count the directories" then
    over-counted a model's tunings by its crashes.
    """
    return unfinished_member_refs(root, run_id, kind=DATAMODEL_KIND)


def unfinished_member_refs(root: Path, run_id: str, *, kind: str) -> tuple[str, ...]:
    """Every member directory of `kind` without its record file, as `<id>@<fp8>`, sorted."""
    members, filename, _, _ = MEMBER_KINDS[kind]
    directory = root / RUNS_DIRECTORY / run_id / members
    if not directory.is_dir():
        return ()
    return tuple(
        sorted(
            child.name
            for child in directory.iterdir()
            if child.is_dir() and not (child / filename).is_file()
        )
    )


def recorded_run_ids(root: Path) -> tuple[str, ...]:
    """Every run this root holds ANY trace of: a run record, or a member directory of either kind.

    `run_ids` is the finished set. This is the wider one `list runs` needs (`docs/issues/081`):
    a run whose definition was withdrawn still has records, and a run that was killed before its
    run record still has member directories, and both are findable only from here.
    """
    directory = root / RUNS_DIRECTORY
    if not directory.is_dir():
        return ()
    found: set[str] = set(run_ids(root))
    for child in directory.iterdir():
        if not child.is_dir():
            continue
        for members, _, _, _ in MEMBER_KINDS.values():
            member_dir = child / members
            if member_dir.is_dir() and any(item.is_dir() for item in member_dir.iterdir()):
                found.add(child.name)
                break
    return tuple(sorted(found))


def strategy_progress(root: Path, run_id: str, strategy_ref: str) -> dict[str, Any]:
    """What an unfinished strategy directory says about how far its run got. See
    `member_progress`."""
    return member_progress(root, run_id, strategy_ref, kind=STRATEGY_KIND)


def datamodel_progress(root: Path, run_id: str, datamodel_ref: str) -> dict[str, Any]:
    """What an unfinished datamodel directory says about how far its run got (`080`)."""
    return member_progress(root, run_id, datamodel_ref, kind=DATAMODEL_KIND)


def member_progress(root: Path, run_id: str, ref: str, *, kind: str) -> dict[str, Any]:
    """What an unfinished member directory says about how far its run got.

    `status` is `running` or `unfinished` (see `STATUS_*`). `lock` is the holder's pid and how
    many seconds ago the run last touched its lock, or `None`. The rest comes from
    `progress.json`, which the heartbeat rewrites every `PROGRESS_EVERY` seconds while the rows
    are still in memory (`087`): `chunks` is the accepted occurrences so far (the name it had when
    it counted part files, kept for the CLI), `tables` names the tables with rows, and
    `last_event_time` is the last instant the run accepted. A directory with no progress file --
    a member that ended before its first heartbeat, or one hard-killed after a spill -- falls back
    to what its files say: one part per spill, and the newest instant in the newest one.
    """
    directory = record_directory(root, run_id, ref, kind=kind)
    claim = _lock_claim(directory / LOCK_FILENAME)
    progress = directory / PROGRESS_FILENAME
    if progress.is_file():
        try:
            said = json.loads(progress.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            said = {}
        if isinstance(said, dict):
            rows = said.get("rows") or {}
            return {
                "status": STATUS_RUNNING if claim is not None else STATUS_UNFINISHED,
                "lock": (
                    None
                    if claim is None
                    else {"pid": claim.pid, "refreshed_ago": round(claim.age, 1)}
                ),
                "chunks": int(said.get("occurrences") or 0),
                "tables": sorted(rows) if isinstance(rows, dict) else [],
                "last_event_time": said.get("last_event_time"),
            }
    tables = directory / TABLES_DIRECTORY
    parts: dict[str, tuple[Path, ...]] = {}
    if tables.is_dir():
        for table in sorted(child for child in tables.iterdir() if child.is_dir()):
            parts[table.name] = _table_files(table)
    newest: datetime | None = None
    for files in parts.values():
        if not files:
            continue
        last = _newest_event_time(files[-1])
        if last is not None and (newest is None or last > newest):
            newest = last
    return {
        "status": STATUS_RUNNING if claim is not None else STATUS_UNFINISHED,
        "lock": None if claim is None else {"pid": claim.pid, "refreshed_ago": round(claim.age, 1)},
        "chunks": max((len(files) for files in parts.values()), default=0),
        "tables": sorted(parts),
        "last_event_time": None if newest is None else newest.isoformat(),
    }


def _newest_event_time(part: Path) -> datetime | None:
    """The latest `event_time` in one part file, or `None` when it has no such column or cannot
    be read -- a part being replaced under a reader is a state, not a failure."""
    try:
        table = pq.read_table(part, columns=["event_time"])
    except (OSError, pa.ArrowException, KeyError):
        return None
    if table.num_rows == 0:
        return None
    # pyarrow.compute binds its kernels at import time, so the stubs do not list `max`.
    value = pc.max(table.column("event_time")).as_py()  # type: ignore[attr-defined]
    return value if isinstance(value, datetime) else None


def read_run_record(root: Path, run_id: str) -> dict[str, Any]:
    """`run.json` -- or, for a record written before `139`, `record.json`."""
    path = run_record_path(root, run_id)
    if not path.is_file():
        return read_record(root, run_id)
    record = _mapping_at(path)
    written = record.get("schema")
    if written != RUN_SCHEMA:
        raise ValueError(
            f"run record at {path} declares schema {written!r}; this version reads {RUN_SCHEMA!r}"
        )
    return record


def datamodel_refs(root: Path, run_id: str) -> tuple[str, ...]:
    """Every datamodel record this run holds, as `<id>@<fp8>`, sorted (record `148`)."""
    directory = root / RUNS_DIRECTORY / run_id / DATAMODELS_DIRECTORY
    if not directory.is_dir():
        return ()
    return tuple(
        sorted(
            child.name
            for child in directory.iterdir()
            if child.is_dir() and (child / DATAMODEL_FILENAME).is_file()
        )
    )


def read_strategy_record(root: Path, run_id: str, strategy_ref: str) -> dict[str, Any]:
    """One strategy's frozen facts, exactly as they were written."""
    return read_member_record(root, run_id, strategy_ref, kind=STRATEGY_KIND)


def read_datamodel_record(root: Path, run_id: str, datamodel_ref: str) -> dict[str, Any]:
    """One datamodel's frozen facts, exactly as they were written (record `148`)."""
    return read_member_record(root, run_id, datamodel_ref, kind=DATAMODEL_KIND)


def read_member_record(root: Path, run_id: str, ref: str, *, kind: str) -> dict[str, Any]:
    _, filename, schema, _ = MEMBER_KINDS[kind]
    path = record_directory(root, run_id, ref, kind=kind) / filename
    if not path.is_file():
        known = (
            strategy_refs(root, run_id) if kind == STRATEGY_KIND else datamodel_refs(root, run_id)
        )
        raise FileNotFoundError(
            f"no complete {kind} record for {run_id!r}/{ref!r} at {path}; "
            f"known: {', '.join(known) or '(none)'}"
        )
    record = _mapping_at(path)
    written = record.get("schema")
    if written != schema:
        raise ValueError(
            f"{kind} record at {path} declares schema {written!r}; this version reads {schema!r}"
        )
    return record


def _mapping_at(path: Path) -> dict[str, Any]:
    record = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(record, dict):
        raise ValueError(
            f"record at {path} is valid JSON but not a mapping (found {type(record).__name__}); "
            "the file is corrupt and must be regenerated or removed"
        )
    return record


def remove_strategy_record(
    root: Path, run_id: str, strategy_ref: str, *, kind: str = STRATEGY_KIND
) -> bool:
    """Remove one member's record directory, refusing while its lock is inside the window.

    Returns False when there was nothing to remove. `RunRecordLive` when a writer may still be
    running: the rows it is writing are the thing a deletion would destroy, and the lock ages out
    on its own.
    """
    directory = record_directory(root, run_id, strategy_ref, kind=kind)
    if not directory.is_dir():
        return False
    claim = _lock_claim(directory / LOCK_FILENAME)
    if claim is not None:
        raise RunRecordLive(f"{run_id}/{strategy_ref}", directory, claim)
    shutil.rmtree(directory)
    return True


def remove_run_record(root: Path, run_id: str, *, keep_latest: bool = False) -> tuple[str, ...]:
    """Remove a run's records: every strategy directory, then the run directory itself.

    With `keep_latest`, the newest record of each strategy id stays and the run directory with it;
    older fingerprints of the same strategy go. Every live lock is checked BEFORE anything is
    removed, so a refusal leaves the run as it was. Returns what was removed, as
    `<strategy_ref>` entries plus `run.json`/`record.json` when the directory went.
    """
    directory = root / RUNS_DIRECTORY / run_id
    if not directory.is_dir():
        return ()
    candidates = tuple(
        child
        for members in (directory / STRATEGIES_DIRECTORY, directory / DATAMODELS_DIRECTORY)
        if members.is_dir()
        for child in sorted(child for child in members.iterdir() if child.is_dir())
    )
    for child in (*candidates, directory):
        claim = _lock_claim(child / LOCK_FILENAME)
        if claim is not None:
            label = run_id if child is directory else f"{run_id}/{child.name}"
            raise RunRecordLive(label, child, claim)
    kept: set[Path] = set()
    if keep_latest:
        newest: dict[str, Path] = {}
        for child in candidates:
            strategy_id = child.name.rsplit("@", 1)[0]
            current = newest.get(strategy_id)
            if current is None or child.stat().st_mtime > current.stat().st_mtime:
                newest[strategy_id] = child
        kept = set(newest.values())
    removed: list[str] = []
    for child in candidates:
        if child in kept:
            continue
        shutil.rmtree(child)
        removed.append(child.name)
    if not kept:
        shutil.rmtree(directory)
        removed.append(RUN_FILENAME if (directory / RUN_FILENAME).exists() else RECORD_FILENAME)
        return tuple(removed)
    return tuple(removed)


def _require_known_schema(record: Mapping[str, Any], path: Path) -> None:
    """Refuse a record written by a future version, loudly, before anything reads its fields.

    **This did not exist, and its absence made a documented property untrue.** `read_record`
    returned `json.loads` with no schema branch, and `cli/show.py` reads every field with
    `record.get(field)`. So a reverted reader handed a new-shape record did not refuse -- it
    rendered the fields it recognised and silently dropped the rest; and a new reader handed an old
    record rendered the new fields as `null`, indistinguishable from "this run genuinely had none".
    "A reverted reader refuses loudly" was assumed rather than implemented.

    Compares the MAJOR version only. A minor bump is for additive change a `.get` reader survives
    by design; a major bump means a field it thinks it understands may now mean something else,
    which is the case worth stopping for.
    """
    written = record.get("schema")
    if written == SCHEMA:
        return

    family, _, version = str(written or "").rpartition("/")
    expected_family, _, expected_version = SCHEMA.rpartition("/")
    if family == expected_family:
        major = version.lstrip("v").split(".")[0]
        expected_major = expected_version.lstrip("v").split(".")[0]
        if major.isdigit() and expected_major.isdigit() and int(major) <= int(expected_major):
            # An older major this reader still understands. `v1` records predate the `kind`
            # discriminator and are read as runs, which is what they are.
            return

    raise ValueError(
        f"run record at {path} declares schema {written!r}, which this version of vqapr does not "
        f"understand; it reads {SCHEMA!r} and older. Upgrade vqapr to read this record rather than "
        "reading it with a version that would render its unknown fields as null."
    )


def read_record(root: Path, run_id: str) -> dict[str, Any]:
    """One run's frozen facts, exactly as they were written."""
    path = record_path(root, run_id)
    if not path.is_file():
        raise FileNotFoundError(
            f"no complete run record for {run_id!r} at {path}; "
            f"known runs: {', '.join(run_ids(root)) or '(none)'}"
        )
    record = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(record, dict):
        # A file that parses as JSON but is not a mapping. Previously returned as-is, so a caller
        # doing `record["account"]` got a `TypeError` two frames from the corrupted file with
        # nothing naming it. `tests/qa/test_run_records_survive_and_race.py` pinned that behaviour
        # and said in the pin that adding a check would be an improvement. Record `115` adds it,
        # because the schema check below cannot run on a payload with no keys to read.
        raise ValueError(
            f"run record at {path} is valid JSON but not a mapping (found "
            f"{type(record).__name__}); the file is corrupt and must be regenerated or removed"
        )
    _require_known_schema(record, path)
    # `v1` records carry no discriminator and are runs by construction, so a reader can branch on
    # `kind` unconditionally without every call site re-deriving that.
    record.setdefault("kind", RUN_KIND)
    return record


class RunRecordMissing(ValueError):
    """No record where the caller pointed: the wrong root, run id or strategy ref.

    `docs/issues/057`. `read_table` returned an empty iterator for a root that was the project
    directory rather than its `.vqapr`, for a run id nothing had written, and for a `strategy_ref`
    that named no directory -- and the user's code failed three steps later on an empty frame. An
    empty TABLE is a fact about a run (a declared table nobody wrote); a missing RECORD is a
    wrong argument, and the refusal names the directory it looked in and what it found beside it.
    """


def resolve_strategy_ref(root: Path, run_id: str, strategy_ref: str | None) -> str | None:
    """The member directory a table read means, or a refusal that names what exists.

    `None` reads the run directory when that directory holds tables of its own (a record written
    before `139`, or a writer without a member); on a current record it resolves to the run's
    only strategy, and refuses -- listing them -- when there are several. A bare `<strategy-id>`
    resolves the way `vqapr show strategy <run>/<id>` does: to the one record of that strategy,
    refusing when there are several fingerprints to choose from.
    """
    run_directory = root / RUNS_DIRECTORY / run_id
    if not run_directory.is_dir():
        # Directories, not `run_ids()`: that lists FINISHED runs, and a reader pointed at the
        # wrong root is helped by seeing what is there, finished or not.
        runs = root / RUNS_DIRECTORY
        present = (
            sorted(child.name for child in runs.iterdir() if child.is_dir())
            if runs.is_dir()
            else []
        )
        raise RunRecordMissing(
            f"no run {run_id!r} under {runs}; run directories there: "
            f"{', '.join(present) or '(none)'}. The root is the `store_root` `vqapr run` prints "
            "(`<project>/.vqapr` by default), not the project directory"
        )
    # Every member directory, finished or not: a killed strategy leaves rows and no
    # `strategy.json`, and those rows are exactly what a reader comes back for.
    strategies = run_directory / STRATEGIES_DIRECTORY
    members = (
        tuple(sorted(child.name for child in strategies.iterdir() if child.is_dir()))
        if strategies.is_dir()
        else ()
    )
    if strategy_ref is None:
        if (run_directory / TABLES_DIRECTORY).is_dir():
            return None
        if len(members) == 1:
            return members[0]
        raise RunRecordMissing(
            f"run {run_id!r} at {run_directory} records "
            + (
                f"{len(members)} strategies ({', '.join(members)}); name one as strategy_ref"
                if members
                else "no strategy and no tables of its own"
            )
        )
    if (record_directory(root, run_id, strategy_ref)).is_dir():
        return strategy_ref
    matching = [ref for ref in members if ref.rsplit("@", 1)[0] == strategy_ref]
    if len(matching) == 1:
        return matching[0]
    raise RunRecordMissing(
        f"no strategy record {strategy_ref!r} under {run_directory / STRATEGIES_DIRECTORY}; "
        + (
            f"{strategy_ref!r} has {len(matching)} records: {', '.join(matching)}"
            if matching
            else f"recorded there: {', '.join(members) or '(none)'}"
        )
    )


def _parts(root: Path, run_id: str, table_id: str, strategy_ref: str | None) -> tuple[Path, ...]:
    resolved = resolve_strategy_ref(root, run_id, strategy_ref)
    directory = record_directory(root, run_id, resolved) / TABLES_DIRECTORY / table_id
    return _table_files(directory)


def _table_files(directory: Path) -> tuple[Path, ...]:
    """The files that ARE one table: `all.parquet` alone when the run ended, else the spill
    parts a still-running or hard-killed run left. Never both -- a compact file beside parts is
    a seal interrupted between its write and the parts' removal, and the parts are its input."""
    if not directory.is_dir():
        return ()
    compact = directory / COMPACT_FILENAME
    if compact.is_file():
        return (compact,)
    return tuple(sorted(path for path in directory.glob(f"[0-9]*{PART_SUFFIX}")))


def read_table(
    root: Path, run_id: str, table_id: str, strategy_ref: str | None = None
) -> Iterator[dict[str, Any]]:
    """Stream one table's rows back, a chunk at a time, as the values they were written from.

    `root` is the store: the `store_root` `vqapr run` prints, `<project>/.vqapr` unless
    `--store-root` moved it -- NOT the project directory. `run_id` and `strategy_ref`
    (`<strategy-id>@<fp8>`, or the bare `<strategy-id>` when one record of it exists, or `None`
    when the run holds one strategy) name a record that must exist: a root, run or ref that
    names nothing is refused with `RunRecordMissing`, naming what was found instead
    (`docs/issues/057`). A table the record declares but never wrote reads back empty.

    A generator because a run's tables are the large half of the record, and a caller counting
    rows should not have to hold all of them to do it. A `Decimal` comes back a `Decimal` and an
    instant an offset-aware `datetime` in the zone it was recorded in; the parquet carries both,
    so there is nothing to guess (record `146`).
    """
    for path in _parts(root, run_id, table_id, strategy_ref):
        try:
            reader = pq.ParquetFile(path)
        except (pa.ArrowInvalid, pa.ArrowException, OSError) as damaged:
            # A damaged chunk is reported, never skipped. Skipping would let `show run --table`
            # return a short table that looks complete, and a reader comparing it against the
            # record's own row count would find two numbers disagreeing with no reason given.
            raise ValueError(
                f"{path} is not a parquet file: {damaged}. The recorder wrote this file, so a "
                "file that does not open means it was edited or truncated; restore it, or "
                "re-run under a new run id"
            ) from damaged
        for batch in reader.iter_batches():
            yield from _python_rows(batch)


read_typed_table = read_table
"""The reader `vqapr.public` exports under the name it had when the sidecar existed. Typed by
construction now; kept so a caller written against record `135` reads on."""


def table_ids(root: Path, run_id: str, strategy_ref: str | None = None) -> tuple[str, ...]:
    resolved = resolve_strategy_ref(root, run_id, strategy_ref)
    directory = record_directory(root, run_id, resolved) / TABLES_DIRECTORY
    if not directory.is_dir():
        return ()
    return tuple(sorted(path.name for path in directory.iterdir() if path.is_dir()))


# ---------------------------------------------------------------------------------------------
# Freezing a run into its records, folded in from flow/records.py (one-shape Step 6, record 161).
# ---------------------------------------------------------------------------------------------


def freeze_run_record(root: Path, frozen: FrozenRun, *, source_digests: Mapping[str, str]) -> Path:
    """Write `run.json`: the configuration every strategy of this run shares.

    Written BEFORE any strategy runs, so a run killed midway still says what it attempted, and
    identical for every process that runs a strategy of this run -- which is why it needs no lock:
    two writers write the same bytes. A run whose configuration changed since a record was written
    under this id is refused by `write_run_record`, naming both digests.

    `source_digests` are the physical digests of the sources the run reads, keyed by source id:
    a registration keeps an id and a path, and nothing pinned the bytes behind them (A7).
    """
    execution = frozen.execution
    record = RunRecord(
        run_id=frozen.run_id,
        declared_digest=str(frozen.identity),
        instruments=list(frozen.instruments),
        period={"start": frozen.start, "end": frozen.end},
        exchange=(
            None
            if frozen.exchange is None
            else {
                "component_id": str(frozen.exchange.component_id),
                "fingerprint": frozen.exchange.fingerprint,
            }
        ),
        # `034` closes here: which convention this run filled under, in the record's own words.
        execution=(
            None
            if execution is None
            else {
                "dataset_id": str(execution.dataset_id),
                "source_id": str(execution.table.source.source_id),
                "trade_at_field": execution.table.trade_at_field,
                "price_fields": dict(execution.table.price_fields),
                "fill": {
                    "selector": execution.fill.selector.value,
                    "local_time": execution.fill.local_time.isoformat(),
                    "timezone": execution.fill.timezone,
                    "trade_price": execution.fill.trade_price,
                    "declaration_identity": execution.fill.declaration_identity,
                },
            }
        ),
        initial_account=(
            None
            if frozen.initial_account_snapshot is None or frozen.initial_account_mode is None
            else {
                "mode": frozen.initial_account_mode.value,
                "version": frozen.initial_account_snapshot.version,
                "cash": frozen.initial_account_snapshot.cash,
                "positions": dict(frozen.initial_account_snapshot.positions),
            }
        ),
        datasets=[
            {
                "dataset_id": str(dataset.dataset_id),
                "source_id": str(dataset.source),
                "grain": None if dataset.grain is None else dataset.grain.value,
                "source_digest": source_digests.get(str(dataset.source)),
            }
            for dataset in frozen.datasets
        ],
        strategies=[
            {"component_id": layer.component_id, "record": layer.record_ref}
            for layer in frozen.strategies
        ],
        # A run holds one kind (record `148`); the other list is empty, and stays in the record
        # so a reader never has to know which kind it is holding to ask.
        datamodels=[
            {
                "component_id": layer.component_id,
                "record": layer.record_ref,
                "dataset_id": layer.dataset_id,
            }
            for layer in frozen.datamodels
        ],
    )
    return write_run_record(root, frozen.run_id, record)


def freeze_strategy_record(
    writer: RunRecordWriter,
    result: SimulationResult,
    frozen: FrozenRun,
    layer: FrozenStrategy,
    as_loaded: Mapping[str, str],
    roster: dict[str, object] | None,
) -> None:
    """Write one strategy's rows and its own facts, so a later process can read them.

    The rows go first and the record last, because `strategy.json` existing is what marks the
    record complete. A reader that finds one knows the strategy reached its end; one killed midway
    leaves its rows and no record, which `strategy_refs` correctly declines to list as finished.
    """
    # A run with a store streams its rows to this writer as each occurrence is accepted, so
    # `recorder_rows` is empty here and everything is already on disk. A result assembled without
    # a sink still carries its rows, and they are appended now. Either way the writer counted what
    # it wrote, which is what the `tables` block below reports.
    recorded = result.final_state.recorder_rows
    for table_id, rows in sorted(recorded.items()):
        writer.append(table_id, rows)

    account = result.final_state.account
    snapshot = None if account is None else account.snapshot
    component = layer.config.component

    # The field set is the model's (one-shape Step 6): a field missing here is refused at
    # construction, and one this function names that the model does not is refused the same way
    # -- not a drift that reaches disk and waits to be noticed.
    record = StrategyRecord(
        run_id=writer.run_id,
        strategy_ref=str(writer.strategy_ref),
        strategy_id=layer.component_id,
        # The registered fingerprint, in full; the directory name carries its first eight.
        fingerprint=component.fingerprint,
        component={
            "component_id": layer.component_id,
            "path": str(component.path),
            "object_name": component.object_name,
            "config": dict(component.config),
            "fingerprint": component.fingerprint,
        },
        agenda={
            "agenda_id": str(layer.agenda.agenda_id),
            "content_identity": layer.agenda.content_identity,
            "occurrences": len(layer.agenda.occurrences),
        },
        constraints=[
            {"component_id": str(constraint.component_id), "fingerprint": constraint.fingerprint}
            for constraint in layer.constraints.constraints
        ],
        account=(
            None
            if snapshot is None
            else {
                "version": snapshot.version,
                "cash": snapshot.cash,
                "positions": dict(snapshot.positions),
            }
        ),
        # Rows and instants per table, counted by the writer as it appended them. Instants, not
        # just rows: a table's row count says how much was written, and the distinct `event_time`
        # count says how often; research asks the second question and the first cannot answer it.
        tables=writer.counts(),
        contract=contract_report(result),
        # What ran, not what was registered -- PER COMPONENT rather than folded (design §4.2).
        # `fingerprint` above is what was registered; this is the fingerprint of the bytes on disk
        # when they were loaded. They agree unless the component was edited after registration,
        # and that difference is the whole signal (`docs/issues/009`, `023`): a strategy that ran
        # 47 times under 12 distinct loaded fingerprints was edited 11 times, which is a direct
        # overfitting tell that a new component_id per edit would have scattered.
        source_digest=dict(as_loaded),
        # The declaration this strategy froze against: its own identity, not the run's.
        declared_digest=str(layer.identity),
        # Which roster this run read, and `None` when it read none. STATED, never compared -- a
        # roster grows as a matter of course, so a run refused for reading a different one than
        # yesterday would be refused every morning.
        roster=roster,
        period={
            "start": frozen.start,
            "end": frozen.end,
            "occurrences": len(result.occurrences),
        },
        # Where the wall clock went, by phase (`docs/issues/068`): the loop's `total`, the
        # `callback` side (window and decide), the `due` side, and each due stage by name.
        # Seconds, rounded to the microsecond so the record is not a float's full expansion.
        timing={phase: round(seconds, 6) for phase, seconds in result.timing.items()},
    )
    writer.finish(record, kind=STRATEGY_KIND)


def freeze_datamodel_record(
    writer: RunRecordWriter,
    result: DataModelResult,
    frozen: FrozenRun,
    layer: FrozenDataModel,
    as_loaded: Mapping[str, str],
) -> None:
    """Write one datamodel's facts, last, so a later process can read them (record `148`).

    The rows are not here: they are the dataset the run registered, under
    `.vqapr/materialized/<dataset_id>/`, and `dataset_id` names it. What this holds is what a
    reader cannot rebuild from that dataset -- which component wrote it, registered and as
    loaded, on which sessions, reading what -- and one line per session rather than the
    per-instrument lineage `059` measured at 478 MB.
    """
    component = layer.component
    times = [trace.evaluation_time for trace in result.occurrences]
    record = DatamodelRecord(
        run_id=writer.run_id,
        datamodel_ref=str(writer.strategy_ref),
        datamodel_id=layer.component_id,
        fingerprint=component.fingerprint,
        component={
            "component_id": layer.component_id,
            "path": str(component.path),
            "object_name": component.object_name,
            "config": dict(component.config),
            "fingerprint": component.fingerprint,
        },
        agenda={
            "agenda_id": str(layer.agenda.agenda_id),
            "content_identity": layer.agenda.content_identity,
            "occurrences": len(layer.agenda.occurrences),
        },
        dataset_id=layer.dataset_id,
        value_fields=list(layer.value_fields),
        rows=result.rows,
        sessions=[
            {
                "evaluation_time": trace.evaluation_time,
                "output_available_at": trace.output_available_at,
                "row_count": trace.row_count,
            }
            for trace in result.occurrences
        ],
        source_digest=dict(as_loaded),
        declared_digest=str(layer.identity),
        period={
            "start": frozen.start,
            "end": frozen.end,
            "occurrences": len(result.occurrences),
            "first": min(times) if times else None,
            "last": max(times) if times else None,
        },
    )
    writer.finish(record, kind=DATAMODEL_KIND)


def contract_report(result: SimulationResult) -> dict[str, object]:
    """What the strategy's constraints promised, and how often each was actually observed to hold.

    `held` and `checked` are two different numbers, and conflating them hides the case that matters
    most: a declaration checked zero times is not a declaration that held. It is one nobody asked
    about, and reporting that as `ok` would be the strongest false assurance this record could
    carry. So a constraint with `checked == 0` reports `ok: false` with a `cause` saying exactly
    that.

    **These count monitoring observations of the committed account.** They used to be meant to
    count judgements of the decision, and that member no longer exists: whether a limit held is a
    question about the book, not about the plan (PRD 7.1).

    **And they used to count nothing at all.** This walked the run's lifecycle entries asking each
    for an `evidence` attribute, but a lifecycle entry carries `kind` and `detail` and the evidence
    is the `detail` -- so the lookup returned `None` every time and the loop never ran
    (`docs/issues/051`).

    Scope, stated rather than implied: this reports the CONSTRAINTS a strategy declared. AC-R6 also
    names `weights`/`forms`/`records`, which are the authoring contract's declarations -- they do
    not exist yet, and inventing entries for them here would report a promise nobody made.
    """

    # Three populations, not one (`docs/issues/086`): what the author's own comparison held,
    # what it failed inside the framework's tolerance, and what it failed beyond it. The run that
    # filed the issue had 40 quantisation residues (worst 0.01%p) and one real breach (4.89%p),
    # and `held 42/82` reported them as one fact. `ok` turns on `breached` alone; the other two
    # counts and their worst excesses are filed beside it so a generous tolerance hides nothing.
    findings: dict[str, dict[str, object]] = {}
    for trace in getattr(result, "occurrences", ()):
        occurrence_report = getattr(getattr(trace, "result", None), "report", None)
        for stamped in getattr(occurrence_report, "findings", ()) or ():
            constraint_id = str(getattr(stamped, "constraint_id", "") or "")
            if not constraint_id:
                continue
            counts = findings.setdefault(
                constraint_id,
                {
                    "held": 0,
                    "within_tolerance": 0,
                    "breached": 0,
                    "checked": 0,
                    "tolerance": Decimal(0),
                    "worst_within": None,
                    "worst_breached": None,
                },
            )
            counts["checked"] += 1  # type: ignore[operator]
            verdict = getattr(stamped, "verdict", "held" if stamped.passed else "breached")
            counts[verdict] += 1  # type: ignore[operator]
            tolerance = getattr(stamped, "tolerance", None)
            if isinstance(tolerance, Decimal) and tolerance > counts["tolerance"]:  # type: ignore[operator]
                counts["tolerance"] = tolerance
            if verdict == "held":
                continue
            key = "worst_within" if verdict == "within_tolerance" else "worst_breached"
            excess = getattr(stamped, "excess", Decimal(0))
            worst = counts[key]
            if worst is None or excess > worst:  # type: ignore[operator]
                counts[key] = excess

    accepted = sum(
        1
        for entry in getattr(result.final_state, "lifecycle_trace", ())
        if getattr(entry, "kind", None) is LifecycleKind.ACCEPTED_INTENT
    )
    report: dict[str, object] = {}
    for constraint_id, counts in sorted(findings.items()):
        checked = int(counts["checked"])  # type: ignore[call-overload]
        breached = int(counts["breached"])  # type: ignore[call-overload]
        entry: dict[str, object] = {
            "held": counts["held"],
            "within_tolerance": counts["within_tolerance"],
            "breached": breached,
            "checked": checked,
            "tolerance": str(counts["tolerance"]),
            "worst_within": None if counts["worst_within"] is None else str(counts["worst_within"]),
            "worst_breached": (
                None if counts["worst_breached"] is None else str(counts["worst_breached"])
            ),
            "ok": breached == 0 and checked > 0,
        }
        if breached:
            entry["cause"] = (
                f"{breached} of {checked} check(s) breached beyond the tolerance "
                f"{counts['tolerance']} (worst excess {counts['worst_breached']})"
            )
            entry["fix"] = (
                f"change the strategy so what it holds satisfies {constraint_id}, loosen the "
                "bound, or -- if these are execution residue and not intent -- raise the "
                "constraint's `tolerance`"
            )
        elif checked == 0:
            entry["cause"] = "declared but never checked, so nothing was proven about it"
            entry["fix"] = "remove the declaration, or run over a period where it is exercised"
        report[constraint_id] = entry

    # A run that accepted intents while checking no constraint is not a clean run; it is a run
    # nobody constrained. Saying so is the point of reporting counts rather than a verdict.
    report["accepted_intents"] = accepted
    return report
