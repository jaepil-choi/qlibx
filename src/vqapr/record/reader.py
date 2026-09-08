"""Reading a run record back: what exists, how far it got, and the rows themselves.

Every reader a cold process needs, plus the two removals -- which are reads first, since what
they must not remove is a record another process is still writing.

The lock lives here for that reason. `RunRecordWriter` creates and refreshes it, but ASKING who
holds one is a read (`_lock_claim`), and the reader, the remover and the writer all ask. Keeping
it here is what lets the package layer in one direction: schema, then reader, then writer.
"""

from __future__ import annotations

import json
import shutil
import time as _time
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from vqapr.record.schema import (
    COMPACT_FILENAME,
    DATAMODEL_FILENAME,
    DATAMODEL_KIND,
    DATAMODELS_DIRECTORY,
    MEMBER_KINDS,
    PART_SUFFIX,
    PROGRESS_FILENAME,
    RECORD_FILENAME,
    RUN_FILENAME,
    RUN_KIND,
    RUN_SCHEMA,
    RUNS_DIRECTORY,
    SCHEMA,
    STRATEGIES_DIRECTORY,
    STRATEGY_FILENAME,
    STRATEGY_KIND,
    TABLES_DIRECTORY,
    _python_rows,
    record_directory,
    record_path,
    run_record_path,
)

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

