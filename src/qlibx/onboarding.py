"""Safe installation of the version-matched qlibx agent skill."""

import hashlib
import os
from enum import StrEnum
from importlib.metadata import version
from pathlib import Path

from pydantic import Field, model_validator

from qlibx.config import ChangeAction
from qlibx.models import QlibxModel

START_MARKER = "<!-- qlibx-managed:start -->"
END_MARKER = "<!-- qlibx-managed:end -->"


class AgentTarget(StrEnum):
    CODEX = "codex"
    CLAUDE = "claude"
    CUSTOM = "custom"


class OnboardingRequest(QlibxModel):
    target: AgentTarget
    custom_root: str | None = None

    @model_validator(mode="after")
    def validate_custom_root(self) -> "OnboardingRequest":
        if self.target is AgentTarget.CUSTOM and not self.custom_root:
            raise ValueError("custom target requires an explicit custom_root")
        if self.target is not AgentTarget.CUSTOM and self.custom_root is not None:
            raise ValueError("custom_root is valid only for the custom target")
        return self


class OnboardingChange(QlibxModel):
    path: str
    action: ChangeAction
    kind: str
    expected_fingerprint: str | None = None


class TargetOnboardingResult(QlibxModel):
    target: AgentTarget
    applied: bool
    changes: tuple[OnboardingChange, ...]
    error: str | None = None


class SkillManifest(QlibxModel):
    schema_version: int = 1
    package_version: str
    skill_schema_version: int = 1
    target: AgentTarget
    files: dict[str, str] = Field(default_factory=dict)


def fingerprint(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(payload)
    os.replace(temporary, path)


class ProjectOnboarder:
    """Preview and apply independent target-specific onboarding plans."""

    def __init__(self, project_root: Path) -> None:
        self._project_root = project_root.resolve()
        self._source = Path(__file__).parent / "resources" / "skills" / "qlibx"

    def onboard(
        self,
        requests: tuple[OnboardingRequest, ...],
        *,
        apply: bool = False,
    ) -> tuple[TargetOnboardingResult, ...]:
        return tuple(
            self._apply(request) if apply else self._preview(request) for request in requests
        )

    def _preview(self, request: OnboardingRequest) -> TargetOnboardingResult:
        skill_dir, instruction_file = self._destinations(request)
        source_files = self._source_files()
        manifest_path = skill_dir / ".qlibx-generated.json"
        prior, manifest_error = self._load_manifest(manifest_path)
        changes: list[OnboardingChange] = []

        for relative, payload in source_files.items():
            destination = skill_dir / relative
            expected = fingerprint(payload)
            if not destination.exists():
                action = ChangeAction.CREATE
            else:
                current = fingerprint(destination.read_bytes())
                if current == expected:
                    action = ChangeAction.UNCHANGED
                elif prior and prior.files.get(relative.as_posix()) == current:
                    action = ChangeAction.UPDATE
                else:
                    action = ChangeAction.CONFLICT
            changes.append(
                OnboardingChange(
                    path=str(destination),
                    action=action,
                    kind="skill_file",
                    expected_fingerprint=expected,
                )
            )

        manifest = self._manifest(request.target, source_files)
        manifest_payload = manifest.model_dump_json(indent=2).encode("utf-8")
        if manifest_error:
            manifest_action = ChangeAction.CONFLICT
        elif not manifest_path.exists():
            manifest_action = ChangeAction.CREATE
        elif manifest_path.read_bytes() == manifest_payload:
            manifest_action = ChangeAction.UNCHANGED
        else:
            manifest_action = ChangeAction.UPDATE
        changes.append(
            OnboardingChange(
                path=str(manifest_path),
                action=manifest_action,
                kind="manifest",
                expected_fingerprint=fingerprint(manifest_payload),
            )
        )

        if instruction_file:
            instruction_action = self._instruction_action(instruction_file, skill_dir)
            changes.append(
                OnboardingChange(
                    path=str(instruction_file),
                    action=instruction_action,
                    kind="instruction_block",
                )
            )
        error = "generated skill content was modified" if any(
            change.action is ChangeAction.CONFLICT for change in changes
        ) else None
        return TargetOnboardingResult(
            target=request.target,
            applied=False,
            changes=tuple(changes),
            error=error,
        )

    def _apply(self, request: OnboardingRequest) -> TargetOnboardingResult:
        preview = self._preview(request)
        if preview.error:
            return preview
        skill_dir, instruction_file = self._destinations(request)
        source_files = self._source_files()
        for relative, payload in source_files.items():
            destination = skill_dir / relative
            if not destination.exists() or destination.read_bytes() != payload:
                atomic_write(destination, payload)
        manifest = self._manifest(request.target, source_files)
        atomic_write(
            skill_dir / ".qlibx-generated.json",
            manifest.model_dump_json(indent=2).encode("utf-8"),
        )
        if instruction_file:
            atomic_write(
                instruction_file,
                self._updated_instruction(instruction_file, skill_dir).encode("utf-8"),
            )
        return TargetOnboardingResult(
            target=request.target,
            applied=True,
            changes=preview.changes,
        )

    def _source_files(self) -> dict[Path, bytes]:
        return {
            path.relative_to(self._source): path.read_bytes()
            for path in sorted(self._source.rglob("*"))
            if path.is_file() and "__pycache__" not in path.parts
        }

    @staticmethod
    def _manifest(target: AgentTarget, files: dict[Path, bytes]) -> SkillManifest:
        return SkillManifest(
            package_version=version("qlibx"),
            target=target,
            files={path.as_posix(): fingerprint(payload) for path, payload in files.items()},
        )

    @staticmethod
    def _load_manifest(path: Path) -> tuple[SkillManifest | None, bool]:
        if not path.exists():
            return None, False
        try:
            return SkillManifest.model_validate_json(path.read_text(encoding="utf-8")), False
        except Exception:
            return None, True

    def _destinations(self, request: OnboardingRequest) -> tuple[Path, Path | None]:
        if request.target is AgentTarget.CODEX:
            return (
                self._project_root / ".agents" / "skills" / "qlibx",
                self._project_root / "AGENTS.md",
            )
        if request.target is AgentTarget.CLAUDE:
            return (
                self._project_root / ".claude" / "skills" / "qlibx-skill",
                self._project_root / "CLAUDE.md",
            )
        custom_root = Path(request.custom_root or "")
        if not custom_root.is_absolute():
            custom_root = self._project_root / custom_root
        return custom_root.resolve() / "qlibx", None

    def _instruction_action(self, path: Path, skill_dir: Path) -> ChangeAction:
        if not path.exists():
            return ChangeAction.CREATE
        content = path.read_text(encoding="utf-8")
        has_start = START_MARKER in content
        has_end = END_MARKER in content
        if has_start != has_end:
            return ChangeAction.CONFLICT
        return (
            ChangeAction.UNCHANGED
            if self._updated_instruction(path, skill_dir) == content
            else ChangeAction.UPDATE
        )

    def _updated_instruction(self, path: Path, skill_dir: Path) -> str:
        relative_skill = skill_dir.relative_to(self._project_root).as_posix()
        block = (
            f"{START_MARKER}\n"
            f"Use the version-matched qlibx skill at {relative_skill}/SKILL.md for qlibx work.\n"
            f"{END_MARKER}"
        )
        if not path.exists():
            return block + "\n"
        content = path.read_text(encoding="utf-8")
        if START_MARKER not in content and END_MARKER not in content:
            separator = "" if not content or content.endswith("\n\n") else "\n"
            return content + separator + block + "\n"
        start = content.index(START_MARKER)
        end = content.index(END_MARKER, start) + len(END_MARKER)
        return content[:start] + block + content[end:]
