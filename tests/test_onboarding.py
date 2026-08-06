import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from qlibx import AgentTarget, OnboardingRequest, QlibxProject
from qlibx.config import ChangeAction


def project(tmp_path: Path) -> QlibxProject:
    QlibxProject.init(tmp_path, apply=True)
    return QlibxProject.open(tmp_path)


def test_codex_onboarding_previews_then_preserves_instruction_content(tmp_path: Path) -> None:
    current = project(tmp_path)
    instruction = tmp_path / "AGENTS.md"
    instruction.write_text("# User instructions\n\nKeep this.\n", encoding="utf-8")
    request = OnboardingRequest(target=AgentTarget.CODEX)

    preview = current.onboard((request,))[0]
    assert preview.applied is False
    assert any(change.action is ChangeAction.CREATE for change in preview.changes)
    assert not (tmp_path / ".agents" / "skills" / "qlibx").exists()

    applied = current.onboard((request,), apply=True)[0]
    assert applied.applied is True
    content = instruction.read_text(encoding="utf-8")
    assert content.startswith("# User instructions\n\nKeep this.\n")
    assert content.count("<!-- qlibx-managed:start -->") == 1
    installed_skill = tmp_path / ".agents" / "skills" / "qlibx" / "SKILL.md"
    assert installed_skill.is_file()
    guidance = installed_skill.read_text(encoding="utf-8")
    assert "committed MVP simulation fills as current execution feedback" in guidance
    assert "Do not present them as an available qlibx workflow" in guidance

    repeated = current.onboard((request,), apply=True)[0]
    assert repeated.applied is True
    assert all(change.action is ChangeAction.UNCHANGED for change in repeated.changes)
    assert instruction.read_text(encoding="utf-8").count("qlibx-managed:start") == 1


def test_modified_generated_skill_is_not_overwritten(tmp_path: Path) -> None:
    current = project(tmp_path)
    request = OnboardingRequest(target=AgentTarget.CODEX)
    current.onboard((request,), apply=True)
    installed = tmp_path / ".agents" / "skills" / "qlibx" / "SKILL.md"
    installed.write_text(installed.read_text(encoding="utf-8") + "\nuser edit\n", encoding="utf-8")

    result = current.onboard((request,), apply=True)[0]

    assert result.applied is False
    assert result.error == "generated skill content was modified"
    assert installed.read_text(encoding="utf-8").endswith("user edit\n")


def test_target_plans_apply_independently_and_preserve_extension_files(tmp_path: Path) -> None:
    current = project(tmp_path)
    codex = OnboardingRequest(target=AgentTarget.CODEX)
    claude = OnboardingRequest(target=AgentTarget.CLAUDE)
    current.onboard((codex,), apply=True)
    codex_skill = tmp_path / ".agents" / "skills" / "qlibx"
    (codex_skill / "user-extension.md").write_text("keep", encoding="utf-8")
    (codex_skill / "SKILL.md").write_text("modified", encoding="utf-8")

    results = current.onboard((codex, claude), apply=True)

    assert results[0].applied is False
    assert results[1].applied is True
    assert (codex_skill / "user-extension.md").read_text(encoding="utf-8") == "keep"
    assert (tmp_path / ".claude" / "skills" / "qlibx-skill" / "SKILL.md").is_file()
    manifest = json.loads(
        (tmp_path / ".claude" / "skills" / "qlibx-skill" / ".qlibx-generated.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["target"] == "claude"
    assert manifest["package_version"] == "0.1.0"


def test_custom_target_requires_explicit_root() -> None:
    with pytest.raises(ValidationError):
        OnboardingRequest(target=AgentTarget.CUSTOM)
