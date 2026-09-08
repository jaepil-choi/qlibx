"""Adversarial attack on claim 3: `new --dataset <unregistered>` refuses and creates NO file.

Attacked at every `--out` shape that could plausibly race the refusal:
- `--out` pointing at a directory that does not exist (so `mkdir(parents=True)` would need to run
  before the write could succeed -- does the refusal happen before or after that side effect?)
- `--out` pointing at a path that already exists (two refusal reasons compete: unregistered
  dataset vs. existing file -- does either one still avoid writing?)
- `--out` pointing at a directory with no write permission (a refusal from the OS itself, not
  from `InputError` -- does that still leave no file behind, or does a partial write land before
  the permission error surfaces?)
- the `.py`/`.yaml` pairing: an unregistered dataset PLUS an already-existing sibling file, to
  make sure the earliest-possible refusal (`_require_registered_dataset`, which runs before any
  path is touched) really does run first.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from vqapr.cli.main import main
from vqapr.workspace import Workspace


def _cli(
    capsys: pytest.CaptureFixture[str], project_root: Path, *argv: str
) -> tuple[int, dict[str, Any]]:
    code = main(["--project-root", str(project_root), *argv])
    out = capsys.readouterr().out.strip()
    return code, json.loads(out.splitlines()[-1])


def test_unregistered_dataset_with_out_in_a_nonexistent_directory_creates_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--out` names a parent directory that does not exist yet.

    If the refusal ran AFTER `target.parent.mkdir(parents=True, exist_ok=True)`, the directory
    itself would be a side effect of a command that is supposed to write nothing on refusal.
    """
    Workspace.create(tmp_path)
    bad_out = tmp_path / "does_not_exist_yet" / "component.py"

    code, payload = _cli(
        capsys, tmp_path,
        "new", "strategy", "my-alpha", "--dataset", "never-registered", "--out", str(bad_out),
    )

    assert code == 1, payload
    assert payload["failures"][0]["code"] == "argument.value_invalid"
    assert not bad_out.parent.exists(), (
        "the parent directory was created despite the dataset refusal never producing a file"
    )
    assert not bad_out.exists()
    assert not bad_out.with_suffix(".yaml").exists()


def test_unregistered_dataset_with_out_already_existing_creates_nothing_new(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--out` names a path that already exists. Two refusal reasons compete; both must hold."""
    Workspace.create(tmp_path)
    existing = tmp_path / "already_here.py"
    existing.write_text("PRE-EXISTING CONTENT", encoding="utf-8")

    code, payload = _cli(
        capsys, tmp_path,
        "new", "strategy", "my-beta", "--dataset", "never-registered", "--out", str(existing),
    )

    assert code == 1, payload
    # The dataset check runs first (`_require_registered_dataset` is called before any path
    # logic), so the reported code names the dataset problem, not the file-exists problem --
    # but regardless of WHICH refusal fires, the existing file must be untouched.
    assert payload["failures"][0]["code"] == "argument.value_invalid"
    assert existing.read_text(encoding="utf-8") == "PRE-EXISTING CONTENT"
    assert not existing.with_suffix(".yaml").exists()


@pytest.mark.skipif(os.name != "nt", reason="icacls permission denial is Windows-specific")
def test_unregistered_dataset_with_out_in_an_unwritable_directory_creates_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--out` names a directory this process cannot write to.

    Since the dataset refusal fires before any filesystem write is attempted, the permission
    denial should never even be reached -- but this proves that, rather than assuming it.
    """
    Workspace.create(tmp_path)
    readonly_dir = tmp_path / "readonly"
    readonly_dir.mkdir()
    target = readonly_dir / "component.py"
    user = os.getlogin()
    subprocess.run(
        ["icacls", str(readonly_dir), "/deny", f"{user}:(W)"],
        capture_output=True,
        check=False,
    )
    try:
        code, payload = _cli(
            capsys, tmp_path,
            "new", "strategy", "my-gamma", "--dataset", "never-registered", "--out", str(target),
        )
        assert code == 1, payload
        assert payload["failures"][0]["code"] == "argument.value_invalid"
        assert not target.exists()
    finally:
        subprocess.run(
            ["icacls", str(readonly_dir), "/remove:d", user],
            capture_output=True,
            check=False,
        )


def test_the_dataset_refusal_runs_before_any_path_logic_at_all(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Confirms ordering directly: `_require_registered_dataset` is checked before `--out` is
    even resolved to a default. No component_id-derived default path should appear either.
    """
    Workspace.create(tmp_path)
    code, payload = _cli(
        capsys, tmp_path,
        "new", "strategy", "totally-unregistered-alpha", "--dataset", "never-registered",
    )

    assert code == 1, payload
    assert payload["failures"][0]["code"] == "argument.value_invalid"
    assert "never-registered" in payload["failures"][0]["observed"]
    # The default path this command would have used had the dataset been registered.
    default_target = tmp_path / "totally_unregistered_alpha.py"
    assert not default_target.exists()
    assert not default_target.with_suffix(".yaml").exists()


def test_refusal_reports_registered_ids_or_none_registered(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The refusal's `observed` field must actually be useful, not merely present.

    A refusal that says "invalid" without naming what IS registered forces a second round trip
    (`vqapr list datasets`) just to learn the answer this command already knows.
    """
    Workspace.create(tmp_path)
    code, payload = _cli(
        capsys, tmp_path,
        "new", "strategy", "my-delta", "--dataset", "never-registered",
    )
    assert code == 1
    observed = payload["failures"][0]["observed"]
    assert "registered:" in observed
    assert "(none registered)" in observed, (
        f"an empty workspace's refusal did not say so plainly: {observed!r}"
    )
