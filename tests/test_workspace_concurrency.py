"""Parallel registration does not lose declarations.

Running strategies in parallel is the normal case for a loop-based engine, not an edge one. The
workspace write was already atomic -- a temporary file replaced into place -- but atomicity only
guarantees a reader never sees half a file. It does not stop two processes from each reading the
same state, each adding one declaration, and the second write erasing the first.

Nothing fails when that happens. A declaration is simply gone, and the run that needed it reports
a missing reference somewhere unrelated.

These tests use real processes. Threads would share an interpreter and could pass while the
cross-process case still lost writes.

The declaration each writer adds is a component: since record `148` an agenda is derived from
the run rather than registered, so a component is the smallest declaration a process registers.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from vqapr.extension.component import ComponentKind, ComponentRef
from vqapr.public import Workspace
from vqapr.workspace import WORKSPACE_LOCK_FILENAME


def _component(raw_id: str) -> ComponentRef:
    return ComponentRef.of(
        raw_id,
        ComponentKind.STRATEGY_MODEL,
        Path(f"{raw_id}.py"),
        "Strategy",
        fingerprint="a" * 64,
    )


WORKERS = 8

WORKER = textwrap.dedent(
    """
    import sys
    from pathlib import Path
    from vqapr.public import ComponentKind, ComponentRef, Workspace

    project, index = sys.argv[1], sys.argv[2]
    component = ComponentRef.of(
        f"component-{index}",
        ComponentKind.STRATEGY_MODEL,
        Path(f"component-{index}.py"),
        "Strategy",
        fingerprint="a" * 64,
    )
    with Workspace.transaction(project) as t:
        t.register_component(component)
    """
).strip()


def _spawn(project: Path, index: int) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-c", WORKER, str(project), str(index)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def test_parallel_registrations_all_survive(tmp_path: Path) -> None:
    """Eight processes, eight declarations. The whole point.

    Without serialisation this loses writes: each process reads the same state, adds its own
    component, and the last write back wins.
    """
    Workspace.create(tmp_path)

    workers = [_spawn(tmp_path, index) for index in range(WORKERS)]
    failures = []
    for worker in workers:
        _out, err = worker.communicate(timeout=120)
        if worker.returncode != 0:
            failures.append(err.strip().splitlines()[-1] if err.strip() else "unknown")

    assert not failures, f"workers failed: {failures}"

    registered = {str(ref.component_id) for ref in Workspace.open(tmp_path).components}
    assert registered == {f"component-{index}" for index in range(WORKERS)}


def test_the_lock_is_released_after_a_registration(tmp_path: Path) -> None:
    """A finished write leaves nothing behind for the next one to wait on."""
    space = Workspace.create(tmp_path)
    with Workspace.transaction(space) as t:
        t.register_component(_component("solo"))

    assert not (space.path.parent / WORKSPACE_LOCK_FILENAME).exists()


def test_a_stale_lock_does_not_block_forever(tmp_path: Path, monkeypatch) -> None:
    """A process that died holding the lock must not make the workspace permanently unwritable.

    The recovery must not be "delete a file we never told you about".
    """
    import vqapr.workspace as module

    space = Workspace.create(tmp_path)
    lock = space.path.parent / WORKSPACE_LOCK_FILENAME
    lock.write_text("99999", encoding="utf-8")

    monkeypatch.setattr(module, "WORKSPACE_LOCK_STALE_AFTER", 0.0)

    with Workspace.transaction(space) as t:
        t.register_component(_component("after-stale"))

    assert [str(ref.component_id) for ref in Workspace.open(tmp_path).components] == [
        "after-stale"
    ]


def test_a_held_lock_fails_loudly_rather_than_hanging(tmp_path: Path, monkeypatch) -> None:
    """Waiting forever behind a holder that never finishes is not an option a user can debug."""
    import vqapr.workspace as module
    from vqapr.domain.errors import VqaprError

    space = Workspace.create(tmp_path)
    (space.path.parent / WORKSPACE_LOCK_FILENAME).write_text("1", encoding="utf-8")

    monkeypatch.setattr(module, "WORKSPACE_LOCK_TIMEOUT", 0.05)
    monkeypatch.setattr(module, "WORKSPACE_LOCK_STALE_AFTER", 1e9)

    with pytest.raises(VqaprError, match="locked"), Workspace.transaction(space) as t:
        t.register_component(_component("blocked"))
