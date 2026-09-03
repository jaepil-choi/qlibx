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
import pyarrow.parquet as pq

from vqapr._internal import atomic

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
"""Each table is a directory of parquet files, one complete file per chunk `append` received.

Record `146` (deletion campaign Step 5). The rows were JSONL with a `.types.json` sidecar that
said which Python type each column had been stringified from, because JSON cannot carry a type
and a reader guessing from the text shifted every instant by its offset (the testbed's A5).
Parquet carries the types: an instant is a `timestamp[us, tz]` and comes back as the same
instant in the same zone through pyarrow and through duckdb alike. A `Decimal` is the one
value stored as text -- exact and unbounded, where a parquet decimal would need a fixed scale
and a weight of one third has twenty-eight places -- and the column's field metadata says so
(`vqapr.type: decimal`), so `read_table` restores it and a duckdb reader casts it knowingly.

One file per chunk rather than one open writer per table, because a killed run must leave
readable rows (record `135`): a parquet file is complete only once its footer is written, so an
open writer would leave nothing, while a file per chunk leaves every chunk that landed. A
chunk is one accepted occurrence's rows, so the files are as many as the run's occurrences.
"""

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

_STRATEGY_FIELDS = (
    "run_id",
    "strategy_ref",
    "strategy_id",
    "fingerprint",
    "component",
    "agenda",
    "constraints",
    "account",
    "tables",
    "contract",
    "source_digest",
    "declared_digest",
    "roster",
    "period",
)
"""What one strategy's record answers (record `139`): architecture §17.3.2's two missing values --
which `.py` ran (`component.path`) and the strategy's OWN fingerprint, registered (`fingerprint`)
and as loaded (`source_digest`, per component rather than folded) -- beside what a run record
answered before: the final account, the tables, the contract report, the roster, the period.
"""

_DATAMODEL_FIELDS = (
    "run_id",
    "datamodel_ref",
    "datamodel_id",
    "fingerprint",
    "component",
    "agenda",
    "dataset_id",
    "value_fields",
    "rows",
    "sessions",
    "source_digest",
    "declared_digest",
    "period",
)
"""What one datamodel's record answers (record `148`): the component that ran, registered and
as loaded; the dataset it wrote and the fields it declared; one row per session -- when it
evaluated, when its rows became available, how many -- and no per-instrument lineage
(`docs/issues/059`)."""

RUN_JSON_FIELDS = (
    "run_id",
    "declared_digest",
    "instruments",
    "period",
    "exchange",
    "execution_input",
    "initial_account",
    "datasets",
    "strategies",
    "datamodels",
)
"""What `run.json` answers: architecture §17.3.1's missing rows -- the universe, the venue and the
execution input with its fill convention (`docs/issues/034`), the initial account declaration, the
datasets and their source digests (A7) -- and which strategies the run names.
"""

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
        return {str(key): _encode(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_encode(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


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
        self.holder = claim.pid
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
        """Mark this run as still alive.

        Never raises: a lock that cannot be touched right now -- a peer reading it, a filesystem
        with coarse timestamps -- must not fail a run that is otherwise fine. The next chunk tries
        again, and chunks arrive far more often than the stale window.
        """
        with suppress(OSError):
            os.utime(self.directory / LOCK_FILENAME, None)

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
        """Drop this run's liveness claim.

        Never raises. It is called from `finish` and from the failure path of a run that is already
        ending, and a lock that cannot be removed right now -- because a peer has it open to read
        the holder, which on Windows raises rather than waiting -- is not a reason to fail a run
        that otherwise succeeded. The lock ages out on its own, so the worst case is that this id
        stays claimed until it goes stale.
        """
        with suppress(OSError):
            (self.directory / LOCK_FILENAME).unlink(missing_ok=True)

    def append(self, table_id: str, rows: Sequence[Mapping[str, object]]) -> None:
        """Append one chunk to one table, as one complete parquet file.

        Takes a chunk at a time so a caller CAN stream as it produces rows, and a run with a
        store does: each accepted occurrence's rows land here at publish.

        Also the run's heartbeat. `LOCK_STALE_AFTER` asks whether the holder is still alive, and
        without a refresh the answer is really "has this run been going longer than two minutes" --
        true of every real run here, which would let any peer take a live id.
        """
        self.heartbeat()
        if not rows:
            return
        directory = self.directory / TABLES_DIRECTORY / table_id
        directory.mkdir(parents=True, exist_ok=True)
        table = _arrow_table(rows, table_id, self._fields.setdefault(table_id, {}))
        part = self._parts.get(table_id, 0)
        target = directory / f"{part:06d}{PART_SUFFIX}"
        # Written beside the target and moved into place, so a reader listing the directory
        # never opens a file whose footer is not there yet.
        staging = directory / f".{part:06d}{PART_SUFFIX}.tmp"
        pq.write_table(table, staging, compression="zstd")
        os.replace(staging, target)
        self._parts[table_id] = part + 1
        instants = self._instants.setdefault(table_id, set())
        for row in rows:
            instants.add(str(row.get("event_time")))
        self._rows[table_id] = self._rows.get(table_id, 0) + len(rows)

    def finish(self, record: Mapping[str, object], *, kind: str = RUN_KIND) -> Path:
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
        payload = json.dumps({**head, **_encode(dict(record))}, indent=2, sort_keys=True)

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
        self.release()
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


def write_run_record(root: Path, run_id: str, record: Mapping[str, object]) -> Path:
    """Write `run.json`, the configuration every strategy of this run shares.

    Idempotent for the same configuration -- every process running a strategy of this run writes
    the same bytes, so no lock is needed -- and refused for a different one (`RunRecordConflict`).
    """
    path = run_record_path(root, run_id)
    declared = str(record.get("declared_digest"))
    if path.is_file():
        existing = read_run_record(root, run_id)
        if str(existing.get("declared_digest")) != declared:
            raise RunRecordConflict(run_id, path, existing.get("declared_digest"), declared)
    payload = json.dumps(
        {"schema": RUN_SCHEMA, "kind": RUN_KIND, "run_id": run_id, **_encode(dict(record))},
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
    """Every strategy record this run holds, as `<id>@<fp8>`, sorted.

    A strategy directory without `strategy.json` was killed before it finished; omitted here,
    exactly as `run_ids` omits an unfinished run.
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


def _resolve_ref(root: Path, run_id: str, strategy_ref: str | None) -> str | None:
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
    if strategy_ref is None:
        if (run_directory / TABLES_DIRECTORY).is_dir():
            return None
        members = strategy_refs(root, run_id)
        if len(members) == 1:
            return members[0]
        raise RunRecordMissing(
            f"run {run_id!r} at {run_directory} records "
            + (
                f"{len(members)} strategies ({', '.join(members)}); name one as strategy_ref"
                if members
                else "no finished strategy and no tables of its own"
            )
        )
    if (record_directory(root, run_id, strategy_ref)).is_dir():
        return strategy_ref
    members = strategy_refs(root, run_id)
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
    resolved = _resolve_ref(root, run_id, strategy_ref)
    directory = record_directory(root, run_id, resolved) / TABLES_DIRECTORY / table_id
    if not directory.is_dir():
        return ()
    return tuple(sorted(path for path in directory.glob(f"*{PART_SUFFIX}")))


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


def table_types(
    root: Path, run_id: str, table_id: str, strategy_ref: str | None = None
) -> dict[str, str] | None:
    """The kind each column was written as, from the parquet schema, or `None` for no table.

    The same vocabulary the retired sidecar used -- `bool`, `int`, `float`, `decimal`,
    `datetime`, `string` -- read off the first chunk that holds a value for the column.
    """
    parts = _parts(root, run_id, table_id, strategy_ref)
    if not parts:
        return None
    types: dict[str, str] = {}
    for path in parts:
        for column in pq.read_schema(path):
            if column.name in types:
                continue
            if column.metadata and column.metadata == _DECIMAL:
                types[column.name] = "decimal"
            elif pa.types.is_timestamp(column.type):
                types[column.name] = "datetime"
            elif pa.types.is_boolean(column.type):
                types[column.name] = "bool"
            elif pa.types.is_integer(column.type):
                types[column.name] = "int"
            elif pa.types.is_floating(column.type):
                types[column.name] = "float"
            elif pa.types.is_string(column.type):
                types[column.name] = "string"
    return types


read_typed_table = read_table
"""The reader `vqapr.public` exports under the name it had when the sidecar existed. Typed by
construction now; kept so a caller written against record `135` reads on."""


def table_ids(root: Path, run_id: str, strategy_ref: str | None = None) -> tuple[str, ...]:
    resolved = _resolve_ref(root, run_id, strategy_ref)
    directory = record_directory(root, run_id, resolved) / TABLES_DIRECTORY
    if not directory.is_dir():
        return ()
    return tuple(sorted(path.name for path in directory.iterdir() if path.is_dir()))
