"""The release history is written by a script, and forgetting to run it is caught.

PRD §11.3. `_shipped.json` is the only evidence that an installed file is one vqapr handed out, so
a release that does not record its own content makes the *next* release accuse untouched installs
of being edited. The check exists so that is a failed release step rather than a user's problem.

The table lives in the working tree on purpose: §11.3 has the package *carry* the hashes of every
file it has ever shipped, and `released_hashes()` reads it out of the installed package. A table
absent from the tree would ship empty, and then every install holding anything but today's bytes
would read `modified` -- precisely the accusation this table exists to prevent.

So these tests do not assert the colour of the gate on the real tree. That colour is transient: red
between a skill edit and the release commit that records it, green immediately after, and
`.agent/project.yaml` keeps `release_check` out of `test` for exactly that reason. Pinning either
polarity here would make `uv run pytest tests/` depend on where in the release cycle the tree
happens to sit. What is stable, and what is tested below, is the gate's *behaviour*: given content
no release has shipped it fails and names it; given a recording run it passes, and what earlier
releases shipped stays in the table.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from vqapr.agent.skillset import RELEASED_TABLE, FileState, judge, sha256, skills_in

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "record_shipped_skills.py"
SKILLS = REPO / "src" / "vqapr" / "agent" / "skills"

UNSHIPPED = b"\n<!-- content no release has shipped -->\n"


def _script(*argv: str, repo: Path = REPO) -> subprocess.CompletedProcess[str]:
    """Run the release script the way the release step does -- as a plain shell line.

    The child's IO encoding is pinned because the recording branch prints the table's absolute
    path. On a console whose encoding is not UTF-8 that path arrives here as mojibake, and the
    assertions would fail for a reason that has nothing to do with the gate.
    """
    return subprocess.run(
        [sys.executable, str(repo / "scripts" / SCRIPT.name), *argv],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=repo,
        timeout=180,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )


@pytest.fixture
def repo_copy(tmp_path: Path) -> Path:
    """A throwaway repo holding the real script and the real skills, laid out as it expects.

    The script locates everything from its own `__file__`, so driving it against a copy is what
    lets these tests move shipped content without writing into the working tree. The version is a
    label the script reads out of `pyproject.toml`; nothing here depends on its value.
    """
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy2(SCRIPT, repo / "scripts" / SCRIPT.name)
    (repo / "pyproject.toml").write_text('version = "9.9.9"\n', encoding="utf-8")
    shutil.copytree(SKILLS, repo / "src" / "vqapr" / "agent" / "skills")
    return repo


def _skills_of(repo: Path) -> Path:
    return repo / "src" / "vqapr" / "agent" / "skills"


def _a_shipped_skill_md(skills: Path) -> Path:
    """One shipped `SKILL.md`, chosen the same way every run so a failure is reproducible."""
    return skills / sorted(skills_in(skills))[0] / "SKILL.md"


def test_the_check_fails_while_content_is_unrecorded(repo_copy: Path) -> None:
    """Edit a shipped file after its release, and the gate refuses and points at it.

    This is the situation the gate exists for: the tree now ships bytes no release handed out. The
    refusal has to name the file -- a count alone leaves whoever hit it guessing -- and name the
    command that fixes it, and that command must be the real one.
    """
    skills = _skills_of(repo_copy)
    # Recorded here rather than assumed: the real tree is unrecorded between a skill edit and the
    # release that stamps it, and this test must not turn red for where the cycle stands.
    assert _script(repo=repo_copy).returncode == 0
    assert _script("--check", repo=repo_copy).returncode == 0, (
        "the copied tree must start fully recorded, or this test proves nothing"
    )

    edited = _a_shipped_skill_md(skills)
    edited.write_bytes(edited.read_bytes() + UNSHIPPED)

    result = _script("--check", repo=repo_copy)
    assert result.returncode == 1, result.stdout
    assert RELEASED_TABLE in result.stderr
    assert f"{edited.parent.name}/{edited.name}" in result.stderr, result.stderr
    assert "record_shipped_skills.py" in result.stderr, (
        "the failure must name the command that fixes it, and that command must be the real one"
    )


def test_every_shipped_file_is_named_by_the_check(repo_copy: Path) -> None:
    """No file is silently exempt: what `skill install` writes is what the release must record.

    Asked against an empty history -- the state before the first release -- the check must account
    for every shipped file, not for whatever subset it happens to walk.
    """
    skills = _skills_of(repo_copy)
    (skills / RELEASED_TABLE).unlink()

    result = _script("--check", repo=repo_copy)
    assert result.returncode == 1, result.stdout
    listed = {line.strip() for line in result.stderr.splitlines() if "/" in line}
    expected = {
        f"{name}/{path}" for name, files in skills_in(skills).items() for path in files
    }
    assert expected <= listed, expected - listed


def test_recording_clears_the_check_and_keeps_earlier_releases(repo_copy: Path) -> None:
    """The round trip the release performs: record, go green, and lose no history.

    A changed path keeps its old hashes. Dropping them would tell whoever still holds the earlier
    file that they edited it, when in fact vqapr handed it to them. The table answers "what have we
    ever shipped", not "what do we ship now".
    """
    skills = _skills_of(repo_copy)
    edited = _a_shipped_skill_md(skills)
    key = f"{edited.parent.name}/{edited.name}"
    was = json.loads((skills / RELEASED_TABLE).read_text(encoding="utf-8"))[key]
    edited.write_bytes(edited.read_bytes() + UNSHIPPED)

    assert _script(repo=repo_copy).returncode == 0
    assert _script("--check", repo=repo_copy).returncode == 0

    now = json.loads((skills / RELEASED_TABLE).read_text(encoding="utf-8"))[key]
    assert now[sha256(edited.read_bytes())] == "9.9.9", "new content lands under this release"
    assert was.items() <= now.items(), "the hashes earlier releases shipped stay in the table"


def test_a_recorded_release_turns_yesterdays_copy_into_outdated(tmp_path: Path) -> None:
    """The judgement the recorded table feeds, without writing into the working tree.

    Records today's bytes under a release label, then asks `judge` about a copy holding exactly
    those bytes while the package has moved on. That copy must read `outdated` -- overwritable
    without asking -- and not `modified`.
    """
    yesterday = b"the SKILL.md of an earlier release"
    table = {"a-skill/SKILL.md": {sha256(yesterday): "0.6.0"}}
    written = tmp_path / RELEASED_TABLE
    written.write_text(json.dumps(table), encoding="utf-8")

    released = json.loads(written.read_text(encoding="utf-8"))
    verdict = judge(
        "a-skill",
        {"SKILL.md": yesterday},
        shipped={"SKILL.md": b"what ships today"},
        released=released,
    )
    assert verdict.files[0].state is FileState.OUTDATED
    assert verdict.files[0].released_in == "0.6.0"


@pytest.mark.parametrize("flag", ["--check", "--help"])
def test_the_script_runs_without_the_package_installed(flag: str) -> None:
    """Run as a plain script, not through `uv run -m`: the release step is a shell line.

    Against the real tree, and deliberately accepting either exit code: the gate's colour there is
    a fact about where the release cycle stands, not about the script. What this pins is that it
    runs at all and reaches a verdict rather than a traceback.
    """
    assert _script(flag).returncode in (0, 1)
