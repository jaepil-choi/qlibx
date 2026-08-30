"""The stale-skill message names a command that runs.

`docs/issues/025`. `vqapr skill list` reported staleness with *"run `vqapr skill install --force` to
update it"*, and `install` accepts only `--target`, `--into` and `--dry-run`. Following the
instruction produced:

    {"error": "UsageError: unrecognized arguments: --force", "ok": false}

`--force` does exist -- on the sibling `remove` verb, where it means *remove even if files have been
modified since install*. So the flag was real, on another verb, with a different meaning.

The assertion here is mechanical rather than textual: whatever the sentence names is extracted from
the message itself and **executed**. A message that names a working command passes; one that names
anything else fails, whatever it says.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from vqapr.cli.main import main


def _cli(capsys: pytest.CaptureFixture[str], root: Path, *argv: str) -> tuple[int, dict]:
    code = main(["--project-root", str(root), *argv])
    out = capsys.readouterr().out.strip()
    return code, json.loads(out.splitlines()[-1])


def _stale_install(root: Path, capsys: pytest.CaptureFixture[str]) -> str:
    """Install the skill, then make the installed copy differ from what the package ships."""
    (root / ".git").mkdir()
    code, _ = _cli(capsys, root, "skill", "install")
    assert code == 0

    installed = root / ".agents/skills/vqapr/SKILL.md"
    installed.write_text("a stale copy of an older surface", encoding="utf-8")

    code, body = _cli(capsys, root, "skill", "list")
    assert code == 0
    assert body["current"] is False, "the fixture failed to produce a stale install"
    return body["stale"]


def test_the_named_command_is_accepted_and_updates_the_install(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The merge condition, executed rather than pattern-matched.

    The command is pulled out of the message with a backtick match and run as a subprocess, so this
    test cannot pass by agreeing with a hard-coded string it also asserts.
    """
    message = _stale_install(tmp_path, capsys)

    named = re.search(r"`([^`]+)`", message)
    assert named, f"the stale message names no command at all: {message!r}"

    argv = named.group(1).split()
    assert argv[0] == "vqapr", f"the named command is not a vqapr command: {argv}"

    result = subprocess.run(
        [sys.executable, "-m", "vqapr", "--project-root", str(tmp_path), *argv[1:]],
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode == 0, (
        f"the stale message tells the reader to run {' '.join(argv)!r}, which fails:\n"
        f"{result.stdout}{result.stderr}"
    )

    _, body = _cli(capsys, tmp_path, "skill", "list")
    assert body["current"] is True, (
        "the command the message named ran, but the install is still stale"
    )


def test_install_gained_no_no_op_force_flag(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The other half of the condition: fix the sentence, not the parser.

    Adding `--force` to `install` would have made the original message correct, and it would have
    been a flag that does nothing -- plain `install` already overwrites. A no-op option that exists
    to justify a message is worse than the message was.
    """
    (tmp_path / ".git").mkdir()
    result = subprocess.run(
        [
            sys.executable, "-m", "vqapr", "--project-root", str(tmp_path),
            "skill", "install", "--force",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode != 0, "`skill install --force` was accepted; a no-op flag was added"
    assert "--force" in (result.stdout + result.stderr)


def test_force_still_belongs_to_remove(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The flag is real on its own verb, and this branch must not have moved it."""
    (tmp_path / ".git").mkdir()
    code, _ = _cli(capsys, tmp_path, "skill", "install")
    assert code == 0

    code, body = _cli(capsys, tmp_path, "skill", "remove", "--force")
    assert code == 0, body
