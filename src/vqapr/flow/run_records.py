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
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from vqapr._internal import atomic

RUNS_DIRECTORY = "runs"
RECORD_FILENAME = "record.json"
TABLES_DIRECTORY = "tables"

SCHEMA = "vqapr-run-record/v2"
"""Bumped from `v1` by record `115`, when the record gained a `kind` discriminator.

A reader is now entitled to branch on this. `read_record` refuses a major version it does not know
instead of handing back a mapping whose fields mean something else -- see `_require_known_schema`.
"""

RUN_KIND = "run"
"""A simulation: the only kind `v1` could describe, and still the only kind written today."""

MATERIALIZATION_KIND = "materialization"
"""A dataset materialization. Declared here in record `115` and WRITTEN by record `116`.

Named one story before it is produced on purpose. `115` changes the record's shape and `116` adds
the second producer; splitting them means the shape change lands with the reader-side check that
protects it, rather than arriving in the same commit as a new writer and being tested only through
that writer.
"""

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

_MATERIALIZATION_FIELDS = (
    "run_id",
    "dataset_id",
    "source_digest",
    "declared_digest",
    "rows",
    "span",
    "period",
)
"""What a materialization answers. Written by record `116`; declared here so the discriminator has
two real branches rather than one and a promise.

`run_id`, `source_digest`, `declared_digest` and `period` are deliberately the same names a run
uses: the two kinds answer some of the same questions, and a reader that wants "which declarations
produced this" should not need to know which kind it is holding to ask.
"""

RECORD_FIELDS_BY_KIND: dict[str, tuple[str, ...]] = {
    RUN_KIND: _RUN_FIELDS,
    MATERIALIZATION_KIND: _MATERIALIZATION_FIELDS,
}


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
            f"released automatically about {claim.releases_in:.0f}s from now. Wait, or use a "
            "different --run-id"
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
            "another run claimed the same id. Re-run with a --run-id nobody else is using"
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

    @property
    def directory(self) -> Path:
        return self.root / RUNS_DIRECTORY / self.run_id

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
                raise RunRecordLive(self.run_id, directory, claim) from failure
            raise RunRecordExists(self.run_id, directory) from failure

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
                raise RunRecordLive(self.run_id, directory, claim) from taken

            # Nobody live holds it. A COMPLETE record is a real conflict and still needs `--force`
            # -- replacing a finished result must stay deliberate. Abandoned leftovers are not:
            # the run that made them is dead, no reader ever returned them, and charging the
            # operator a destructive flag to clear someone else's crash is a cost with no benefit.
            if (directory / RECORD_FILENAME).is_file() and not replace:
                raise RunRecordExists(self.run_id, directory) from taken

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
        """Append one chunk to one table.

        Takes a chunk at a time so a caller CAN stream as it produces rows. `public.run` does not
        yet: it hands over the whole recorder output once the run returns.

        Also the run's heartbeat. `LOCK_STALE_AFTER` asks whether the holder is still alive, and
        without a refresh the answer is really "has this run been going longer than two minutes" --
        true of every real run here, which would let any peer take a live id.
        """
        self.heartbeat()
        if not rows:
            return
        path = self.directory / TABLES_DIRECTORY / f"{table_id}.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(_encode(row), sort_keys=True) + "\n")

    def finish(self, record: Mapping[str, object], *, kind: str = RUN_KIND) -> Path:
        """Write the run's own facts, last, by atomic replace.

        Last because `record.json` existing is what makes the record complete: a reader that finds
        one knows the run reached its end. Atomically because a half-written record read by a cold
        process is indistinguishable from a run that recorded half its facts.

        `kind` defaults to `RUN_KIND` because every caller today writes a run. Record `116` passes
        `MATERIALIZATION_KIND`; the default is what lets `115` change the shape without touching a
        single call site, so the reader-side check lands before the second producer exists.
        """
        if kind not in RECORD_FIELDS_BY_KIND:
            raise KeyError(
                f"unknown run-record kind {kind!r}; known kinds are "
                f"{', '.join(sorted(RECORD_FIELDS_BY_KIND))}"
            )
        directory = self.directory
        payload = json.dumps(
            {
                "schema": SCHEMA,
                # The discriminator, written before the answers so a reader scanning the head of
                # the file knows what it is holding. Record `115`.
                "kind": kind,
                "run_id": self.run_id,
                **_encode(dict(record)),
            },
            indent=2,
            sort_keys=True,
        )

        def taken(gone: OSError) -> BaseException:
            # The directory is no longer there, or no longer ours. Another run took this id while
            # this one was executing -- only possible when someone forced an id already in use --
            # and this run's rows went with it. Saying so beats an unhandled OSError that reads
            # like the framework broke.
            return RunRecordTaken(self.run_id, directory)

        # `create_parent=False` is load-bearing: the directory's ABSENCE is how this detects a
        # stolen run id. Recreating it would turn the detection into a silent re-claim of state
        # another run now owns.
        atomic.write_atomically(
            directory / RECORD_FILENAME,
            payload + "\n",
            on_error=taken,
            create_parent=False,
        )
        # The run is over, so it is no longer live. Released after the record lands, never before:
        # a reader that sees a complete record must never also see a live claim on it.
        self.release()
        return directory / RECORD_FILENAME


def record_path(root: Path, run_id: str) -> Path:
    return root / RUNS_DIRECTORY / run_id / RECORD_FILENAME


def run_ids(root: Path) -> tuple[str, ...]:
    """Every run this root holds a complete record for, sorted.

    Derived by scanning rather than read from an index, so no two runs share a mutable target. A
    directory without `record.json` is a run that did not finish; it is omitted rather than
    reported as a run whose facts are missing.
    """
    directory = root / RUNS_DIRECTORY
    if not directory.is_dir():
        return ()
    return tuple(
        sorted(
            child.name
            for child in directory.iterdir()
            if child.is_dir() and (child / RECORD_FILENAME).is_file()
        )
    )


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


def read_table(root: Path, run_id: str, table_id: str) -> Iterator[dict[str, Any]]:
    """Stream one table's rows back, one line at a time.

    A generator because a run's tables are the large half of the record, and a caller counting rows
    should not have to hold all of them to do it.
    """
    path = root / RUNS_DIRECTORY / run_id / TABLES_DIRECTORY / f"{table_id}.jsonl"
    if not path.is_file():
        return
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                row = json.loads(stripped)
                if not isinstance(row, dict):
                    # Valid JSON of the wrong shape is damage too. Yielding it would break this
                    # function's own `Iterator[dict[str, Any]]` contract and hand every caller a
                    # bare number where it expects a row.
                    raise ValueError(f"expected a JSON object, found {type(row).__name__}")
                yield row
            except json.JSONDecodeError as damaged:
                # A damaged row is reported, never skipped. Skipping would let `show run --table`
                # return a short table that looks complete, and a reader comparing it against the
                # record's own row count would find two numbers disagreeing with no reason given.
                # An empty file is a different thing and stays legal: a run may record a table and
                # write nothing to it.
                raise ValueError(
                    f"{path} line {number} is not one JSON row: {damaged}. The recorder wrote "
                    "this file, so a line that does not parse means it was edited or truncated; "
                    "restore it, or re-run under a new run id"
                ) from damaged


def table_ids(root: Path, run_id: str) -> tuple[str, ...]:
    directory = root / RUNS_DIRECTORY / run_id / TABLES_DIRECTORY
    if not directory.is_dir():
        return ()
    return tuple(sorted(path.stem for path in directory.glob("*.jsonl")))
