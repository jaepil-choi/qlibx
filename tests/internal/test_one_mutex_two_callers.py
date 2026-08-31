"""The workspace and the catalog hold their directories with the same mutex.

`catalog_store._exclusive`'s own docstring said *"Modeled directly on `Workspace._exclusive`"* — a
knowing copy. Copies drift, and these two had drifted in exactly the two ways this file pins.

Out of scope on purpose: `flow/run_records.py`'s lock. It is a run-length **lease**, not a mutex —
`heartbeat` and `release` never raise by design, and staleness is what makes a dead run's id
reclaimable. `run_records.py` records two prior attempts to simplify around it that each made a real
race measurably worse (9 of 12, then 12 of 12 failures) and were reverted. The exclusive-lock count
in this package is **two**, and record `106` says so rather than claiming one.
"""

from __future__ import annotations

import os
import time as _time
from pathlib import Path

import pytest

from vqapr._internal import filelock
from vqapr._internal.catalog_store import (
    CATALOG_LOCK_FILENAME,
    CATALOG_LOCK_STALE_AFTER,
    CATALOG_LOCK_TIMEOUT,
    _exclusive,
)
from vqapr.domain.errors import VqaprError
from vqapr.workspace import (
    WORKSPACE_LOCK_FILENAME,
    WORKSPACE_LOCK_STALE_AFTER,
    WORKSPACE_LOCK_TIMEOUT,
    Workspace,
)


def test_a_contended_catalog_refuses_readably_instead_of_unhandled(tmp_path: Path) -> None:
    """Audit finding C4, closed.

    The catalog raised a bare `TimeoutError`. `cli/main.py`'s outermost `except Exception` renders
    an untyped exception as `stage: "unhandled"`, which to an agent reading the envelope is the
    signal for *"the framework is broken"* — so a contended catalog, an ordinary and recoverable
    condition, sent the reader to suspect the package instead of waiting for the other writer.
    `Workspace` refused the identical situation with six readable fields.
    """
    catalog_dir = tmp_path / ".vqapr"
    catalog_dir.mkdir(parents=True)
    held = catalog_dir / CATALOG_LOCK_FILENAME
    held.write_text("99999", encoding="ascii")

    # A timeout short enough to be a test, and a stale threshold long enough that the lock above
    # is not swept as abandoned before the wait runs out.
    contended = filelock.exclusive(
        held,
        on_timeout=_locked_refusal_for(catalog_dir),
        timeout=0.05,
        stale_after=CATALOG_LOCK_STALE_AFTER,
    )

    with pytest.raises(VqaprError) as refused, contended:
        pytest.fail("the lock was already held; acquiring it must not succeed")

    assert refused.value.stage == "catalog.write"
    failure = refused.value.failures[0]
    assert failure.code == "catalog.write.locked"
    assert str(catalog_dir) in failure.requirement
    assert str(held) in failure.observed
    assert failure.fix, "a refusal an operator can act on needs a fix"
    assert failure.explain, "and an explain topic for the follow-up question"
    assert refused.value.mutation is False, "a refused acquisition wrote nothing"


def _locked_refusal_for(catalog_dir: Path):
    """Reach the catalog's own refusal factory without duplicating its wording here."""
    from vqapr._internal.catalog_store import _locked_refusal

    return _locked_refusal(catalog_dir)


def test_both_mutex_sites_clamp_a_negative_lock_age_identically(tmp_path: Path) -> None:
    """`workspace` clamped at zero; the catalog's copy did not.

    A lock written microseconds ago can carry an `st_mtime` marginally ahead of `time.time()` —
    filesystem and clock resolution differ — and the difference is an artifact, not information.
    Unclamped it reaches an operator as a negative age. Now there is one reader, so the two cannot
    disagree; this asserts the property at the shared function both call.
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

    The recovery step would be "delete a file we never told you about", which is why both callers
    carry a stale threshold rather than only a timeout.
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


def test_the_two_callers_share_one_definition_of_the_constants(tmp_path: Path) -> None:
    """`30.0` and `120.0` were written out in both modules.

    Free, that way, to be tuned in one and not the other. The names survive because callers and
    tests refer to them; what changed is that they are now aliases of a single definition rather
    than second copies of a number.
    """
    assert CATALOG_LOCK_TIMEOUT is filelock.LOCK_TIMEOUT
    assert CATALOG_LOCK_STALE_AFTER is filelock.LOCK_STALE_AFTER
    assert WORKSPACE_LOCK_TIMEOUT == filelock.LOCK_TIMEOUT
    assert WORKSPACE_LOCK_STALE_AFTER == filelock.LOCK_STALE_AFTER


def test_the_workspace_still_refuses_a_contended_write_with_its_own_vocabulary(
    tmp_path: Path,
) -> None:
    """Sharing the mutex must not flatten the two callers into one failure vocabulary.

    A workspace refusal names the workspace and carries `WORKSPACE_STATE`; a catalog refusal names
    the catalog directory. That is why `on_timeout` is a caller-supplied factory rather than a fixed
    error type inside the lock.
    """
    workspace = Workspace.create(tmp_path)
    lock = workspace.path.parent / WORKSPACE_LOCK_FILENAME
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("99999", encoding="ascii")

    refusal = workspace._locked_refusal(lock, WORKSPACE_LOCK_TIMEOUT)

    assert refusal.stage == "workspace.write"
    assert refusal.failures[0].code == "workspace.write.locked"
    assert str(workspace.path) in refusal.failures[0].requirement


def test_the_catalog_directory_is_unwound_when_a_cycle_commits_nothing(tmp_path: Path) -> None:
    """The part of `_exclusive` that was never about locking, and had to stay.

    A cycle that creates `.vqapr/` and then commits nothing must leave the root exactly as it found
    it, or `Project.open()` stops being safe to call before a first successful commit.
    """
    catalog_dir = tmp_path / ".vqapr"
    assert not catalog_dir.exists()

    with _exclusive(catalog_dir):
        assert catalog_dir.is_dir(), "taking the lock creates the directory"

    assert not catalog_dir.exists(), "and an empty one is swept back up on the way out"


def test_a_directory_that_already_held_state_survives_the_cycle(tmp_path: Path) -> None:
    """The other side of it: once a catalog or object landed, the directory is real state."""
    catalog_dir = tmp_path / ".vqapr"
    catalog_dir.mkdir(parents=True)
    (catalog_dir / "catalog.json").write_text("{}", encoding="utf-8")

    with _exclusive(catalog_dir):
        pass

    assert catalog_dir.is_dir()
    assert (catalog_dir / "catalog.json").exists()
