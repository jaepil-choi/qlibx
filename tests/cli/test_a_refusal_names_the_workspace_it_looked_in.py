"""`docs/issues/archive/066`: every envelope says which workspace it is about, and an implicit root
under an existing workspace is refused rather than silently started.

`vqapr register` run from `work/decl/` created `work/decl/.vqapr` beside the project's real
workspace; the next `check` refused for datasets registered five minutes earlier, and the
refusal named the cure ("register the missing datasets") without the place it had looked.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vqapr.cli.main import main


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, dict]:
    code = main(list(argv))
    out = capsys.readouterr().out.strip()
    return code, json.loads(out.splitlines()[-1])


def test_success_and_failure_envelopes_both_carry_the_workspace_root(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, ok = _run(capsys, "--project-root", str(tmp_path), "new", "compliance", "cap")
    assert code == 0, ok
    assert ok["workspace_root"] == str(tmp_path.resolve())

    code, refused = _run(capsys, "--project-root", str(tmp_path), "show", "model", "absent")
    assert code == 1
    assert refused["ok"] is False
    assert refused["workspace_root"] == str(tmp_path.resolve())


def test_an_implicit_root_beneath_a_workspace_is_refused_naming_both(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    code, _ = _run(capsys, "--project-root", str(tmp_path), "new", "compliance", "cap")
    assert code == 0
    code, _ = _run(
        capsys, "--project-root", str(tmp_path), "register", "compliance", "cap", str(tmp_path / "cap.py")
    )
    assert code == 0
    below = tmp_path / "work" / "decl"
    below.mkdir(parents=True)
    monkeypatch.chdir(below)

    code, refused = _run(capsys, "new", "compliance", "cap2")

    assert code == 1, refused
    failure = refused["failures"][0]
    assert str(tmp_path.resolve()) in failure["observed"] or str(tmp_path) in failure["observed"]
    assert "--project-root" in failure["fix"]
    assert not (below / ".vqapr").exists(), "nothing was started in the subdirectory"

    # Named explicitly, the same directory is honoured: a nested workspace on purpose.
    code, ok = _run(capsys, "--project-root", str(below), "new", "compliance", "cap2")
    assert code == 0, ok
    assert ok["workspace_root"] == str(below.resolve())


def test_an_implicit_root_with_no_workspace_anywhere_above_is_the_cwd(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    code, ok = _run(capsys, "new", "compliance", "cap")
    assert code == 0, ok
    assert ok["workspace_root"] == str(tmp_path.resolve())
