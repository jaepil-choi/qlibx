"""Every command a skill message names is a command that runs.

`docs/issues/archive/025`. `vqapr skill list` reported staleness with *"run `vqapr skill install --force` to
update it"*, and `install` accepted only `--target`, `--into` and `--dry-run`. Following the
instruction produced:

    {"error": "UsageError: unrecognized arguments: --force", "ok": false}

The assertion is mechanical rather than textual: whatever a message names is extracted from the
message itself and **executed**. A message that names a working command passes; one that names
anything else fails, whatever it says.

## `install --force` now exists, and this file used to assert it must not

`025` was fixed by rewriting the sentence rather than adding the flag, and this file asserted that
choice: *"a `--force` on `install` would be a no-op that exists only to make an incorrect message
correct."* That was true of the `install` of the time, which overwrote everything unconditionally
-- there was nothing for a flag to unlock.

PRD §11.3 changed what `install` does. It now judges each installed file against every release
vqapr has shipped and **refuses to overwrite one that matches none of them**, because content we
have never shipped is the user's edit. `--force` unlocks exactly that, so it is no longer a no-op,
and the earlier assertion is retired rather than deleted: the test below proves the flag does
something, which is the same guarantee `025` was really asking for.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from vqapr.agent.skillset import MANIFEST_NAME
from vqapr.cli.main import main

EDITED = "a copy the user edited by hand"

SKILLS = Path(".agents") / "skills"


def _cli(capsys: pytest.CaptureFixture[str], root: Path, *argv: str) -> tuple[int, dict]:
    code = main(["--project-root", str(root), *argv])
    out = capsys.readouterr().out.strip()
    return code, json.loads(out.splitlines()[-1])


def _some_installed_file(root: Path) -> Path:
    """One shipped file from the install, chosen without naming a skill.

    Naming `introduce-vqapr/SKILL.md` here would make this file need editing every time the set is
    reorganised, and the guarantee is about any installed file, not a particular one.
    """
    found = sorted((root / SKILLS).rglob("SKILL.md"))
    assert found, "install wrote no SKILL.md at all"
    return found[0]


def _commands_named_in(payload: object) -> list[list[str]]:
    """Every `vqapr ...` in backticks anywhere in a payload, as argv lists."""
    text = json.dumps(payload, ensure_ascii=False)
    return [
        named.split()
        for named in re.findall(r"`([^`]+)`", text)
        if named.split()[:1] == ["vqapr"]
    ]


def _run(root: Path, argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "vqapr", "--project-root", str(root), *argv[1:]],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
    )


@pytest.fixture
def edited_install(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> Path:
    """Install, then edit one installed file so it matches no release vqapr has shipped."""
    code, _ = _cli(capsys, tmp_path, "skill", "install")
    assert code == 0

    edited = _some_installed_file(tmp_path)
    edited.write_text(EDITED, encoding="utf-8")
    return edited


def test_the_refusal_names_a_command_that_runs(
    tmp_path: Path, edited_install: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`025`'s condition, executed rather than pattern-matched.

    The command is pulled out of the payload with a backtick match and run as a subprocess, so
    this test cannot pass by agreeing with a hard-coded string it also asserts.
    """
    code, body = _cli(capsys, tmp_path, "skill", "install")
    assert code == 0, body
    assert body["refused"], "the edited file was not refused; the fixture proved nothing"

    named = _commands_named_in(body)
    assert named, f"the refusal names no vqapr command at all: {body}"

    for argv in named:
        result = _run(tmp_path, argv)
        assert result.returncode == 0, (
            f"a message tells the reader to run {' '.join(argv)!r}, which fails:\n"
            f"{result.stdout}{result.stderr}"
        )

    assert edited_install.read_text(encoding="utf-8") != EDITED, (
        "the command the message named ran, and the edited file is still the edit"
    )


def test_force_is_not_a_no_op_and_plain_install_leaves_the_edit_alone(
    tmp_path: Path, edited_install: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Both halves of the gate, in the order a user meets them.

    This is the assertion that replaced `025`'s "no no-op flag" -- see the module docstring. A
    flag that changes nothing would fail here, because the plain run and the forced run are
    required to differ.
    """
    code, plain = _cli(capsys, tmp_path, "skill", "install")
    assert code == 0, plain
    assert str(edited_install) in plain["refused"]
    assert edited_install.read_text(encoding="utf-8") == EDITED, (
        "plain install overwrote an edit vqapr never shipped"
    )

    code, forced = _cli(capsys, tmp_path, "skill", "install", "--force")
    assert code == 0, forced
    assert not forced.get("refused"), forced
    assert edited_install.read_text(encoding="utf-8") != EDITED


def test_a_file_vqapr_never_shipped_is_reported_and_left(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """PRD §11.3: a path we have never shipped is not ours, so it is named and not touched."""
    code, _ = _cli(capsys, tmp_path, "skill", "install")
    assert code == 0

    mine = _some_installed_file(tmp_path).parent / "references" / "my-notes.md"
    mine.parent.mkdir(parents=True, exist_ok=True)
    mine.write_text("my own note", encoding="utf-8")

    code, body = _cli(capsys, tmp_path, "skill", "install")
    assert code == 0, body
    assert str(mine) in body["preserved"]

    code, body = _cli(capsys, tmp_path, "skill", "remove", "--force")
    assert code == 0, body
    assert str(mine) in body["preserved"]
    assert mine.read_text(encoding="utf-8") == "my own note", "remove --force deleted a user file"


def test_the_upgrade_note_reaches_stderr_and_names_a_command_that_runs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A skill installed by another vqapr is announced on every command, not only `skill`.

    On stderr, so stdout keeps carrying exactly one JSON document (record `171`). Record `168` is
    why it is not `skill list`'s alone: a stale skill does its damage while an agent reads it and
    runs something else.
    """
    code, _ = _cli(capsys, tmp_path, "skill", "install")
    assert code == 0

    manifest_path = tmp_path / SKILLS / MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["package_version"] = "0.0.1-from-another-release"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = _run(tmp_path, ["vqapr", "list", "datasets"])
    assert result.returncode == 0, result.stderr
    json.loads(result.stdout.strip().splitlines()[-1]), "stdout must stay one JSON document"
    assert "0.0.1-from-another-release" in result.stderr

    named = _commands_named_in(result.stderr)
    assert named, f"the upgrade note names no command: {result.stderr!r}"
    for argv in named:
        assert _run(tmp_path, argv).returncode == 0, f"{' '.join(argv)!r} fails"


def test_force_still_belongs_to_remove(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The flag is real on its own verb too, and this branch must not have moved it."""
    code, _ = _cli(capsys, tmp_path, "skill", "install")
    assert code == 0

    code, body = _cli(capsys, tmp_path, "skill", "remove", "--force")
    assert code == 0, body
