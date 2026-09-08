"""The workspace holds its directory with the shared mutex, and reports its own refusal.

**This file used to be `test_one_mutex_two_callers.py`**, and it pinned the two exclusive-lock
sites — `workspace.py` and `catalog_store.py` — against each other after they had drifted apart.
Record `124` deleted the catalog with the rest of the unshipped Project cluster, so there is one
caller now and the divergence this guarded against cannot recur. What survives is the property
that outlived the comparison: `filelock` clamps a future mtime, treats a vanished lock as no age,
reclaims a stale one, and lets its caller name the refusal.

Out of scope on purpose: `flow/run_records.py`'s lock. It is a run-length **lease**, not a mutex —
`heartbeat` and `release` never raise by design, and staleness is what makes a dead run's id
reclaimable. `run_records.py` records two prior attempts to simplify around it that each made a real
race measurably worse (9 of 12, then 12 of 12 failures) and were reverted. The exclusive-lock count
in this package is **one**, and record `106` said `two` when the catalog still existed.
"""

from __future__ import annotations

import os
import time as _time
from pathlib import Path

from vqapr._internal import filelock
from vqapr.workspace import (
    WORKSPACE_LOCK_FILENAME,
    WORKSPACE_LOCK_STALE_AFTER,
    WORKSPACE_LOCK_TIMEOUT,
    Workspace,
)


def test_a_negative_lock_age_is_clamped_at_zero(tmp_path: Path) -> None:
    """A lock written microseconds ago can carry an `st_mtime` ahead of `time.time()`.

    Filesystem and clock resolution differ, and the difference is an artifact, not information.
    Unclamped it reaches an operator as a negative age.
    """
    lock = tmp_path / "future.lock"
    lock.write_text("1", encoding="ascii")
    ahead = _time.time() + 3600
    os.utime(lock, (ahead, ahead))

    age = filelock.lock_age(lock)

    assert age == 0.0, "an mtime in the future is a clock artifact, reported as zero seconds old"


def test_a_lock_that_vanished_reads_as_no_age_rather_than_raising(tmp_path: Path) -> None:
    """The other half of the age contract: a lock removed mid-check is not an error."""
    assert filelock.lock_age(tmp_path / "never-existed.lock") is None


def test_a_stale_lock_is_reclaimed_rather_than_waited_out(tmp_path: Path) -> None:
    """Without this a crash leaves the resource permanently unwritable.

    The recovery step would be "delete a file we never told you about", which is why the caller
    carries a stale threshold rather than only a timeout.
    """
    lock = tmp_path / "abandoned.lock"
    lock.write_text("99999", encoding="ascii")
    long_dead = _time.time() - (filelock.LOCK_STALE_AFTER * 10)
    os.utime(lock, (long_dead, long_dead))

    def unreachable(_lock: Path, _timeout: float) -> BaseException:
        raise AssertionError("an abandoned lock must be reclaimed, not waited out")

    with filelock.exclusive(lock, on_timeout=unreachable, timeout=0.05):
        assert lock.exists(), "the lock is held by this caller now"

    assert not lock.exists(), "and released on the way out"


def test_the_workspace_constants_alias_the_shared_definition(tmp_path: Path) -> None:
    """`30.0` and `120.0` were once written out in two modules, free to drift apart.

    The names survive because callers and tests refer to them; what they must not become again is
    a second copy of a number.
    """
    assert WORKSPACE_LOCK_TIMEOUT == filelock.LOCK_TIMEOUT
    assert WORKSPACE_LOCK_STALE_AFTER == filelock.LOCK_STALE_AFTER


def test_the_workspace_still_refuses_a_contended_write_with_its_own_vocabulary(
    tmp_path: Path,
) -> None:
    """A shared mutex must not own its caller's failure vocabulary.

    A workspace refusal names the workspace and says who must act (423: another process holds
    it). That is why `on_timeout` is a caller-supplied factory rather than a fixed error type
    inside the lock.
    """
    workspace = Workspace.create(tmp_path)
    lock = workspace.path.parent / WORKSPACE_LOCK_FILENAME
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("99999", encoding="ascii")

    refusal = workspace._locked_refusal(lock, WORKSPACE_LOCK_TIMEOUT)

    assert refusal.stage == "write"
    assert refusal.failures[0].code == "workspace.locked"
    assert refusal.failures[0].status == 423
    assert str(workspace.path) in refusal.failures[0].requirement
