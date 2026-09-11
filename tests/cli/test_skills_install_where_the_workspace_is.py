"""The skills are installed where the workspace is, the root every other command works in.

Report 2026-09-11 (`docs/issues/report-2026-09-11-skill-install-writes-into-the-enclosing-
repositorys-git-root-not-the-project-that-installed-vqapr.md`): a project nested inside another
git repository ran `uv add vqapr` and `vqapr skill install`, and the ten skills landed in the
enclosing repository -- the nearest `.git` -- where an agent open in that unrelated repository
picked them up. The same walk refused a fresh folder with no `.git` at all, and from an unresolved
`--project-root .` it found nothing, since `Path(".")` has no parents.

The stale-skill note every other command prints already read the workspace root, so a skill
installed at the `.git` root was never checked. One root now serves both (record `258`).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vqapr.agent.skillset import MANIFEST_NAME
from vqapr.cli.main import main


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, dict, str]:
    code = main(list(argv))
    captured = capsys.readouterr()
    return code, json.loads(captured.out.strip().splitlines()[-1]), captured.err


@pytest.fixture
def nested(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A project one directory inside a repository that is not a vqapr project, run from there."""
    (tmp_path / ".git").mkdir()
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    return project


def test_a_project_inside_another_repository_gets_the_skills_itself(
    nested: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, body, _ = _run(capsys, "skill", "install")

    assert code == 0, body
    assert body["root"] == body["workspace_root"] == str(nested.resolve())
    for target in (".agents", ".claude"):
        assert list((nested / target / "skills").rglob("SKILL.md")), f"{target} got no skill"
        assert not (nested.parent / target).exists(), "the enclosing repository got the skills"


def test_naming_the_current_directory_is_the_same_as_not_naming_it(
    nested: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, implicit, _ = _run(capsys, "skill", "install", "--dry-run")
    code, explicit, _ = _run(capsys, "--project-root", ".", "skill", "install", "--dry-run")

    assert code == 0, explicit
    assert explicit["root"] == implicit["root"]
    assert explicit["written"] == implicit["written"]


def test_a_fresh_folder_with_no_repository_installs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The first-time path: empty folder, `uv add vqapr`, `skill install` -- no `git init`."""
    monkeypatch.chdir(tmp_path)

    code, body, _ = _run(capsys, "skill", "install", "--dry-run")

    assert code == 0, body
    assert body["written"]
    assert all(path.startswith(str(tmp_path.resolve())) for path in body["written"])


def test_the_stale_skill_note_reads_the_skills_install_wrote(
    nested: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The fourth finding: install and the note every other command prints read one root."""
    code, _, _ = _run(capsys, "skill", "install", "--target", "claude")
    assert code == 0
    manifest = nested / ".claude" / "skills" / MANIFEST_NAME
    recorded = json.loads(manifest.read_text(encoding="utf-8"))
    recorded["package_version"] = "0.0.1"
    manifest.write_text(json.dumps(recorded), encoding="utf-8")

    code, _, err = _run(capsys, "list", "datasets")

    assert code == 0
    assert "installed from vqapr 0.0.1" in err, err
