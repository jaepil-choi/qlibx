"""Rung 1's stop condition names commands the CLI accepts.

`docs/issues/archive/030`, found on the very first command of a first-time journey. The skill said:

> **Stop condition:** `vqapr list` shows all required elements and `register` accepted every
> declaration without failures.

`kind` is a required positional and there is no all-kinds form, so running the sentence returned
`usage.rejected`. Checking the stop condition means one call per kind, and learning that means
reading `vqapr list --help` -- not the skill, which is what the reader was following.

The sentence now names the calls. This test is what stops it drifting from the CLI again: a kind
renamed or added in `list_.KINDS` and not reflected in the skill fails here.

Only the runnable half of `docs/issues/archive/030` is closed. The second half -- whether `cli.usage`
refusals are inside the six-field envelope guarantee, which they are not today -- is a decision
about what that guarantee covers, and is left open deliberately.
"""

from __future__ import annotations

import json
import re

from vqapr.agent.skillset import shipped_skills
from vqapr.cli.list_ import KINDS
from vqapr.cli.main import main

SURVEYS_THE_WORKSPACE = "inspect-workspace"
"""The skill that now owns surveying a workspace with `vqapr list`.

`docs/issues/archive/030`'s sentence lived under "Rung 1" in the single pre-split skill, and this helper
sliced it out between two heading strings. PRD §11.2 made the skill a set, and the surveying half
moved here.

The anchor is now the skill rather than a pair of headings inside one. Slicing by heading text is
what broke when the content moved -- and the guarantee was never about a section, it is that
whatever tells a reader to survey the workspace names kinds the CLI accepts.
"""


def _stop_condition_block() -> str:
    """The body of the skill that tells a reader to survey the workspace."""
    return shipped_skills()[SURVEYS_THE_WORKSPACE]["SKILL.md"].decode("utf-8")


def test_bare_list_is_still_refused_so_the_skill_must_not_name_it(capsys) -> None:
    """The behaviour the sentence contradicted, pinned rather than assumed.

    If `list` ever grows an all-kinds form -- which `docs/issues/archive/030` argues is the better shape --
    this fails, and the skill can go back to one sentence in the same commit.
    """
    assert main(["list"]) != 0
    envelope = json.loads(capsys.readouterr().out)

    assert envelope["ok"] is False
    assert envelope["stage"] == "usage"
    assert envelope["failures"][0]["code"] == "usage.rejected"


def test_every_command_the_stop_condition_names_is_a_real_kind() -> None:
    """A command in the skill that the CLI refuses is worse than no command at all."""
    named = re.findall(r"vqapr list ([a-z-]+)", _stop_condition_block())

    assert named, "the stop condition must name the calls that check it"
    unknown = sorted(set(named) - set(KINDS))
    assert not unknown, f"the skill names kinds `vqapr list` does not accept: {unknown}"


def test_the_stop_condition_accounts_for_every_kind() -> None:
    """Named or explicitly set aside -- so a new kind cannot be silently absent from the skill.

    Seven kinds are the Rung 1 setup and are listed as commands; the remaining three are named in
    the sentence beneath it. Ten is the whole of `KINDS`.
    """
    block = _stop_condition_block()
    mentioned = {kind for kind in KINDS if kind in block}

    assert mentioned == set(KINDS), f"unmentioned kinds: {sorted(set(KINDS) - mentioned)}"


def test_the_skill_says_why_there_is_no_all_kinds_call() -> None:
    """The reader ran one command and got a refusal; the skill now predicts it."""
    block = " ".join(_stop_condition_block().split())

    assert "there is no all-kinds form" in block
    assert "usage.rejected" in block, (
        "name the code the reader will see, so a refusal reads as expected rather than as a defect"
    )
