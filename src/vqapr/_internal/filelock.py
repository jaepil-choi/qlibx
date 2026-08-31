"""One exclusive mutex, for every caller that holds a directory for a read-modify-write cycle.

Two implementations of this existed, and `catalog_store._exclusive`'s own docstring said so:
*"Modeled directly on `Workspace._exclusive`."* It was a copy, made knowingly, and the copies had
drifted in the two ways copies always drift.

**They disagreed about the failure type.** `Workspace._exclusive` raised a typed `VqaprError` with
`workspace.write.locked` — six fields, a `fix`, an `explain` topic. `catalog_store._exclusive`
raised a bare `TimeoutError`, which `cli/main.py`'s outermost `except Exception` renders as
`stage: "unhandled"`. To an agent that is the signal for *"the framework broke"*, so a contended
catalog told the reader to suspect the package rather than wait for the other writer. Recorded as
finding C4 of the structural audit.

**They disagreed about a negative age.** `workspace._stale_lock_age` clamped at zero; the catalog's
copy did not. A lock file written microseconds ago can carry an `st_mtime` marginally ahead of
`time.time()` — filesystem and clock resolution differ — and the difference is an artifact, not
information.

**And the two constants were written down twice**, `30.0` and `120.0` in each file, free to be
tuned in one and not the other.

What is deliberately NOT here: `flow/run_records.py`'s lock. That one is a run-length **lease**, not
a mutex — `_claim` writes the holder's pid, `heartbeat` touches the file per chunk and never raises,
`release` never raises, and staleness is what makes a dead run's id reclaimable. Folding a lease
into a mutex abstraction because both call `O_CREAT | O_EXCL` would be pattern-matching on the
primitive rather than on the semantics, and `run_records.py` records two prior attempts to
"simplify" around that lock that each made a real race measurably worse (9 of 12 and 12 of 12
failures) and were reverted. The exclusive-lock count in this package is therefore **two**, not one:
this mutex and that lease.
"""

from __future__ import annotations

import contextlib
import os
import time as _time
from collections.abc import Callable, Iterator
from pathlib import Path

LOCK_TIMEOUT = 30.0
"""How long a waiter keeps trying before it gives up with the caller's typed failure."""

LOCK_STALE_AFTER = 120.0
"""A lock older than this is assumed to belong to a process that died holding it.

Without this a crash leaves the resource permanently unwritable, and the recovery step is "delete a
file we never told you about".
"""

_RETRY_INTERVAL = 0.02

__all__ = ["LOCK_STALE_AFTER", "LOCK_TIMEOUT", "exclusive", "lock_age"]


def lock_age(lock: Path) -> float | None:
    """Seconds since the lock was last written, or `None` if it disappeared while checking.

    Clamped at zero. A lock written microseconds ago can report an `st_mtime` marginally ahead of
    `time.time()`, and an unclamped subtraction surfaces that to an operator as a negative age.
    """
    try:
        return max(0.0, _time.time() - lock.stat().st_mtime)
    except OSError:
        return None


@contextlib.contextmanager
def exclusive(
    lock: Path,
    *,
    on_timeout: Callable[[Path, float], BaseException],
    timeout: float = LOCK_TIMEOUT,
    stale_after: float = LOCK_STALE_AFTER,
) -> Iterator[None]:
    """Hold `lock` for one read-modify-write cycle.

    `O_CREAT | O_EXCL` is the portable primitive: creating the file succeeds for exactly one
    process and fails for every other, on Windows and POSIX alike. `fcntl`/`msvcrt` locks would
    need two implementations and neither survives an NFS mount well.

    The waiting caller retries rather than blocking in the kernel, so it can give up with a typed
    failure instead of hanging forever behind a holder that will never finish.

    `on_timeout` is supplied by the caller and receives the lock path and the elapsed timeout. It
    returns the exception to raise. This is a parameter rather than a fixed error type because the
    two callers are refusing different things to different readers — a workspace refusal names the
    workspace and its `explain` topic, a catalog refusal names the catalog directory — and a shared
    lock that imposed one failure vocabulary on both would push the caller's own vocabulary back
    into a `try/except` at every call site.

    The caller creates and removes any directory the lock lives in. The catalog's writer has to
    unwind a directory it created when a cycle commits nothing, and that unwinding is its own
    business, not the lock's.
    """
    lock.parent.mkdir(parents=True, exist_ok=True)
    deadline = _time.monotonic() + timeout
    handle: int | None = None
    while True:
        try:
            handle = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            age = lock_age(lock)
            if age is not None and age > stale_after:
                # The holder is gone. Removing the lock races with another waiter doing the same
                # thing, which is harmless: whoever loses simply keeps waiting.
                with contextlib.suppress(OSError):
                    lock.unlink()
                continue
            if _time.monotonic() >= deadline:
                raise on_timeout(lock, timeout) from None
            _time.sleep(_RETRY_INTERVAL)
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
