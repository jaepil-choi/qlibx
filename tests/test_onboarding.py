import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from qlibx import (
    AgentTarget,
    OnboardingDesiredState,
    OnboardingRequest,
    QlibxProject,
)
from qlibx.config import ChangeAction


def project(tmp_path: Path) -> QlibxProject:
    QlibxProject.init(tmp_path, apply=True)
    return QlibxProject.open(tmp_path)


def test_uc_agent_001_codex_onboarding_installs_availability_guidance(
    tmp_path: Path,
) -> None:
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
    assert "Explain look-ahead risk" in guidance
    assert "actual release timestamp" in guidance
    assert "source-supported delay rule" in guidance
    assert "source enrichment" in guidance
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


def absent_request(target: AgentTarget, *, custom_root: str | None = None) -> OnboardingRequest:
    return OnboardingRequest(
        target=target,
        custom_root=custom_root,
        desired_state=OnboardingDesiredState.ABSENT,
    )


def test_remove_is_preview_first_idempotent_and_preserves_user_extensions(tmp_path: Path) -> None:
    current = project(tmp_path)
    instruction = tmp_path / "AGENTS.md"
    instruction.write_bytes(b"# User instructions\r\n\r\nKeep this.\r\n")
    present = OnboardingRequest(target=AgentTarget.CODEX)
    current.onboard((present,), apply=True)
    skill_dir = tmp_path / ".agents" / "skills" / "qlibx"
    extension = skill_dir / "user-extension.md"
    extension.write_text("keep", encoding="utf-8")
    request = absent_request(AgentTarget.CODEX)

    preview = current.onboard((request,))[0]

    assert preview.applied is False
    assert preview.error is None
    assert preview.validation.matches_desired_state is False
    assert any(change.action is ChangeAction.REMOVE for change in preview.changes)
    assert (skill_dir / "SKILL.md").exists()

    applied = current.onboard((request,), apply=True)[0]

    assert applied.applied is True
    assert applied.error is None
    assert applied.validation.matches_desired_state is True
    assert applied.validation_argv[-1] == "--remove"
    assert not (skill_dir / "SKILL.md").exists()
    assert not (skill_dir / ".qlibx-generated.json").exists()
    assert extension.read_text(encoding="utf-8") == "keep"
    assert instruction.exists()
    assert b"qlibx-managed" not in instruction.read_bytes()

    repeated = current.onboard((request,), apply=True)[0]
    assert repeated.applied is True
    assert repeated.validation.matches_desired_state is True
    assert all(change.action is ChangeAction.UNCHANGED for change in repeated.changes)


def test_managed_block_update_and_remove_preserve_all_outside_bytes(tmp_path: Path) -> None:
    current = project(tmp_path)
    instruction = tmp_path / "AGENTS.md"
    instruction.write_bytes(b"prefix\r\n\r\nuser-owned\r\n")
    present = OnboardingRequest(target=AgentTarget.CODEX)
    current.onboard((present,), apply=True)

    installed = instruction.read_bytes()
    start = installed.index(b"<!-- qlibx-managed:start -->")
    end = installed.index(b"<!-- qlibx-managed:end -->") + len(b"<!-- qlibx-managed:end -->")
    prefix = installed[:start]
    suffix = installed[end:]
    modified_block = installed[start:end].replace(
        b"Use the version-matched qlibx skill",
        b"Use an obsolete qlibx skill",
    )
    instruction.write_bytes(prefix + modified_block + suffix)

    updated = current.onboard((present,), apply=True)[0]
    assert updated.applied is True
    refreshed = instruction.read_bytes()
    refreshed_start = refreshed.index(b"<!-- qlibx-managed:start -->")
    refreshed_end = refreshed.index(b"<!-- qlibx-managed:end -->") + len(
        b"<!-- qlibx-managed:end -->"
    )
    assert refreshed[:refreshed_start] == prefix
    assert refreshed[refreshed_end:] == suffix
    assert b"Use the version-matched qlibx skill" in refreshed
    assert b"\r\n" in refreshed[refreshed_start:refreshed_end]

    before_remove_prefix = refreshed[:refreshed_start]
    before_remove_suffix = refreshed[refreshed_end:]
    removed = current.onboard((absent_request(AgentTarget.CODEX),), apply=True)[0]
    assert removed.applied is True
    assert instruction.read_bytes() == before_remove_prefix + before_remove_suffix


def test_update_removes_retired_manifest_owned_file(tmp_path: Path) -> None:
    current = project(tmp_path)
    request = OnboardingRequest(target=AgentTarget.CODEX)
    current.onboard((request,), apply=True)
    skill_dir = tmp_path / ".agents" / "skills" / "qlibx"
    retired = skill_dir / "references" / "retired.md"
    retired.write_bytes(b"retired generated content")
    manifest_path = skill_dir / ".qlibx-generated.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"]["references/retired.md"] = hashlib.sha256(retired.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    preview = current.onboard((request,))[0]
    retired_change = next(change for change in preview.changes if change.path == str(retired))
    assert retired_change.action is ChangeAction.REMOVE

    applied = current.onboard((request,), apply=True)[0]
    assert applied.applied is True
    assert not retired.exists()
    assert applied.validation.matches_desired_state is True


def test_manifest_v1_can_upgrade_and_remove(tmp_path: Path) -> None:
    current = project(tmp_path)
    present = OnboardingRequest(target=AgentTarget.CODEX)
    current.onboard((present,), apply=True)
    manifest_path = tmp_path / ".agents" / "skills" / "qlibx" / ".qlibx-generated.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["schema_version"] = 1
    manifest.pop("instruction_path")
    manifest.pop("managed_block_fingerprint")
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    upgraded = current.onboard((present,), apply=True)[0]
    assert upgraded.applied is True
    assert json.loads(manifest_path.read_text(encoding="utf-8"))["schema_version"] == 2

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["schema_version"] = 1
    manifest.pop("instruction_path")
    manifest.pop("managed_block_fingerprint")
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    removed = current.onboard((absent_request(AgentTarget.CODEX),), apply=True)[0]
    assert removed.applied is True
    assert removed.validation.matches_desired_state is True
    assert (tmp_path / "AGENTS.md").exists()


def test_modified_generated_file_aborts_remove_without_partial_mutation(tmp_path: Path) -> None:
    current = project(tmp_path)
    present = OnboardingRequest(target=AgentTarget.CODEX)
    current.onboard((present,), apply=True)
    skill_dir = tmp_path / ".agents" / "skills" / "qlibx"
    installed = skill_dir / "SKILL.md"
    installed.write_text(installed.read_text(encoding="utf-8") + "\nuser edit\n", encoding="utf-8")
    manifest_before = (skill_dir / ".qlibx-generated.json").read_bytes()
    instruction = tmp_path / "AGENTS.md"
    instruction_before = instruction.read_bytes()

    result = current.onboard((absent_request(AgentTarget.CODEX),), apply=True)[0]

    assert result.applied is False
    assert result.error == "generated skill content was modified"
    assert installed.exists()
    assert (skill_dir / ".qlibx-generated.json").read_bytes() == manifest_before
    assert instruction.read_bytes() == instruction_before


def test_invalid_manifest_path_and_duplicate_markers_fail_before_mutation(tmp_path: Path) -> None:
    current = project(tmp_path)
    present = OnboardingRequest(target=AgentTarget.CODEX)
    current.onboard((present,), apply=True)
    skill_dir = tmp_path / ".agents" / "skills" / "qlibx"
    manifest_path = skill_dir / ".qlibx-generated.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"]["../escape.md"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    instruction = tmp_path / "AGENTS.md"
    instruction.write_bytes(instruction.read_bytes() + b"<!-- qlibx-managed:start -->")
    skill_before = (skill_dir / "SKILL.md").read_bytes()
    instruction_before = instruction.read_bytes()

    result = current.onboard((present,), apply=True)[0]

    assert result.applied is False
    assert (skill_dir / "SKILL.md").read_bytes() == skill_before
    assert instruction.read_bytes() == instruction_before
    assert any("invalid onboarding manifest" in issue for issue in result.validation.issues)
    assert any("invalid managed instruction block" in issue for issue in result.validation.issues)


def test_custom_target_remove_preserves_custom_root(tmp_path: Path) -> None:
    current = project(tmp_path)
    custom_root = tmp_path / "agent-skills"
    present = OnboardingRequest(target=AgentTarget.CUSTOM, custom_root=str(custom_root))
    applied = current.onboard((present,), apply=True)[0]
    assert applied.validation.managed_block_ok is None
    (custom_root / "keep.txt").write_text("keep", encoding="utf-8")

    removed = current.onboard(
        (absent_request(AgentTarget.CUSTOM, custom_root=str(custom_root)),),
        apply=True,
    )[0]

    assert removed.applied is True
    assert removed.validation.matches_desired_state is True
    assert custom_root.is_dir()
    assert (custom_root / "keep.txt").read_text(encoding="utf-8") == "keep"
