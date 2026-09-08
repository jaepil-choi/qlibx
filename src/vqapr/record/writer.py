"""Writing one run's record: its rows into its own directory, its facts last.

The writer half. `RunRecordWriter` claims a run id with a lock, takes chunks of rows into an
Arrow buffer, seals them as one parquet file per table when the run ends, and writes the record
that marks it complete. `write_run_record` writes the one file every strategy of a run shares.

Imports `reader.py`, and is imported by nothing in this package: a writer reads the lock to
learn whether somebody else holds this id, and reads `run.json` to learn whether the run already
on disk describes a different configuration.
"""

from __future__ import annotations

import errno
import json
import os
import shutil
import time as _time
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from vqapr._internal import atomic
from vqapr.record.reader import (
    LOCK_FILENAME,
    RunRecordLive,
    _lock_claim,
    read_run_record,
)
from vqapr.record.schema import (
    COMPACT_FILENAME,
    MEMBER_KINDS,
    PART_SUFFIX,
    PROGRESS_EVERY,
    PROGRESS_FILENAME,
    RECORD_FIELDS_BY_KIND,
    RECORD_FILENAME,
    RUN_KIND,
    RUN_SCHEMA,
    SCHEMA,
    SPILL_BYTES,
    STRATEGY_KIND,
    TABLES_DIRECTORY,
    RunRecord,
    _arrow_table,
    _encode_mapping,
    _Record,
    record_directory,
    run_record_path,
)

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

