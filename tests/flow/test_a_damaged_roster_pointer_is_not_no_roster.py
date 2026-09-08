"""A registered roster whose pointer is damaged is refused, not read as "no roster".

`docs/issues/042`, found by the structural audit in
`docs/diagnostics/2026-08-31-vqapr-structural-refactoring.md` (C1).

`Workspace.registered_instruments()` raises a typed `workspace.instruments.unreadable` for a
damaged pointer, and says why in its own docstring: *"'no roster' and 'a roster whose record is
damaged' are different states, and only the first is ordinary."*

Two callers on the run path caught `Exception` around it and returned `None`. (Both lived in
`vqapr.public` as `_registered_roster` and `roster_report` until record `111` moved them to
`vqapr.flow.roster` and made the first one public; the defect and its fix are unchanged.) `None` means **no
roster registered** -- a legal, ordinary state -- so a truncated `.vqapr/instruments.json` made a
run complete with `ok: true`, `roster: null`, and every fill recording `kind: None`. On a KRX-shaped
venue that charges the ETF sleeve at the share rate, which is exactly the defect `docs/issues/007`
closed, returning silently through a `try/except` written for a different case.

The comment three lines below the swallow said *"A REGISTERED roster that cannot be read is refused,
not degraded."* It was true of the roster TABLES and false of the pointer that names them.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from vqapr.domain.errors import VqaprError
from vqapr.domain.instruments import export_roster
from vqapr.public import registered_roster, roster_report
from vqapr.project.store import Workspace


def _project_with_a_roster(tmp_path: Path) -> Path:
    written = export_roster({"A005930": "stock", "A069500": "etf"}, tmp_path / "roster")
    digest = hashlib.sha256()
    for _, path in sorted(written.items()):
        digest.update(Path(path).read_bytes())
    with Workspace.transaction(tmp_path) as t:
        t.register_instruments(
            {kind: path for kind, path in written.items()}, digest=digest.hexdigest()
        )
    return tmp_path


def test_an_absent_workspace_is_still_no_roster(tmp_path: Path) -> None:
    """The case the swallow was written for, which must keep working.

    A run assembled outside a workspace has no roster to find, and saying so by returning `None`
    is honest -- the refusal belongs where something asks what an instrument is.
    """
    assert registered_roster(tmp_path / "nowhere") is None
    assert roster_report(registered_roster(tmp_path / "nowhere")) is None


def test_a_registered_roster_still_loads(tmp_path: Path) -> None:
    """Guard the guard: a healthy roster must not be caught by the narrowed exception."""
    project = _project_with_a_roster(tmp_path)

    roster = registered_roster(project)

    assert roster is not None
    assert dict(roster.registry.histogram) == {"stock": 1, "etf": 1}
    assert roster_report(roster)["by_kind"] == {"stock": 1, "etf": 1}


@pytest.mark.parametrize(
    "damage",
    ['{"schema": "vqapr-instrum', "", "[]"],
    ids=["truncated", "empty", "wrong-shape"],
)
def test_a_damaged_pointer_refuses_rather_than_reading_as_absent(
    tmp_path: Path, damage: str
) -> None:
    """The defect itself: `None` here means a rosterless run, and this project has a roster."""
    project = _project_with_a_roster(tmp_path)
    pointer = Workspace.open(project).roster_path
    assert pointer.is_file(), "the fixture must have written a pointer to damage"
    pointer.write_text(damage, encoding="utf-8")

    with pytest.raises(VqaprError) as refused:
        registered_roster(project)

    assert refused.value.failures[0].code == "roster.unreadable", (
        "the typed refusal must reach the caller instead of becoming `no roster`"
    )

    # The envelope side never reads the pointer at all (`docs/issues/070`): `cli/run.py`'s
    # `_roster_envelope` is handed the roster the run READ (`RunResult.roster`), so a pointer
    # damaged after the run cannot change what the envelope says, and a pointer damaged before
    # it is the refusal above, at run start, before anything is spent. `None` here is the one
    # honest `known: false`: a run that read no roster because none was registered.
    from vqapr.cli.run import _roster_envelope

    assert _roster_envelope(None)["known"] is False
    assert "stale" not in _roster_envelope(None)


def test_a_run_that_never_registered_one_is_unaffected(tmp_path: Path) -> None:
    """A workspace with no roster at all is `None`, which is what `None` is reserved for."""
    Workspace.create(tmp_path)
    assert not (tmp_path / ".vqapr" / "instruments.json").exists()

    assert registered_roster(tmp_path) is None
    assert roster_report(registered_roster(tmp_path)) is None


def test_the_pointer_json_is_what_gets_damaged(tmp_path: Path) -> None:
    """Pin the file this test damages, so a relocation does not turn it into a no-op."""
    project = _project_with_a_roster(tmp_path)
    pointer = Workspace.open(project).roster_path

    assert pointer.name == "instruments.json"
    assert json.loads(pointer.read_text(encoding="utf-8"))["tables"]
