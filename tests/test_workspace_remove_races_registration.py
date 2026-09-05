"""`Workspace.remove()` checked its references outside the lock it then took.

`docs/issues/043`. The sequence was:

    blockers = self.references_to(kind, identity)   # its own _read(), no lock
    if blockers:
        raise ...
    with self._exclusive():                        # the lock starts HERE
        state = self._read()
        ...

Two reads, no lock across them. A second process that registers a declaration naming the target in
that window loses: the removal proceeds on a reference list that was already stale.

**The result is worse than a lost update.** The document reader validates forward references, so a
document holding a run that names a component nobody registered does not merely carry a dangling
pointer -- `Workspace.open()` **raises**, and every command in the project fails until the file is
hand-repaired. Two ordinary concurrent commands produce a workspace no command can open.

The interleaving here is forced rather than hoped for. `_exclusive` is wrapped so the competing
registration runs and commits at the moment the remover is about to take the lock -- after the
pre-check in the old code, before the lock in both. The competing writer takes the lock properly, so
this is a race between two well-behaved callers, not a test that cheats by writing behind the lock's
back.

The competing declaration is a run (record `148`): the per-strategy binding that used to be
registered is derived from the run now, so a run is what names a component.
"""

from __future__ import annotations

import threading
from datetime import date, time
from decimal import Decimal
from pathlib import Path

import pytest

from vqapr.domain.errors import VqaprError
from vqapr.extension.component import ComponentKind, ComponentRef
from vqapr.extension.fingerprint import fingerprint_component
from vqapr.public import AccountMode, AccountSnapshot, RunDefinition, StrategyEntry
from vqapr.workspace import Workspace

pytestmark = pytest.mark.concurrency

ZONE = "Asia/Seoul"


def _seed(tmp_path: Path) -> Workspace:
    """A workspace holding a component, with nothing yet referencing it."""
    workspace = Workspace.create(tmp_path)
    source = tmp_path / "alpha.py"
    source.write_text("class S:\n    pass\n", encoding="utf-8")
    workspace.register_component(
        ComponentRef(
            component_id="alpha",
            kind=ComponentKind.STRATEGY_MODEL,
            path=source,
            object_name="S",
            config={},
            fingerprint=fingerprint_component(
                source, kind=ComponentKind.STRATEGY_MODEL, object_name="S", config={}
            ),
        )
    )
    return workspace


def _run_naming_alpha() -> RunDefinition:
    return RunDefinition(
        run_id="cadence",
        strategies=(StrategyEntry("alpha"),),
        instruments=("A",),
        timezone=ZONE,
        at=time(9, 0),
        sessions=(date(2026, 4, 1),),
        initial_account_snapshot=AccountSnapshot(0, Decimal("1000"), {}),
        initial_account_mode=AccountMode.LONG_ONLY,
    )


def test_a_removal_and_a_registration_cannot_produce_an_unopenable_workspace(
    tmp_path: Path,
) -> None:
    """The race, forced deterministically.

    Fails on the pre-fix code: the removal's reference check runs before the lock, the competing
    registration commits inside that window, and the removal then deletes a component the freshly
    registered run names. `Workspace.open()` refuses the result.
    """
    workspace = _seed(tmp_path)
    competitor = Workspace.open(tmp_path)
    interfered = threading.Event()
    failed: list[BaseException] = []

    def register_the_reference() -> None:
        """A second, entirely well-behaved caller. It takes the lock like anyone else."""
        try:
            competitor.register_run(_run_naming_alpha())
        except BaseException as error:
            failed.append(error)
        finally:
            interfered.set()

    original = type(workspace)._exclusive
    armed = {"fired": False}

    def racing_exclusive(self):  # type: ignore[no-untyped-def]
        """Run the competing registration at the instant before the lock is taken.

        Hooked here because this is the one point that exists in BOTH versions of `remove`: after
        the old code's unlocked pre-check, and before either version holds the lock. The competitor
        needs the lock itself, so it must run while the remover does not hold it -- which is
        exactly the window under test.

        `armed` is set BEFORE the thread starts, not after it finishes. The patch is on the class,
        so the competitor's own `register_run` re-enters this same wrapper; a guard that only
        closed once the registration completed would recurse until the process ran out of file
        descriptors.
        """
        if not armed["fired"]:
            armed["fired"] = True
            worker = threading.Thread(target=register_the_reference)
            worker.start()
            worker.join(timeout=30)
        return original(self)

    workspace.__class__._exclusive = racing_exclusive  # type: ignore[method-assign]
    try:
        removal_refused = False
        try:
            workspace.remove("component", "alpha")
        except VqaprError:
            removal_refused = True
    finally:
        workspace.__class__._exclusive = original  # type: ignore[method-assign]

    assert not failed, f"the competing registration itself failed: {failed}"
    assert interfered.is_set(), "the interleaving never happened; the test proves nothing"

    # The invariant, stated independently of which side won. Whether the removal is refused or the
    # registration is, the workspace on disk must still open.
    try:
        reopened = Workspace.open(tmp_path)
    except VqaprError as broken:  # pragma: no cover - this is the failure being fixed
        pytest.fail(
            "two well-behaved concurrent commands produced a workspace that will not open, "
            f"which no later command can recover from: {broken}"
        )

    if removal_refused:
        assert reopened.component("alpha") is not None, (
            "the removal was refused, so the component it protects must still be registered"
        )
    else:
        assert not reopened.run_definitions, (
            "the component was removed, so nothing may still name it"
        )


def test_the_reference_check_and_the_write_see_one_snapshot(tmp_path: Path) -> None:
    """The mechanism, asserted directly rather than only through its symptom.

    `remove` must not read the workspace twice with a gap between the reads. One read inside the
    lock is what makes the check and the write agree.
    """
    workspace = _seed(tmp_path)
    reads_outside_the_lock: list[int] = []
    holding = {"locked": False}

    original_read = type(workspace)._read
    original_exclusive = type(workspace)._exclusive

    def counting_read(self):  # type: ignore[no-untyped-def]
        if not holding["locked"]:
            reads_outside_the_lock.append(1)
        return original_read(self)

    def tracking_exclusive(self):  # type: ignore[no-untyped-def]
        import contextlib

        @contextlib.contextmanager
        def wrapper():  # type: ignore[no-untyped-def]
            with original_exclusive(self):
                holding["locked"] = True
                try:
                    yield
                finally:
                    holding["locked"] = False

        return wrapper()

    workspace.__class__._read = counting_read  # type: ignore[method-assign]
    workspace.__class__._exclusive = tracking_exclusive  # type: ignore[method-assign]
    try:
        workspace.remove("component", "alpha")
    finally:
        workspace.__class__._read = original_read  # type: ignore[method-assign]
        workspace.__class__._exclusive = original_exclusive  # type: ignore[method-assign]

    assert not reads_outside_the_lock, (
        "remove() read the workspace outside its own lock, which is the gap a competing writer "
        "commits into; the reference check must run against the state the lock already read"
    )
