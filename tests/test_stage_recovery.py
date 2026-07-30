"""The skill layer must offer the choice the core refused to make.

PRD 5.3 states the requirement negatively: a skill that presents one repair path has undone
the decision PRD 5.6 made, one layer up. So these tests are about plurality and about who
owns it -- not about the wording of any particular path.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from qlibx.cli import parser
from qlibx.errors import STAGES
from qlibx.skill import plan_agent_skill
from qlibx.stage_recovery import STAGE_RECOVERY, stage_recovery_markdown


def _public_commands() -> set[str]:
    """Every spelling the CLI accepts: `qlibx <command>` and `qlibx <command> <action>`."""
    accepted: set[str] = set()

    def walk(command: argparse.ArgumentParser, prefix: str) -> None:
        for action in command._actions:
            if not isinstance(action, argparse._SubParsersAction):
                continue
            for name, child in action.choices.items():
                spelling = f"{prefix} {name}".strip()
                accepted.add(spelling)
                walk(child, spelling)

    walk(parser(), "")
    return accepted


@pytest.mark.parametrize("stage", sorted(STAGES))
def test_every_stage_offers_a_choice_of_repairs(stage: str) -> None:
    """One path is a prescription. The core declined to prescribe; the skill may not either."""
    failures = STAGE_RECOVERY.get(stage, ())
    assert failures, f"stage {stage} documents no failure"
    for failure in failures:
        assert len(failure.paths) >= 2, (
            f"{stage} failure {failure.symptom!r} offers {len(failure.paths)} path(s); "
            "a single path is the prescription PRD 5.3 forbids"
        )
        for path in failure.paths:
            assert path.action.strip(), f"{stage}: a path states no action"
            assert path.choose_when.strip(), (
                f"{stage}: path {path.action!r} gives no criterion, so the agent still guesses"
            )
        assert failure.rerun.strip(), f"{stage}: failure {failure.symptom!r} names no rerun"


def test_the_recovery_table_covers_the_declared_stages_and_nothing_else() -> None:
    """A stage the core dropped must not keep a recovery section, and a new one must gain it."""
    assert set(STAGE_RECOVERY) == set(STAGES)


def test_every_rerun_command_is_one_the_cli_accepts() -> None:
    """A renamed command must break this, not rot silently inside a generated skill."""
    accepted = _public_commands()
    unknown = []
    for stage, failures in STAGE_RECOVERY.items():
        for failure in failures:
            for quoted in _qlibx_invocations(failure.rerun):
                if quoted not in accepted:
                    unknown.append(f"{stage}: {quoted!r}")
    assert not unknown, "rerun commands the CLI does not accept:\n  " + "\n  ".join(unknown)


def _qlibx_invocations(text: str) -> list[str]:
    """Pull `qlibx <command> [<action>]` out of a rerun line, ignoring its options."""
    found = []
    for chunk in text.split("`"):
        words = chunk.split()
        if not words or words[0] != "qlibx":
            continue
        # Stop at the first option or `<placeholder>`: past that point the words are argument
        # values, not command names.
        tail = words[1:]
        cut = next(
            (index for index, word in enumerate(tail) if word.startswith(("-", "<"))), len(tail)
        )
        if tail[:cut]:
            found.append(" ".join(tail[:cut]))
    return found


def test_the_generated_skill_ships_the_stage_reference(tmp_path: Path) -> None:
    """The content is only worth writing if the agent that receives a stage can find it."""
    plan = plan_agent_skill(tmp_path / "skill")
    files = {file.path.name: file.content for file in plan.files}
    assert "stage-recovery.md" in files

    skill = files["SKILL.md"]
    assert "references/stage-recovery.md" in skill

    reference = files["stage-recovery.md"]
    for stage in STAGES:
        assert f"## {stage}" in reference
    assert reference.isascii(), "the reference must survive a legacy console codepage"


def test_the_reference_states_which_paths_need_the_user() -> None:
    """PRD 5.3 asks which choice needs confirmation, so the rendering must say for every path."""
    rendered = stage_recovery_markdown()
    paths = sum(len(failure.paths) for failures in STAGE_RECOVERY.values() for failure in failures)
    assert rendered.count("- Confirmation:") == paths
    assert "ask the user before taking this path" in rendered
