"""A damaged workspace is not "no roster", and the report describes the roster the run READ.

`docs/issues/archive/050`, the sibling of `docs/issues/archive/042` at the other door. 042 closed the guard around
the roster POINTER and its own closing text named what stayed open: *"only `Workspace.open` itself
is guarded."*

## Half one

`Workspace.open` decodes `.vqapr/workspace.yaml` and raises a typed `workspace.open.invalid` for a
file that is corrupt or half-written. Both readers on the run path wrapped it in `except Exception:
return None`, and `None` means **no roster is registered** -- a legal, ordinary state. So a
workspace damaged between preflight and `run()` made a project that HAS a roster read as one that
never had one: the run continued, every fill recorded `kind: None`, and on a KRX-shaped venue the
ETF sleeve was charged the share rate. That is `docs/issues/archive/007` returning through a `try/except`
written for an absent workspace.

## Half two

`roster_report`'s docstring claimed its answer came "from the roster already loaded for this run
rather than from a second read". That was true of `by_kind` and false of `digest` and `tables`,
which came from a second `registered_instruments()` -- the file as it stood minutes later. A
`vqapr register` landing mid-run made the frozen record carry the NEW roster's digest beside fills
classified by the OLD one, which is precisely the drift the `source_digest`/`declared_digest` pair
exists to expose.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import textwrap
from pathlib import Path

import pytest

from vqapr.cli.run import _roster_envelope
from vqapr.domain.errors import VqaprError
from vqapr.domain.instrument import export_roster
from vqapr.flow.roster import registered_roster, roster_report
from vqapr.project.store import Workspace

WHOLE_ROSTER = {"A005930": "stock", "A069500": "etf"}


def _register(project: Path, declared: dict[str, str], *, into: str) -> str:
    """Register `declared` as this project's roster, returning the digest recorded for it."""
    written = export_roster(declared, project / into)
    digest = hashlib.sha256()
    for _, path in sorted(written.items()):
        digest.update(Path(path).read_bytes())
    with Workspace.transaction(project) as t:
        t.register_instruments(
            {kind: path for kind, path in written.items()}, digest=digest.hexdigest()
        )
    return digest.hexdigest()


@pytest.mark.parametrize(
    "damage",
    ["datasets: [", "", "datasets: 3"],
    ids=["truncated", "empty", "wrong-shape"],
)
def test_a_damaged_workspace_refuses_rather_than_reading_as_no_roster(
    tmp_path: Path, damage: str
) -> None:
    """The defect itself: `None` here means a rosterless run, and this project has a roster."""
    _register(tmp_path, WHOLE_ROSTER, into="roster")
    workspace = Workspace.open(tmp_path).path
    assert workspace.is_file(), "the fixture must have written a workspace to damage"
    workspace.write_text(damage, encoding="utf-8")

    with pytest.raises(VqaprError) as refused:
        registered_roster(tmp_path)

    assert refused.value.failures[0].code in {"workspace.invalid", "workspace.unreadable"}, (
        "the typed refusal must reach the caller instead of becoming `no roster`"
    )


def test_the_envelope_reports_the_roster_the_run_read_whatever_happens_to_the_file(
    tmp_path: Path,
) -> None:
    """What the refusal buys, read off the envelope a user actually sees.

    `cli/run.py`'s `_roster_envelope` used to re-read the roster after the run and report
    `known: true, stale: true` when the workspace had become unreadable meanwhile. Since
    `docs/issues/archive/070` it is handed the roster the run READ (`RunResult.roster`) and reads
    nothing: a workspace damaged after the run cannot turn a known roster into `known: false`,
    nor into a stale marker -- the counts are the ones the fills were classified by.
    """
    digest = _register(tmp_path, WHOLE_ROSTER, into="roster")
    read = registered_roster(tmp_path)
    Workspace.open(tmp_path).path.write_text("datasets: [", encoding="utf-8")

    envelope = _roster_envelope(read)

    assert envelope["known"] is True, "this project registered a roster; the envelope must say so"
    assert "stale" not in envelope
    assert envelope["digest"] == digest
    assert envelope["by_kind"] == {"stock": 1, "etf": 1}


def test_an_absent_workspace_is_still_no_roster(tmp_path: Path) -> None:
    """The case the guard exists for, which the narrowing must leave untouched."""
    assert registered_roster(tmp_path / "nowhere") is None
    assert roster_report(registered_roster(tmp_path / "nowhere")) is None


def test_a_project_that_registered_no_roster_is_still_no_roster(tmp_path: Path) -> None:
    """A readable workspace with no roster is `None`, which is what `None` is reserved for."""
    Workspace.create(tmp_path)

    assert registered_roster(tmp_path) is None
    assert roster_report(registered_roster(tmp_path)) is None


def test_the_report_describes_the_roster_the_run_read_not_the_file_now(tmp_path: Path) -> None:
    """Half two: a `vqapr register` landing mid-run must not rewrite what the record reports.

    The digest and the per-category counts must describe ONE roster. Reading the pointer a second
    time made the record state the new roster's digest beside counts taken from the old one, and
    report the pair as a single consistent fact.
    """
    at_run_start = _register(tmp_path, WHOLE_ROSTER, into="roster")
    read = registered_roster(tmp_path)
    # `vqapr register <instruments>.yaml` lands while the run is still executing.
    mid_run = _register(tmp_path, {"A005930": "stock"}, into="roster-corrected")
    assert mid_run != at_run_start, "the fixture must actually move the roster underneath the run"

    report = roster_report(read)

    assert report is not None
    assert report["digest"] == at_run_start, (
        "the record must state the digest of the roster the fills were classified by"
    )
    assert report["by_kind"] == {"etf": 1, "stock": 1}
    assert report["tables"] == ["etf", "stock"], (
        "the table list must describe the same roster as the digest beside it"
    )
    assert report["instruments"] == 2


def test_the_report_does_not_read_the_pointer_a_second_time() -> None:
    """The structural property, so the second read cannot come back unnoticed.

    Read off the parse tree rather than the text, so a comment naming either call is free.
    """
    tree = ast.parse(textwrap.dedent(inspect.getsource(roster_report)))
    called = {
        ast.unparse(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)
    }

    assert not [name for name in called if "registered_instruments" in name], (
        "`roster_report` is reading the roster pointer again; its digest and tables must come "
        "from the read the run actually bound its categories to"
    )
    assert not [name for name in called if "Workspace.open" in name], (
        "`roster_report` is opening the workspace again; it is handed what the run read"
    )
