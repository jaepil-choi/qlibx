"""`run` refuses what `check` refuses, in the same codes, for a registered run.

The defect this closes (`docs/issues/015`): the eight judgments lived only in `check`, so a run
with a real look-ahead -- a fill at 15:30 with decisions at or after it -- was refused by `check`
and executed by `run`. The run then wrote a permanent record that `vqapr list runs` shows beside
legitimate runs with nothing marking it, and no command deletes a run. A reader could not tell.

The property under test is the sentence the reporter wanted to be able to say and could not:
*`check` and `run` enforce the same rules, so a green `run` means what a green `check` means.*

A run is a registered declaration since record 139, so the defects here are ones a REGISTERED run
can carry: `register` already refuses a reversed period and a bare date, and those never reach
either verb. What registration accepts and the judgments refuse is the look-ahead itself, and an
account whose declared mode contradicts its opening positions.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_commands import _cli, _register_run, _workspace_for_run

from vqapr.cli.check import check


def _run(capsys: pytest.CaptureFixture[str], root: Path, run_id: str) -> tuple[int, dict]:
    return _cli(capsys, "--project-root", str(root), "run", run_id)


def _lookahead_run(
    root: Path, capsys: pytest.CaptureFixture[str], run_id: str, **overrides: object
) -> None:
    """A registered run whose strategy decides AT the fill instant: the shape of issue 015.

    The run's own `at` is the decision time (record 148), so the look-ahead is one key: `15:30`
    coincides with the workspace's fill at 15:30, which is exactly what
    `check.execution.not_after_decision` refuses -- and `register` accepts, since every id the
    run names is registered and a wall time is not a reference it can check.
    """
    code, payload = _register_run(root, capsys, run_id, at="15:30", **overrides)
    assert code == 0, payload


def test_a_run_check_refuses_is_not_executed_by_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The headline. A look-ahead refused by `check` must not produce a run record.

    This is the exact shape issue 015 was filed on: `check` said no, `run` said yes, and the
    artifact was indistinguishable from a good one afterwards.
    """
    _workspace_for_run(tmp_path, capsys)
    _lookahead_run(tmp_path, capsys, "lookahead")

    judged = check("lookahead", tmp_path)
    assert judged["ok"] is False, "fixture must be a run check actually refuses"
    refused_codes = {failure["code"] for failure in judged["failures"]}
    assert "check.execution.not_after_decision" in refused_codes, refused_codes

    code, payload = _run(capsys, tmp_path, "lookahead")

    assert code == 1, "run executed a run check refuses"
    assert payload["ok"] is False
    run_codes = {failure["code"] for failure in payload["failures"]}
    assert run_codes & refused_codes, (
        f"run refused for different reasons than check: run={run_codes} check={refused_codes}"
    )


def test_the_refusal_carries_the_six_fields_in_checks_own_codes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Not a bare 'judgments failed'. The same envelope, and the same code, as `check` publishes.

    Re-coding into a `run.*` namespace would rename a defect the reader may already have handling
    for, which is the opposite of the parity this closes.
    """
    _workspace_for_run(tmp_path, capsys)
    _lookahead_run(tmp_path, capsys, "lookahead")

    _, payload = _run(capsys, tmp_path, "lookahead")
    failure = payload["failures"][0]

    for field in ("code", "source", "requirement", "observed", "fix", "explain"):
        assert field in failure, f"the refusal dropped {field!r}"
        assert failure[field] not in (None, "", {}), f"{field!r} is present but empty"

    assert failure["code"].startswith("check."), (
        "run invented its own code instead of reusing the one check publishes"
    )
    assert failure["explain"] == "run-precondition"
    # A registered run has no file to point at; the key path into the declaration is its location.
    assert failure["source"]["file"] is None
    assert failure["source"]["key_path"].startswith("runs.lookahead")


def test_run_refuses_when_a_judgment_could_not_answer(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Blocked is not a pass.

    `check` computes `ok` as `not failures and not blocked`, so a judgment that could not LOOK
    makes it refuse. If `run` refused only on the answered-no list, a run nothing was proven
    about would run to completion -- issue 015's divergence reproduced inside its own fix.
    """
    _workspace_for_run(tmp_path, capsys)

    assert check("r1", tmp_path)["ok"] is True, "fixture must otherwise pass"

    import vqapr.flow.judgments as judgments_module

    def _cannot_look(*_args: object, **_kwargs: object) -> None:
        raise KeyError("a judgment read a key nobody wrote")

    monkeypatch.setattr(judgments_module, "_judge_universe", _cannot_look)

    code, payload = _run(capsys, tmp_path, "r1")

    assert code == 1, "run executed a run whose judgment could not answer"
    codes = {failure["code"] for failure in payload["failures"]}
    assert "run.check.judgment_blocked" in codes, codes
    blocked = next(
        failure
        for failure in payload["failures"]
        if failure["code"] == "run.check.judgment_blocked"
    )
    assert "universe" in blocked["observed"]
    assert "KeyError" in blocked["observed"]


def test_every_independent_defect_is_reported_not_just_the_first(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Independence survives the move into `run`.

    A run carrying several defects must produce several refusals in one call, or the reader is
    back to fixing one thing per round trip. Two defects registration cannot see: a decision at
    the fill instant, and a long-only account that opens short.
    """
    _workspace_for_run(tmp_path, capsys)
    _lookahead_run(
        tmp_path, capsys, "twice-wrong",
        initial_account={"cash": "1000", "mode": "long_only", "positions": {"A": "-1"}},
    )

    _, payload = _run(capsys, tmp_path, "twice-wrong")
    codes = {failure["code"] for failure in payload["failures"]}

    assert {"check.execution.not_after_decision", "check.weights.mode_conflict"} <= codes, codes


def test_a_refused_run_writes_no_record(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The permanent artifact is the actual harm, so prove none is produced.

    Issue 015's cost was not the wrong answer alone; it was that the wrong answer sat in the store
    forever, looking exactly like a right one, with no command to remove it. `list runs` reports
    each registered run beside the strategy records the store holds for it, so an unchanged
    listing means no record landed.
    """
    _workspace_for_run(tmp_path, capsys)
    _lookahead_run(tmp_path, capsys, "lookahead")

    _, before = _cli(capsys, "--project-root", str(tmp_path), "list", "runs")
    assert [row["recorded"] for row in before["items"]] == [[], []], before
    _run(capsys, tmp_path, "lookahead")
    _, after = _cli(capsys, "--project-root", str(tmp_path), "list", "runs")

    assert json.dumps(after, sort_keys=True) == json.dumps(before, sort_keys=True), (
        "a refused run left something behind in the run store"
    )
    assert not (tmp_path / ".vqapr" / "runs" / "lookahead").exists()


def test_a_run_check_passes_still_runs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The other half of parity, and the one that keeps this from being a wall.

    Adding a gate that refuses everything would satisfy every assertion above and destroy the
    product. A run `check` certifies must still execute.
    """
    _workspace_for_run(tmp_path, capsys)

    assert check("r1", tmp_path)["ok"] is True

    code, payload = _run(capsys, tmp_path, "r1")

    assert code == 0, payload
    assert payload["ok"] is True
    assert payload["stage"] == "run.complete"
