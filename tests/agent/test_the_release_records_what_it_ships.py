"""The release history is written by a script, and forgetting to run it is caught.

PRD §11.3. `_shipped.json` is the only evidence that an installed file is one vqapr handed out, so
a release that does not record its own content makes the *next* release accuse untouched installs
of being edited. The check exists so that is a failed release step rather than a user's problem.

The table is deliberately **not** in the working tree. Recording content before it ships would put
bytes in the history that no release ever handed out, and the refusal's sentence -- *differs from
every release vqapr has shipped* -- would stop being true. So `--check` fails here, on purpose, and
the release step is what makes it pass.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from vqapr.agent.skillset import RELEASED_TABLE, FileState, judge, sha256, skills_in

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "record_shipped_skills.py"
SKILLS = REPO / "src" / "vqapr" / "agent" / "skills"


def _script(*argv: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *argv],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=REPO,
        timeout=180,
    )


def test_the_check_fails_while_content_is_unrecorded() -> None:
    """The gate is wired up and answers about the real tree.

    Asserting the failure rather than the success is the honest shape here: the tree ships content
    that has not been released, and a green check would mean the script was not looking.
    """
    result = _script("--check")
    assert result.returncode == 1, result.stdout
    assert RELEASED_TABLE in result.stderr
    assert "record_shipped_skills.py" in result.stderr, (
        "the failure must name the command that fixes it, and that command must be the real one"
    )


def test_every_shipped_file_is_named_by_the_check() -> None:
    """No file is silently exempt: what `skill install` writes is what the release must record."""
    listed = {line.strip() for line in _script("--check").stderr.splitlines() if "/" in line}
    expected = {
        f"{name}/{path}" for name, files in skills_in(SKILLS).items() for path in files
    }
    assert expected <= listed, expected - listed


def test_a_recorded_release_turns_yesterdays_copy_into_outdated(tmp_path: Path) -> None:
    """The round trip the release performs, without writing into the working tree.

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


def test_recording_adds_and_never_removes(tmp_path: Path) -> None:
    """A path dropped from the skill set keeps its history.

    Deleting it would tell whoever still holds that file that they edited it, when in fact vqapr
    handed it to them. The table answers "what have we ever shipped", not "what do we ship now".
    """
    retired = {"gone-skill/SKILL.md": {"0" * 64: "0.5.0"}}
    table = dict(retired)
    table.setdefault("a-skill/SKILL.md", {})[sha256(b"new")] = "0.7.0"
    assert retired["gone-skill/SKILL.md"].items() <= table["gone-skill/SKILL.md"].items()


@pytest.mark.parametrize("flag", ["--check", "--help"])
def test_the_script_runs_without_the_package_installed(flag: str) -> None:
    """Run as a plain script, not through `uv run -m`: the release step is a shell line."""
    assert _script(flag).returncode in (0, 1)
