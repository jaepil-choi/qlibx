"""`run` refuses what `check` refuses, in the same codes, for both spec kinds.

The defect this closes (`docs/issues/015`): the eight judgments lived only in `check`, so a spec
with a real look-ahead -- a fill at 15:30 with decisions at or after it -- was refused by `check`
and executed by `run`. The run then wrote a permanent record that `vqapr list runs` shows beside
legitimate runs with nothing marking it, and no command deletes a run. A reader could not tell.

The property under test is the sentence the reporter wanted to be able to say and could not:
*`check` and `run` enforce the same rules, so a green `run` means what a green `check` means.*
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from test_commands import _cli, _spec, _workspace_for_run

from vqapr.cli.check import check


def _run(capsys: pytest.CaptureFixture[str], root: Path, spec: Path) -> tuple[int, dict]:
    return _cli(capsys, "--project-root", str(root), "run", str(spec))


def test_a_spec_check_refuses_is_not_executed_by_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The headline. A look-ahead refused by `check` must not produce a run record.

    This is the exact shape issue 015 was filed on: `check` said no, `run` said yes, and the
    artifact was indistinguishable from a good one afterwards.
    """
    _workspace_for_run(tmp_path, capsys)
    spec = _spec(tmp_path, start="2024-03-05", end="2024-03-07")

    judged = check(spec, tmp_path)
    assert judged["ok"] is False, "fixture must be a spec check actually refuses"
    refused_codes = {failure["code"] for failure in judged["failures"]}

    code, payload = _run(capsys, tmp_path, spec)

    assert code == 1, "run executed a spec check refuses"
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
    spec = _spec(tmp_path, start="2024-03-05", end="2024-03-07")

    _, payload = _run(capsys, tmp_path, spec)
    failure = payload["failures"][0]

    for field in ("code", "source", "requirement", "observed", "fix", "explain"):
        assert field in failure, f"the refusal dropped {field!r}"
        assert failure[field] not in (None, "", {}), f"{field!r} is present but empty"

    assert failure["code"].startswith("check."), (
        "run invented its own code instead of reusing the one check publishes"
    )
    assert failure["explain"] == "run-precondition"


def test_run_refuses_when_a_judgment_could_not_answer(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Blocked is not a pass.

    `check` computes `ok` as `not failures and not blocked`, so a judgment that could not LOOK
    makes it refuse. If `run` refused only on the answered-no list, a spec nothing was proven
    about would run to completion -- issue 015's divergence reproduced inside its own fix.
    """
    _workspace_for_run(tmp_path, capsys)
    spec = _spec(tmp_path)

    assert check(spec, tmp_path)["ok"] is True, "fixture must otherwise pass"

    import vqapr.flow.judgments as judgments_module

    def _cannot_look(*_args: object, **_kwargs: object) -> None:
        raise KeyError("a judgment read a key nobody wrote")

    monkeypatch.setattr(judgments_module, "_judge_universe", _cannot_look)

    code, payload = _run(capsys, tmp_path, spec)

    assert code == 1, "run executed a spec whose judgment could not answer"
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

    A spec carrying several defects must produce several refusals in one call, or the reader is
    back to fixing one thing per round trip.
    """
    _workspace_for_run(tmp_path, capsys)
    spec = _spec(tmp_path, start="2024-03-07T00:00:00+09:00", end="2024-03-05T00:00:00+09:00")
    document = yaml.safe_load(spec.read_text(encoding="utf-8"))
    document["instruments"] = []
    spec.write_text(yaml.safe_dump(document), encoding="utf-8")

    _, payload = _run(capsys, tmp_path, spec)
    codes = {failure["code"] for failure in payload["failures"]}

    assert {"check.universe.absent", "check.period.uncovered"} <= codes, codes


def test_a_refused_run_writes_no_record(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The permanent artifact is the actual harm, so prove none is produced.

    Issue 015's cost was not the wrong answer alone; it was that the wrong answer sat in the store
    forever, looking exactly like a right one, with no command to remove it.
    """
    _workspace_for_run(tmp_path, capsys)
    spec = _spec(tmp_path, start="2024-03-05", end="2024-03-07")

    _, before = _cli(capsys, "--project-root", str(tmp_path), "list", "runs")
    _run(capsys, tmp_path, spec)
    _, after = _cli(capsys, "--project-root", str(tmp_path), "list", "runs")

    assert json.dumps(after, sort_keys=True) == json.dumps(before, sort_keys=True), (
        "a refused run left something behind in the run store"
    )


def test_a_spec_check_passes_still_runs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The other half of parity, and the one that keeps this from being a wall.

    Adding a gate that refuses everything would satisfy every assertion above and destroy the
    product. A spec `check` certifies must still execute.
    """
    _workspace_for_run(tmp_path, capsys)
    spec = _spec(tmp_path)

    assert check(spec, tmp_path)["ok"] is True

    code, payload = _run(capsys, tmp_path, spec)

    assert code == 0, payload
    assert payload["ok"] is True
    assert payload["stage"] == "run.complete"
