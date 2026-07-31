from __future__ import annotations

from pathlib import Path

import pytest

from qlibx import Project
from qlibx.errors import QlibxError
from qlibx.onboarding import apply_instruction, plan_instruction
from qlibx.skill import apply_agent_skill, plan_agent_skill


def test_instruction_plan_rejects_stale_user_content(tmp_path: Path) -> None:
    project = Project.initialize(tmp_path)
    target = tmp_path / "AGENTS.md"
    target.write_text("before\n", encoding="utf-8")
    plan = plan_instruction(project, "AGENTS.md")
    target.write_text("user changed this\n", encoding="utf-8")
    with pytest.raises(QlibxError, match="changed after planning"):
        apply_instruction(plan)
    assert target.read_text(encoding="utf-8") == "user changed this\n"


def test_skill_plan_preserves_unmanaged_files_and_requires_replacement_approval(
    tmp_path: Path,
) -> None:
    root = tmp_path / "skills" / "qlibx"
    first = plan_agent_skill(root, target="codex")
    apply_agent_skill(first)
    unmanaged = root / "user-notes.md"
    unmanaged.write_text("keep me", encoding="utf-8")
    contract = root / "references" / "contracts.md"
    contract.write_text("user changed", encoding="utf-8")
    replacement = plan_agent_skill(root, target="codex")
    assert any(file.action == "replace_requires_approval" for file in replacement.files)
    with pytest.raises(QlibxError, match="different content"):
        apply_agent_skill(replacement)
    apply_agent_skill(replacement, force=True)
    assert unmanaged.read_text(encoding="utf-8") == "keep me"
    assert "signal_transform v1" in contract.read_text(encoding="utf-8")


def test_skill_plan_rejects_changes_after_dry_run(tmp_path: Path) -> None:
    root = tmp_path / "qlibx"
    plan = plan_agent_skill(root, target="claude")
    root.mkdir(parents=True)
    (root / "SKILL.md").write_text("late user file", encoding="utf-8")
    with pytest.raises(QlibxError, match="changed after planning"):
        apply_agent_skill(plan, force=True)
