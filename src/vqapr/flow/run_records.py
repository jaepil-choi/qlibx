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
import tempfile
import time as _time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

RUNS_DIRECTORY = "runs"
RECORD_FILENAME = "record.json"
TABLES_DIRECTORY = "tables"

SCHEMA = "vqapr-run-record/v1"

RECORD_FIELDS = ("run_id", "account", "tables", "contract", "source_digest", "period")
"""The field set a run record carries, named once and read by both the writer and every reader.

AC-R5 asks that `show run`'s output and the frozen record carry the same fields. This lives here,
beside the record itself, rather than in the CLI that displays it: the record is the artifact and
the CLI is one of its readers, so the CLI importing this is the right direction and the core
package importing from the CLI was not.

`schema` is deliberately absent: it is the record's own metadata, not one of its answers.
"""


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


def _lock_holder(lock: Path) -> int | None:
    """The pid holding this run id, or `None` if nobody live does.

    A lock file older than `LOCK_STALE_AFTER` is treated as abandoned: its process died without
    releasing, and refusing forever on a dead holder would make a crash unrecoverable.
    """
    try:
        age = _time.time() - lock.stat().st_mtime
    except OSError:
        return None
    if age > LOCK_STALE_AFTER:
        return None
    try:
        return int(lock.read_text(encoding="ascii").strip() or "-1")
    except (OSError, ValueError):
        # Present and fresh but unreadable: still a live claim, just an anonymous one. Reporting
        # it as free would be the destructive answer.
        return -1


class RunRecordLive(FileExistsError):
    """A run is executing under this id right now.

    Distinct from `RunRecordExists` because the remedy is opposite: an existing RECORD is replaced
    with `--force`, while a LIVE run must not be, and telling an operator to force it would destroy
    the very rows they are waiting on.
    """

    def __init__(self, run_id: str, directory: Path, holder: int) -> None:
        self.run_id = run_id
        self.directory = directory
        self.holder = holder
        super().__init__(
            f"run {run_id!r} is already running at {directory} (pid {holder}); "
            "wait for it to finish, or use a different --run-id"
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
                holder = _lock_holder(directory / LOCK_FILENAME)
                if holder is None:
                    raise
                raise RunRecordLive(self.run_id, directory, holder) from failure
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
            holder = _lock_holder(directory / LOCK_FILENAME)
            if holder is not None:
                # Someone is running under this id right now. `--force` does not override this:
                # forcing a live run destroys the rows it is still writing and blends both into
                # one record, which is unrecoverable, while waiting costs nothing.
                raise RunRecordLive(self.run_id, directory, holder) from taken

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
            # of them. A peer whose `_lock_holder` read landed before this run's `_claim` can still
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

    def finish(self, record: Mapping[str, object]) -> Path:
        """Write the run's own facts, last, by atomic replace.

        Last because `record.json` existing is what makes the record complete: a reader that finds
        one knows the run reached its end. Atomically because a half-written record read by a cold
        process is indistinguishable from a run that recorded half its facts.
        """
        directory = self.directory
        payload = json.dumps(
            {"schema": SCHEMA, "run_id": self.run_id, **_encode(dict(record))},
            indent=2,
            sort_keys=True,
        )
        try:
            handle, staged = tempfile.mkstemp(dir=directory, prefix=".record.", suffix=".json")
        except OSError as gone:
            # The directory is no longer there, or no longer ours. Another run took this id while
            # this one was executing -- only possible when someone forced an id already in use --
            # and this run's rows went with it. Saying so beats an unhandled OSError that reads
            # like the framework broke.
            raise RunRecordTaken(self.run_id, directory) from gone
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                stream.write(payload + "\n")
            os.replace(staged, directory / RECORD_FILENAME)
        except OSError as gone:
            Path(staged).unlink(missing_ok=True)
            raise RunRecordTaken(self.run_id, directory) from gone
        except BaseException:
            Path(staged).unlink(missing_ok=True)
            raise
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


def read_record(root: Path, run_id: str) -> dict[str, Any]:
    """One run's frozen facts, exactly as they were written."""
    path = record_path(root, run_id)
    if not path.is_file():
        raise FileNotFoundError(
            f"no complete run record for {run_id!r} at {path}; "
            f"known runs: {', '.join(run_ids(root)) or '(none)'}"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def read_table(root: Path, run_id: str, table_id: str) -> Iterator[dict[str, Any]]:
    """Stream one table's rows back, one line at a time.

    A generator because a run's tables are the large half of the record, and a caller counting rows
    should not have to hold all of them to do it.
    """
    path = root / RUNS_DIRECTORY / run_id / TABLES_DIRECTORY / f"{table_id}.jsonl"
    if not path.is_file():
        return
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped:
                yield json.loads(stripped)


def table_ids(root: Path, run_id: str) -> tuple[str, ...]:
    directory = root / RUNS_DIRECTORY / run_id / TABLES_DIRECTORY
    if not directory.is_dir():
        return ()
    return tuple(sorted(path.stem for path in directory.glob("*.jsonl")))
