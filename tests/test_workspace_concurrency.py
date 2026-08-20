"""Parallel registration does not lose declarations.

Running strategies in parallel is the normal case for a loop-based engine, not an edge one. The
workspace write was already atomic -- a temporary file replaced into place -- but atomicity only
guarantees a reader never sees half a file. It does not stop two processes from each reading the
same state, each adding one declaration, and the second write erasing the first.

Nothing fails when that happens. A declaration is simply gone, and the run that needed it reports
a missing reference somewhere unrelated.

These tests use real processes. Threads would share an interpreter and could pass while the
cross-process case still lost writes.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from datetime import date, time
from pathlib import Path

import pytest

from vqapr.domain.timestamps import LocalInstantDeclaration
from vqapr.public import Workspace
from vqapr.runtime.agendas import OperationAgenda, OperationOccurrence, OperationRole
from vqapr.workspace import WORKSPACE_LOCK_FILENAME


def _agenda(raw_id: str) -> OperationAgenda:
    return OperationAgenda.from_occurrences(
        agenda_id=raw_id,
        role=OperationRole.STRATEGY_CALLBACK,
        timezone="Asia/Seoul",
        occurrences=(
            OperationOccurrence(
                f"{raw_id}-1",
                OperationRole.STRATEGY_CALLBACK,
                LocalInstantDeclaration(date(2024, 3, 5), time(4, 0), "Asia/Seoul", 0, "+09:00"),
            ),
        ),
        provenance="concurrency probe",
    )


WORKERS = 8

WORKER = textwrap.dedent(
    """
    import sys
    from datetime import date, time
    from vqapr.public import Workspace
    from vqapr.domain.timestamps import LocalInstantDeclaration
    from vqapr.runtime.agendas import OperationAgenda, OperationOccurrence, OperationRole

    project, index = sys.argv[1], sys.argv[2]
    occurrence = OperationOccurrence(
        f"occ-{index}",
        OperationRole.STRATEGY_CALLBACK,
        LocalInstantDeclaration(date(2024, 3, 5), time(4, 0), "Asia/Seoul", 0, "+09:00"),
    )
    agenda = OperationAgenda.from_occurrences(
        agenda_id=f"agenda-{index}",
        role=OperationRole.STRATEGY_CALLBACK,
        timezone="Asia/Seoul",
        occurrences=(occurrence,),
        provenance="concurrency probe",
    )
    Workspace.create(project).register_agenda(agenda)
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
    agenda, and the last write back wins.
    """
    Workspace.create(tmp_path)

    workers = [_spawn(tmp_path, index) for index in range(WORKERS)]
    failures = []
    for worker in workers:
        _out, err = worker.communicate(timeout=120)
        if worker.returncode != 0:
            failures.append(err.strip().splitlines()[-1] if err.strip() else "unknown")

    assert not failures, f"workers failed: {failures}"

    registered = {agenda.agenda_id for agenda in Workspace.open(tmp_path).agendas}
    assert registered == {f"agenda-{index}" for index in range(WORKERS)}


def test_the_lock_is_released_after_a_registration(tmp_path: Path) -> None:
    """A finished write leaves nothing behind for the next one to wait on."""
    space = Workspace.create(tmp_path)
    space.register_agenda(_agenda("solo"))

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

    space.register_agenda(_agenda("after-stale"))

    assert [agenda.agenda_id for agenda in Workspace.open(tmp_path).agendas] == ["after-stale"]


def test_a_held_lock_fails_loudly_rather_than_hanging(tmp_path: Path, monkeypatch) -> None:
    """Waiting forever behind a holder that never finishes is not an option a user can debug."""
    import vqapr.workspace as module
    from vqapr.domain.errors import VqaprError

    space = Workspace.create(tmp_path)
    (space.path.parent / WORKSPACE_LOCK_FILENAME).write_text("1", encoding="utf-8")

    monkeypatch.setattr(module, "WORKSPACE_LOCK_TIMEOUT", 0.05)
    monkeypatch.setattr(module, "WORKSPACE_LOCK_STALE_AFTER", 1e9)

    with pytest.raises(VqaprError, match="locked"):
        space.register_agenda(_agenda("blocked"))
