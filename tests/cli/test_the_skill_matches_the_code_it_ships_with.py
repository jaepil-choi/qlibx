"""Sentences in the shipped skill that the code no longer backed (`docs/issues/archive/062`, `067`).

The skill is installed from the package, so a sentence in it is a promise the package makes. Two
had drifted: `Hold(reason=...)` was said to take "one token, no spaces" while the docstring and the
validation accepted prose, and an edited component was said to be refused without
`register --force` while no such flag existed and a plain re-register replaced it silently. Each
assertion here is mechanical: the text is checked against the behaviour it describes, in the same
test, so the two cannot drift apart again without this file saying so.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vqapr import authoring as va
from vqapr.agent.skillset import shipped_skills
from vqapr.cli.main import main
from vqapr.extension.component import ComponentKind
from vqapr.extension.scaffold import render


def _shipped_prose() -> str:
    """Every markdown byte vqapr ships as skill content, as one string.

    Not one file. A sentence is a promise wherever it is installed, and since PRD §11.2 made the
    skill a set that prose lives across nine directories and their `references/`. Asserting
    against a single `SKILL.md` would let a retired claim survive by moving one file sideways.
    """
    return "\n".join(
        content.decode("utf-8")
        for files in shipped_skills().values()
        for path, content in sorted(files.items())
        if path.endswith(".md")
    )


def _cli(capsys: pytest.CaptureFixture[str], root: Path, *argv: str) -> tuple[int, dict]:
    code = main(["--project-root", str(root), *argv])
    out = capsys.readouterr().out.strip()
    return code, json.loads(out.splitlines()[-1])


def test_the_hold_reason_rule_is_the_docstrings_rule() -> None:
    """`062`: prose with spaces is accepted, and the skill and the scaffold both say so."""
    text = _shipped_prose()
    assert "one token" not in text, "the skill still states the stricter rule the code dropped"

    assert va.Hold(reason="no name scored above zero").reason == "no name scored above zero"
    with pytest.raises(ValueError):
        va.Hold(reason="   ")

    source = render(ComponentKind.STRATEGY_MODEL, "alpha", dataset_id="prices")
    reasons = [line for line in source.splitlines() if "va.Hold(reason=" in line]
    assert reasons and all(" " in line.split("reason=")[1] for line in reasons), (
        "the scaffold's example reason is the documentation; it should contain a space"
    )


def test_the_skill_does_not_promise_a_register_force_flag(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`067`: no `register --force` anywhere in the skill, and the CLI indeed has none."""
    text = _shipped_prose()
    offending = [
        line
        for line in text.splitlines()
        if "register" in line
        and "--force" in line
        and "vqapr run" not in line
        and "there is no" not in line  # the one sentence that DENIES the flag
    ]
    assert offending == [], offending
    assert "vqapr remove" not in text, "the verb is `rm`"

    code, cap = _cli(capsys, tmp_path, "new", "constraint", "cap20")
    assert code == 0, cap
    code, refused = _cli(capsys, tmp_path, "register", "constraint", "cap20", cap["path"], "--force")
    assert code == 1
    assert refused["failures"][0]["code"] == "usage.rejected"
    assert "--force" in refused["failures"][0]["requirement"]


def test_a_plain_re_register_replaces_and_the_payload_says_which_fingerprint_it_replaced(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`067`: the edit loop is the same command twice, and the second answer names the old one."""
    code, cap = _cli(capsys, tmp_path, "new", "constraint", "cap20")
    assert code == 0, cap
    path = Path(cap["path"])

    code, first = _cli(capsys, tmp_path, "register", "constraint", "cap20", str(path))
    assert code == 0, first
    assert "replaced" not in first, "a first registration replaced nothing"
    code, listed = _cli(capsys, tmp_path, "list", "components")
    before = {row["component_id"]: row["fingerprint"] for row in listed["items"]}["cap20"]

    code, same = _cli(capsys, tmp_path, "register", "constraint", "cap20", str(path))
    assert code == 0 and "replaced" not in same, "unchanged bytes replace nothing"

    path.write_text(path.read_text(encoding="utf-8").replace('"0.2"', '"0.25"'), encoding="utf-8")
    code, edited = _cli(capsys, tmp_path, "register", "constraint", "cap20", str(path))
    assert code == 0, edited
    assert edited["replaced"] == {"fingerprint": before}
    code, listed = _cli(capsys, tmp_path, "list", "components")
    after = {row["component_id"]: row["fingerprint"] for row in listed["items"]}["cap20"]
    assert after != before
    assert [row["component_id"] for row in listed["items"]] == ["cap20"], "one id, not two"
