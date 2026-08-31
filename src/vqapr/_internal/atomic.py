"""One durable write, for every caller that swaps a file into place.

Four implementations of this existed — `workspace.py`, `_internal/catalog_store.py`,
`_internal/objects.py`, `flow/run_records.py` — each staging to a temporary file beside the target,
each calling `os.replace`, and each having independently decided what to do about the parts that are
easy to forget.

**Only one of the four retried the swap**, and the reasoning for it was written down only in
`workspace.py`:

    POSIX `rename` is unconditional, so a reader holding the old inode is simply left holding it
    and the swap succeeds. Windows refuses instead: `os.replace` onto a path another process
    currently has open fails with `WinError 5` [...] The workspace lock does not cover this. It
    serialises *writers* against each other [...] but a **reader** takes no lock, deliberately.

That reasoning is not about workspaces. It is about `os.replace` on Windows, and it applies to every
file in this package that a reader can hold open while a writer swaps it — a run record being read
by `show run`, a catalog being read by a concurrent `Project.open()`. Three of the four writers were
exposed to a race the fourth had already measured (1 run in 10 with eight concurrent processes) and
solved.

**Only two of the four fsynced.** `run_records.finish` did not, and nothing documented that as a
choice; it is the crash-safety-critical path in the package, so the omission reads as an oversight
rather than a decision. The shared writer fsyncs, and record `107` records that as a deliberate
change rather than letting it arrive silently.

What stays with the callers, because it was never about durability:

- **The failure vocabulary.** `run_records.finish` maps `OSError` to a typed `RunRecordTaken`
  carrying the run id; `workspace._write` maps it to `workspace.write.failed`. A single hard-coded
  failure type would push each caller's own vocabulary back into a `try/except` at every call site,
  so `on_error` is a caller-supplied factory.
- **Verification before install.** `objects.stage_object` re-reads the staged bytes and checks their
  digest before the swap, which is its crash-safety boundary: anything that goes wrong before that
  point leaves an orphaned temp file, never a corrupt object at the final digest path. That is a
  content-addressed store's invariant, not a property of writing files, so it arrives as a `verify`
  hook rather than as behaviour every caller pays for.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
import time as _time
from collections.abc import Callable
from pathlib import Path

SWAP_ATTEMPTS = 10
SWAP_BACKOFF = 0.02
"""Retries for the swap a concurrent reader can make fail on Windows.

`os.replace` onto a path another process has open fails with `WinError 5`, and that reader is gone
microseconds later. Measured on this repository before the retry existed: 1 run in 10 with eight
processes reading and writing at once. A real permission problem still fails, because it outlasts
the retries.
"""

__all__ = ["SWAP_ATTEMPTS", "SWAP_BACKOFF", "write_atomically"]


def _swap(temporary: Path, target: Path, *, attempts: int, backoff: float) -> None:
    for attempt in range(attempts):
        try:
            os.replace(temporary, target)
            return
        except OSError:
            # A reader has the target open. Windows refuses the swap rather than letting the
            # reader keep the old file, and the reader is gone microseconds later.
            if attempt + 1 == attempts:
                raise
            _time.sleep(backoff * (attempt + 1))


def write_atomically(
    target: Path,
    payload: bytes | str,
    *,
    on_error: Callable[[OSError], BaseException] | None = None,
    verify: Callable[[bytes], None] | None = None,
    create_parent: bool = True,
    encoding: str = "utf-8",
    attempts: int = SWAP_ATTEMPTS,
    backoff: float = SWAP_BACKOFF,
) -> None:
    """Write `payload` to `target` so a reader sees either the old file or the new one, never both.

    Text is encoded and written as bytes, so a `str` payload lands with the newlines it already
    carries on every platform. Two of the four former writers opened in text mode with the
    platform default, which on Windows silently translated `\\n` to `\\r\\n`; the artifacts are
    JSON and YAML read back by parsers, so the translation bought nothing and cost byte-identity
    across platforms.

    The temporary file is created in the target's own directory, because `os.replace` is only
    atomic within a filesystem and a temp directory can be on another one.

    On any failure the temporary file is removed and `target` is left exactly as it was. That is
    the contract the callers depend on: a run that dies mid-write leaves a readable previous
    record, not a truncated one.

    `on_error` receives the `OSError` and returns the exception to raise in its place. Without it
    the `OSError` propagates unchanged.

    `create_parent=False` is for the caller whose parent directory's **absence is the signal**.
    `RunRecordWriter.finish` writes into a directory it claimed at the start of the run; if that
    directory is gone by the end, another run took the id and this run's rows went with it, which
    is a `RunRecordTaken` rather than something to repair. Creating the directory would turn that
    detection into a silent recreation of state somebody else now owns.
    """
    if create_parent:
        target.parent.mkdir(parents=True, exist_ok=True)
    data = payload.encode(encoding) if isinstance(payload, str) else payload

    try:
        handle, staged_name = tempfile.mkstemp(
            dir=target.parent, prefix=f".{target.name}.", suffix=".tmp"
        )
    except OSError as error:
        # Staging itself failed -- most often because the parent directory is gone. There is
        # nothing to clean up, and the caller's vocabulary still applies: for `run_records` this
        # is precisely the stolen-run-id case, and it must not escape as a raw OSError that reads
        # like the framework broke.
        if on_error is not None:
            raise on_error(error) from error
        raise

    staged = Path(staged_name)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if verify is not None:
            # Re-read what actually landed rather than trusting what was handed in: the point of
            # the check is to catch a write that did not survive the trip to disk.
            verify(staged.read_bytes())
        _swap(staged, target, attempts=attempts, backoff=backoff)
    except OSError as error:
        with contextlib.suppress(OSError):
            staged.unlink(missing_ok=True)
        if on_error is not None:
            raise on_error(error) from error
        raise
    except BaseException:
        with contextlib.suppress(OSError):
            staged.unlink(missing_ok=True)
        raise
    finally:
        # `os.replace` consumed the temp file on success; this clears the leftovers of a
        # verification failure or an exception raised while writing.
        with contextlib.suppress(OSError):
            staged.unlink(missing_ok=True)
