"""A finished run must not be discarded because its roster pointer went bad after it finished.

**This file exists because record `113` claimed it and it did not exist.** The fix for R1 — the most
severe finding of the Step 7 review — shipped with the record asserting "two tests" that were never
written: the heredoc that was supposed to append them failed with `Bad file descriptor`, the file's
pre-existing parametrised count of 7 was mistaken for evidence they had landed, and nothing
exercised the fix. An independent architecture review of VB002 caught it. Record `115` writes the
tests and corrects record `113`'s validation table.

## The defect R1 fixed

`roster_report(...)` was evaluated **as an argument inside `run`'s `try`**. It re-reads the roster
pointer, so a pointer corrupted during the run — a crash mid-write, a concurrent `vqapr register`, a
hand edit — makes it raise. `flow.run()` returns successfully, then this throws, `freeze_record` is
never entered, the writer releases, and the exception propagates: no rows, no `record.json`, the run
id freed for a peer, exit 1. **A multi-hour computation discarded because one small JSON file went
bad after it was no longer needed.**

## The second defect, which this file also pins

R1's first fix absorbed the failure as `None`. Both `flow/records.py` and `flow/run_records.py`
define `roster: null` as *"the run never knew the categories"* — but `run` calls `registered_roster`
**before** `flow.run()` and that refuses an unreadable pointer outright, so any run reaching the
record did read its roster. `None` would write a falsehood into the frozen artifact. The marker says
what happened instead.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import vqapr.run.assemble as orchestration
from vqapr.domain.errors import Failure, Stage, Status, VqaprError
from vqapr.run.assemble import _roster_report_or_stale
from vqapr.workspace.registry import Workspace


def _unreadable(*_args: object, **_kwargs: object) -> object:
    raise VqaprError(
        stage=Stage.READ,
        failures=[
            Failure.bounded(
                "roster.unreadable",
                "the registered instrument roster pointer must be readable JSON",
                status=Status.UNAVAILABLE,
                observed="instruments.json: broken",
                fix="re-register the roster",
            )
        ],
        mutation=False,
        retry_precondition="re-register the instrument roster, then retry",
    )


def test_a_roster_that_breaks_after_the_run_does_not_cost_the_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The severe half. A refusal here must not propagate, because the run already succeeded."""
    Workspace.create(tmp_path)
    monkeypatch.setattr(orchestration, "roster_report", _unreadable)

    # Must not raise. Before R1 this refusal escaped and took the whole record with it.
    block = _roster_report_or_stale(None)

    assert block is not None, (
        "a run that read its roster at start must not be recorded as having read none"
    )


def test_the_record_says_stale_rather_than_claiming_the_run_knew_no_roster(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The encoding. `null` in this field means something specific and false here.

    `run` refuses an unreadable pointer at start, so a run reaching the record **did** read its
    roster. Recording `null` would state the opposite in the artifact a later cold process reads,
    while the ephemeral CLI envelope stated the truth — the two disagreeing about the same run.
    """
    Workspace.create(tmp_path)
    monkeypatch.setattr(orchestration, "roster_report", _unreadable)

    block = _roster_report_or_stale(None)

    assert isinstance(block, dict)
    assert block["known"] is True, "the run did read its roster; the record must not deny it"
    assert block["stale"] is True, "and must say the categories are no longer recoverable"
    assert "roster.unreadable" in str(block["note"]), (
        "the note must carry the underlying refusal so a reader can act on the real cause"
    )


def test_a_programming_error_still_escapes(monkeypatch: pytest.MonkeyPatch) -> None:
    """The other half of R1's fix: the absorber catches `VqaprError` ONLY.

    A bare `except Exception` here would be the over-broad catch `docs/issues/archive/042` exists to
    prevent — it would swallow a bug in report construction and record a stale marker for it,
    which is a defect reported as a damaged file.
    """

    def bug(*_args: object, **_kwargs: object) -> object:
        raise TypeError("a bug in report construction, not a damaged file")

    monkeypatch.setattr(orchestration, "roster_report", bug)

    with pytest.raises(TypeError, match="a bug in report construction"):
        _roster_report_or_stale(None)


def test_a_healthy_roster_is_passed_through_untouched(monkeypatch: pytest.MonkeyPatch) -> None:
    """The absorber must be invisible on the ordinary path."""
    expected = {"known": True, "tables": ["etf"], "counts": {"etf": 3}}
    monkeypatch.setattr(orchestration, "roster_report", lambda *_a, **_k: expected)

    assert _roster_report_or_stale(None) is expected


def test_the_report_is_computed_outside_the_guard_that_releases_the_run_id() -> None:
    """The structural property, read off the source so it cannot regress silently.

    The defect was not the absence of a `try` — it was that `roster_report` was evaluated as an
    ARGUMENT inside one. A future edit that inlines it back into the `freeze_record(...)` call
    reintroduces R1 exactly, and every behavioural test above would still pass, because they call
    the helper directly.
    """
    source = Path("src/vqapr/run/assemble.py").read_text(encoding="utf-8")

    assert "_roster_report_or_stale(roster)" in source
    assert "freeze_record(writer, result, frozen, as_loaded, roster_report(" not in source, (
        "roster_report is being evaluated inside the guard again; a refusal there discards a "
        "completed run's entire record (R1)"
    )
