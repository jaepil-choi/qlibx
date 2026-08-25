"""File-backed, non-mutating read and CAS commit for the `Catalog` root.

The on-disk root lives at `<root>/.vqapr/catalog.json`. `read_catalog` never creates anything —
a project that has never committed reads back `Catalog.empty()` with the filesystem untouched.
`commit_catalog` is the only path that ever writes: it reacquires an exclusive lock, re-reads the
root inside that lock, and refuses to write unless both the caller's expected generation and root
digest still match what is on disk. There is no automatic rebase; a mismatch is a typed
`CatalogConflict` and the caller decides what to do next.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
import time as _time
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

from vqapr._internal.catalog import Catalog, canonical_bytes, root_digest

CATALOG_DIRECTORY = ".vqapr"
CATALOG_FILENAME = "catalog.json"
CATALOG_LOCK_FILENAME = ".catalog.lock"
OBJECTS_DIRECTORY = ("objects", "sha256")

CATALOG_LOCK_TIMEOUT = 30.0
CATALOG_LOCK_STALE_AFTER = 120.0

__all__ = [
    "CatalogConflict",
    "commit_catalog",
    "read_catalog",
    "sweep_orphans",
]


class CatalogConflict(Exception):
    """Raised when a CAS commit's expected generation/root digest no longer matches disk.

    `mutation` is always `False` here: a conflict is detected before any write is attempted, so
    the on-disk root is guaranteed byte-identical to what it was before the failed commit.
    """

    def __init__(
        self,
        expected_generation: int,
        observed_generation: int,
        *,
        mutation: bool = False,
    ):
        super().__init__(
            f"catalog conflict: expected generation {expected_generation}, "
            f"observed generation {observed_generation}"
        )
        self.expected_generation = expected_generation
        self.observed_generation = observed_generation
        self.mutation = mutation


def _catalog_path(root: Path) -> Path:
    return Path(root) / CATALOG_DIRECTORY / CATALOG_FILENAME


def _objects_dir(root: Path) -> Path:
    path = Path(root) / CATALOG_DIRECTORY
    for part in OBJECTS_DIRECTORY:
        path = path / part
    return path


def _catalog_from_document(document: object) -> Catalog:
    if not isinstance(document, dict):
        raise ValueError("catalog.json must contain a JSON object")
    required = {
        "schema",
        "generation",
        "datasets",
        "execution_inputs",
        "extensions",
        "publications",
        "object_digests",
    }
    missing = required - document.keys()
    if missing:
        raise ValueError(f"catalog.json is missing required keys: {sorted(missing)!r}")
    return Catalog(
        schema=document["schema"],
        generation=document["generation"],
        datasets=document["datasets"],
        execution_inputs=document["execution_inputs"],
        extensions=document["extensions"],
        publications=document["publications"],
        object_digests=tuple(document["object_digests"]),
    )


def read_catalog(root: Path) -> Catalog:
    """Read the committed catalog root, or `Catalog.empty()` if none was ever committed.

    This is a hard non-mutating contract: a fresh `root` with no `.vqapr` directory is left
    exactly as it was found — no directory, lock file, or catalog is created by a read.
    """
    path = _catalog_path(root)
    if not path.exists():
        return Catalog.empty()
    text = path.read_text(encoding="utf-8")
    document = json.loads(text)
    return _catalog_from_document(document)


def _stale_lock_age(lock: Path) -> float | None:
    """Seconds since the lock was created, or `None` if it disappeared while checking."""
    try:
        return _time.time() - lock.stat().st_mtime
    except OSError:
        return None


@contextlib.contextmanager
def _exclusive(catalog_dir: Path) -> Iterator[None]:
    """Hold the catalog directory's writer lock for one read-modify-write cycle.

    Modeled directly on `Workspace._exclusive`: `O_CREAT | O_EXCL` is the portable primitive,
    succeeding for exactly one process and failing for every other on Windows and POSIX alike.

    Taking the lock has to create the catalog directory, so this records whether the directory
    already existed. A cycle that creates the directory and then commits nothing - the failed
    first registration the plan calls out - must leave the root exactly as it found it, or
    `Project.open()` would no longer be safe to call before a first successful commit.
    """
    preexisting = catalog_dir.is_dir()
    catalog_dir.mkdir(parents=True, exist_ok=True)
    lock = catalog_dir / CATALOG_LOCK_FILENAME
    deadline = _time.monotonic() + CATALOG_LOCK_TIMEOUT
    handle: int | None = None
    while True:
        try:
            handle = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            age = _stale_lock_age(lock)
            if age is not None and age > CATALOG_LOCK_STALE_AFTER:
                with contextlib.suppress(OSError):
                    lock.unlink()
                continue
            if _time.monotonic() >= deadline:
                raise TimeoutError(
                    f"catalog at {catalog_dir} must be writable within "
                    f"{CATALOG_LOCK_TIMEOUT:.0f}s; another process has held {lock} "
                    "for the whole timeout"
                ) from None
            _time.sleep(0.02)
    try:
        os.write(handle, str(os.getpid()).encode("utf-8"))
        os.close(handle)
        handle = None
        yield
    finally:
        if handle is not None:
            os.close(handle)
        with contextlib.suppress(OSError):
            lock.unlink()
        if not preexisting:
            # Only an empty directory is removed: once a catalog or object landed, the
            # directory is real state and never swept away by an unwinding writer.
            with contextlib.suppress(OSError):
                catalog_dir.rmdir()


def _write_catalog(catalog_dir: Path, catalog: Catalog) -> None:
    catalog_dir.mkdir(parents=True, exist_ok=True)
    path = catalog_dir / CATALOG_FILENAME
    fd, tmp_name = tempfile.mkstemp(dir=catalog_dir, prefix=".catalog-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(canonical_bytes(catalog))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


def commit_catalog(
    root: Path,
    *,
    candidate: Catalog,
    expected_generation: int,
    expected_root_digest: str,
) -> Catalog:
    """Compare-and-swap the catalog root, incrementing generation exactly once on success.

    Callers must have built `candidate` from a snapshot with `expected_generation` and
    `expected_root_digest`. Both are re-checked against disk while holding the writer lock; if
    either no longer matches, the lock is released and `CatalogConflict` is raised without any
    write taking place.
    """
    if not isinstance(candidate, Catalog):
        raise TypeError(f"candidate must be a Catalog, got {type(candidate).__name__}")
    catalog_dir = Path(root) / CATALOG_DIRECTORY
    with _exclusive(catalog_dir):
        current = read_catalog(root)
        stale_generation = current.generation != expected_generation
        stale_digest = root_digest(current) != expected_root_digest
        if stale_generation or stale_digest:
            raise CatalogConflict(expected_generation, current.generation, mutation=False)
        committed = replace(candidate, generation=expected_generation + 1)
        _write_catalog(catalog_dir, committed)
    return committed


def sweep_orphans(
    root: Path,
    *,
    referenced: set[str],
    grace_seconds: float = 86400.0,
) -> tuple[str, ...]:
    """Remove unreferenced content objects older than `grace_seconds`; return removed digests.

    Only objects actually unlinked are reported. Any per-file or directory-level failure is
    swallowed here — a sweep failure must never invalidate a committed catalog root — but the
    function only claims what it actually removed.
    """
    objects_dir = _objects_dir(root)
    removed: list[str] = []
    try:
        if not objects_dir.is_dir():
            return ()
        now = _time.time()
        for entry in objects_dir.iterdir():
            digest = entry.name
            if digest in referenced:
                continue
            try:
                if not entry.is_file():
                    continue
                age = now - entry.stat().st_mtime
                if age < grace_seconds:
                    continue
                entry.unlink()
            except OSError:
                continue
            removed.append(digest)
    except OSError:
        pass
    return tuple(removed)
