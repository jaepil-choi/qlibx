"""Safe installation and removal of the version-matched qlibx agent skill."""

import hashlib
import json
import os
from dataclasses import dataclass
from enum import StrEnum
from importlib.metadata import version
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import Field, field_validator, model_validator

from qlibx.config import ChangeAction
from qlibx.models import QlibxModel

START_MARKER = "<!-- qlibx-managed:start -->"
END_MARKER = "<!-- qlibx-managed:end -->"
_START_BYTES = START_MARKER.encode("utf-8")
_END_BYTES = END_MARKER.encode("utf-8")


class AgentTarget(StrEnum):
    CODEX = "codex"
    CLAUDE = "claude"
    CUSTOM = "custom"


class OnboardingDesiredState(StrEnum):
    PRESENT = "present"
    ABSENT = "absent"


class OnboardingRequest(QlibxModel):
    target: AgentTarget
    custom_root: str | None = None
    desired_state: OnboardingDesiredState = OnboardingDesiredState.PRESENT

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


class OnboardingValidation(QlibxModel):
    matches_desired_state: bool
    entrypoint_ok: bool
    manifest_ok: bool
    managed_block_ok: bool | None
    fingerprints_ok: bool
    issues: tuple[str, ...] = ()


class TargetOnboardingResult(QlibxModel):
    target: AgentTarget
    desired_state: OnboardingDesiredState
    applied: bool
    changes: tuple[OnboardingChange, ...]
    validation: OnboardingValidation
    validation_argv: tuple[str, ...]
    error: str | None = None


class _ManifestBase(QlibxModel):
    package_version: str
    skill_schema_version: Literal[1] = 1
    target: AgentTarget
    files: dict[str, str] = Field(default_factory=dict)

    @field_validator("files")
    @classmethod
    def validate_files(cls, value: dict[str, str]) -> dict[str, str]:
        validated: dict[str, str] = {}
        for raw_path, digest in value.items():
            normalized = _safe_relative_path(raw_path)
            if len(digest) != 64 or any(
                character not in "0123456789abcdef" for character in digest
            ):
                raise ValueError(f"invalid SHA-256 fingerprint for {raw_path!r}")
            validated[normalized] = digest
        return validated


class SkillManifestV1(_ManifestBase):
    schema_version: Literal[1] = 1


class SkillManifest(_ManifestBase):
    schema_version: Literal[2] = 2
    instruction_path: str | None = None
    managed_block_fingerprint: str | None = None

    @field_validator("instruction_path")
    @classmethod
    def validate_instruction_path(cls, value: str | None) -> str | None:
        return None if value is None else _safe_relative_path(value)

    @field_validator("managed_block_fingerprint")
    @classmethod
    def validate_block_fingerprint(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("invalid managed-block fingerprint")
        return value

    @model_validator(mode="after")
    def validate_instruction_contract(self) -> "SkillManifest":
        has_instruction = self.instruction_path is not None
        has_fingerprint = self.managed_block_fingerprint is not None
        if has_instruction != has_fingerprint:
            raise ValueError("instruction path and managed-block fingerprint must appear together")
        if self.target is AgentTarget.CUSTOM and has_instruction:
            raise ValueError("custom targets cannot own a project instruction block")
        if self.target is not AgentTarget.CUSTOM and not has_instruction:
            raise ValueError("agent targets require managed instruction metadata")
        return self


Manifest = SkillManifestV1 | SkillManifest


@dataclass(frozen=True)
class _TargetPlan:
    request: OnboardingRequest
    skill_dir: Path
    instruction_file: Path | None
    manifest_path: Path
    source_files: dict[Path, bytes]
    prior_files: dict[Path, str]
    manifest_payload: bytes | None
    instruction_payload: bytes | None
    expected_bytes: dict[Path, bytes | None]
    changes: tuple[OnboardingChange, ...]
    conflict_issues: tuple[str, ...]
    validation_argv: tuple[str, ...]


class OnboardingMutationConflict(RuntimeError):
    """The target changed after its onboarding plan was built."""


def _safe_relative_path(value: str) -> str:
    if not value or "\\" in value:
        raise ValueError("manifest paths must be non-empty POSIX relative paths")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or any(part in {"", "."} for part in path.parts):
        raise ValueError("manifest paths must stay below the skill root")
    if ":" in path.parts[0]:
        raise ValueError("manifest paths cannot contain a drive selector")
    return path.as_posix()


def fingerprint(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def atomic_write(path: Path, payload: bytes, *, expected: bytes | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(payload)
    try:
        current = path.read_bytes() if path.exists() else None
        if current != expected:
            raise OnboardingMutationConflict(f"target changed before write: {path}")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def remove_owned_file(path: Path, *, expected: bytes) -> None:
    if not path.exists():
        return
    if path.read_bytes() != expected:
        raise OnboardingMutationConflict(f"target changed before remove: {path}")
    path.unlink()


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
        plan = self._plan(request)
        return self._result(plan, applied=False)

    def _apply(self, request: OnboardingRequest) -> TargetOnboardingResult:
        plan = self._plan(request)
        if plan.conflict_issues:
            return self._result(
                plan,
                applied=False,
                error="generated skill content was modified",
            )
        try:
            if request.desired_state is OnboardingDesiredState.PRESENT:
                self._apply_present(plan)
            else:
                self._apply_absent(plan)
        except (OSError, OnboardingMutationConflict) as exc:
            return self._result(plan, applied=False, error=f"onboarding mutation failed: {exc}")

        validation = self._validate(plan)
        return self._result(
            plan,
            applied=True,
            validation=validation,
            error=None if validation.matches_desired_state else "onboarding validation failed",
        )

    def _plan(self, request: OnboardingRequest) -> _TargetPlan:
        skill_dir, instruction_file = self._destinations(request)
        manifest_path = skill_dir / ".qlibx-generated.json"
        source_files = self._source_files()
        prior, manifest_error = self._load_manifest(manifest_path)
        prior_files = {
            Path(relative): digest for relative, digest in (prior.files.items() if prior else ())
        }
        expected_bytes: dict[Path, bytes | None] = {}
        changes: list[OnboardingChange] = []
        conflicts: list[str] = []

        if manifest_error:
            conflicts.append(f"invalid onboarding manifest: {manifest_path}")

        if request.desired_state is OnboardingDesiredState.PRESENT:
            for relative, payload in source_files.items():
                destination = skill_dir / relative
                current = destination.read_bytes() if destination.exists() else None
                expected_bytes[destination] = current
                prior_digest = prior_files.get(relative)
                if current is None:
                    action = ChangeAction.CREATE
                elif current == payload:
                    action = ChangeAction.UNCHANGED
                elif prior_digest == fingerprint(current):
                    action = ChangeAction.UPDATE
                else:
                    action = ChangeAction.CONFLICT
                    conflicts.append(f"generated file fingerprint mismatch: {destination}")
                changes.append(
                    OnboardingChange(
                        path=str(destination),
                        action=action,
                        kind="skill_file",
                        expected_fingerprint=fingerprint(payload),
                    )
                )

            for relative, prior_digest in sorted(
                prior_files.items(), key=lambda item: item[0].as_posix()
            ):
                if relative in source_files:
                    continue
                destination = skill_dir / relative
                current = destination.read_bytes() if destination.exists() else None
                expected_bytes[destination] = current
                if current is None:
                    action = ChangeAction.UNCHANGED
                elif fingerprint(current) == prior_digest:
                    action = ChangeAction.REMOVE
                else:
                    action = ChangeAction.CONFLICT
                    conflicts.append(f"obsolete generated file was modified: {destination}")
                changes.append(
                    OnboardingChange(
                        path=str(destination),
                        action=action,
                        kind="obsolete_skill_file",
                    )
                )

            manifest = self._manifest(request.target, source_files, instruction_file, skill_dir)
            manifest_payload = manifest.model_dump_json(indent=2).encode("utf-8")
            current_manifest = manifest_path.read_bytes() if manifest_path.exists() else None
            expected_bytes[manifest_path] = current_manifest
            if manifest_error:
                manifest_action = ChangeAction.CONFLICT
            elif current_manifest is None:
                manifest_action = ChangeAction.CREATE
            elif current_manifest == manifest_payload:
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
        else:
            source_files = {}
            manifest_payload = None
            for relative, prior_digest in sorted(
                prior_files.items(), key=lambda item: item[0].as_posix()
            ):
                destination = skill_dir / relative
                current = destination.read_bytes() if destination.exists() else None
                expected_bytes[destination] = current
                if current is None:
                    action = ChangeAction.UNCHANGED
                elif fingerprint(current) == prior_digest:
                    action = ChangeAction.REMOVE
                else:
                    action = ChangeAction.CONFLICT
                    conflicts.append(f"generated file fingerprint mismatch: {destination}")
                changes.append(
                    OnboardingChange(
                        path=str(destination),
                        action=action,
                        kind="skill_file",
                    )
                )
            current_manifest = manifest_path.read_bytes() if manifest_path.exists() else None
            expected_bytes[manifest_path] = current_manifest
            if manifest_error:
                manifest_action = ChangeAction.CONFLICT
            elif current_manifest is None:
                manifest_action = ChangeAction.UNCHANGED
            else:
                manifest_action = ChangeAction.REMOVE
            changes.append(
                OnboardingChange(
                    path=str(manifest_path),
                    action=manifest_action,
                    kind="manifest",
                )
            )

        instruction_payload = None
        if instruction_file is not None:
            current_instruction = (
                instruction_file.read_bytes() if instruction_file.exists() else None
            )
            expected_bytes[instruction_file] = current_instruction
            if request.desired_state is OnboardingDesiredState.PRESENT:
                instruction_payload, instruction_error = self._instruction_present_payload(
                    current_instruction, skill_dir
                )
                if instruction_error:
                    action = ChangeAction.CONFLICT
                    conflicts.append(f"invalid managed instruction block: {instruction_file}")
                elif current_instruction is None:
                    action = ChangeAction.CREATE
                elif current_instruction == instruction_payload:
                    action = ChangeAction.UNCHANGED
                else:
                    action = ChangeAction.UPDATE
            else:
                instruction_payload, instruction_error = self._instruction_absent_payload(
                    current_instruction
                )
                if instruction_error:
                    action = ChangeAction.CONFLICT
                    conflicts.append(f"invalid managed instruction block: {instruction_file}")
                elif current_instruction == instruction_payload:
                    action = ChangeAction.UNCHANGED
                else:
                    action = ChangeAction.REMOVE
            changes.append(
                OnboardingChange(
                    path=str(instruction_file),
                    action=action,
                    kind="instruction_block",
                    expected_fingerprint=(
                        None if instruction_payload is None else fingerprint(instruction_payload)
                    ),
                )
            )

        return _TargetPlan(
            request=request,
            skill_dir=skill_dir,
            instruction_file=instruction_file,
            manifest_path=manifest_path,
            source_files=source_files,
            prior_files=prior_files,
            manifest_payload=manifest_payload,
            instruction_payload=instruction_payload,
            expected_bytes=expected_bytes,
            changes=tuple(changes),
            conflict_issues=tuple(conflicts),
            validation_argv=self._validation_argv(request),
        )

    def _apply_present(self, plan: _TargetPlan) -> None:
        current_relatives = set(plan.source_files)
        for relative in plan.prior_files:
            if relative in current_relatives:
                continue
            destination = plan.skill_dir / relative
            expected = plan.expected_bytes[destination]
            if expected is not None:
                remove_owned_file(destination, expected=expected)

        for relative, payload in plan.source_files.items():
            destination = plan.skill_dir / relative
            expected = plan.expected_bytes[destination]
            if expected != payload:
                atomic_write(destination, payload, expected=expected)

        if plan.instruction_file is not None:
            expected = plan.expected_bytes[plan.instruction_file]
            if expected != plan.instruction_payload:
                atomic_write(
                    plan.instruction_file,
                    plan.instruction_payload or b"",
                    expected=expected,
                )

        expected_manifest = plan.expected_bytes[plan.manifest_path]
        if expected_manifest != plan.manifest_payload:
            atomic_write(
                plan.manifest_path,
                plan.manifest_payload or b"",
                expected=expected_manifest,
            )
        self._prune_empty_directories(plan.skill_dir)

    def _apply_absent(self, plan: _TargetPlan) -> None:
        if plan.instruction_file is not None:
            expected = plan.expected_bytes[plan.instruction_file]
            if expected != plan.instruction_payload:
                atomic_write(
                    plan.instruction_file,
                    plan.instruction_payload or b"",
                    expected=expected,
                )

        for relative in plan.prior_files:
            destination = plan.skill_dir / relative
            expected = plan.expected_bytes[destination]
            if expected is not None:
                remove_owned_file(destination, expected=expected)

        expected_manifest = plan.expected_bytes[plan.manifest_path]
        if expected_manifest is not None:
            remove_owned_file(plan.manifest_path, expected=expected_manifest)
        self._prune_empty_directories(plan.skill_dir)

    def _result(
        self,
        plan: _TargetPlan,
        *,
        applied: bool,
        validation: OnboardingValidation | None = None,
        error: str | None = None,
    ) -> TargetOnboardingResult:
        return TargetOnboardingResult(
            target=plan.request.target,
            desired_state=plan.request.desired_state,
            applied=applied,
            changes=plan.changes,
            validation=validation or self._validate(plan),
            validation_argv=plan.validation_argv,
            error=error,
        )

    def _validate(self, plan: _TargetPlan) -> OnboardingValidation:
        issues = list(plan.conflict_issues)
        if plan.request.desired_state is OnboardingDesiredState.PRESENT:
            manifest_ok = (
                plan.manifest_path.exists()
                and plan.manifest_path.read_bytes() == plan.manifest_payload
            )
            fingerprints_ok = all(
                (plan.skill_dir / relative).exists()
                and (plan.skill_dir / relative).read_bytes() == payload
                for relative, payload in plan.source_files.items()
            )
            entrypoint_ok = (plan.skill_dir / "SKILL.md").exists() and (
                plan.skill_dir / "SKILL.md"
            ).read_bytes() == plan.source_files.get(Path("SKILL.md"))
            managed_block_ok = self._managed_block_ok(plan.instruction_file, plan.skill_dir)
        else:
            manifest_ok = not plan.manifest_path.exists()
            fingerprints_ok = all(
                not (plan.skill_dir / relative).exists() for relative in plan.prior_files
            )
            entrypoint_ok = not (plan.skill_dir / "SKILL.md").exists()
            managed_block_ok = self._managed_block_absent(plan.instruction_file)

        if not entrypoint_ok:
            issues.append("entrypoint does not match the requested state")
        if not manifest_ok:
            issues.append("manifest does not match the requested state")
        if managed_block_ok is False:
            issues.append("managed instruction block does not match the requested state")
        if not fingerprints_ok:
            issues.append("generated file fingerprints do not match the requested state")
        matches = (
            entrypoint_ok
            and manifest_ok
            and managed_block_ok is not False
            and fingerprints_ok
            and not plan.conflict_issues
        )
        return OnboardingValidation(
            matches_desired_state=matches,
            entrypoint_ok=entrypoint_ok,
            manifest_ok=manifest_ok,
            managed_block_ok=managed_block_ok,
            fingerprints_ok=fingerprints_ok,
            issues=tuple(dict.fromkeys(issues)),
        )

    def _source_files(self) -> dict[Path, bytes]:
        return {
            path.relative_to(self._source): path.read_bytes()
            for path in sorted(self._source.rglob("*"))
            if path.is_file() and "__pycache__" not in path.parts
        }

    def _manifest(
        self,
        target: AgentTarget,
        files: dict[Path, bytes],
        instruction_file: Path | None,
        skill_dir: Path,
    ) -> SkillManifest:
        instruction_path = None
        block_fingerprint = None
        if instruction_file is not None:
            instruction_path = instruction_file.relative_to(self._project_root).as_posix()
            block_fingerprint = fingerprint(self._managed_block(skill_dir, b"\n"))
        return SkillManifest(
            package_version=version("qlibx"),
            target=target,
            files={path.as_posix(): fingerprint(payload) for path, payload in files.items()},
            instruction_path=instruction_path,
            managed_block_fingerprint=block_fingerprint,
        )

    @staticmethod
    def _load_manifest(path: Path) -> tuple[Manifest | None, bool]:
        if not path.exists():
            return None, False
        try:
            raw = path.read_text(encoding="utf-8")
            schema_version = json.loads(raw).get("schema_version")
            if schema_version == 1:
                return SkillManifestV1.model_validate_json(raw), False
            if schema_version == 2:
                return SkillManifest.model_validate_json(raw), False
            return None, True
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

    def _validation_argv(self, request: OnboardingRequest) -> tuple[str, ...]:
        argv = [
            "qlibx",
            "project",
            "onboard",
            str(self._project_root),
            "--target",
            request.target.value,
        ]
        if request.custom_root is not None:
            argv.extend(("--custom-root", request.custom_root))
        if request.desired_state is OnboardingDesiredState.ABSENT:
            argv.append("--remove")
        return tuple(argv)

    def _managed_block(self, skill_dir: Path, newline: bytes) -> bytes:
        relative_skill = skill_dir.relative_to(self._project_root).as_posix()
        return newline.join(
            (
                _START_BYTES,
                (
                    "Use the version-matched qlibx skill at "
                    f"{relative_skill}/SKILL.md for qlibx work."
                ).encode(),
                _END_BYTES,
            )
        )

    @staticmethod
    def _marker_span(payload: bytes) -> tuple[tuple[int, int] | None, str | None]:
        starts = payload.count(_START_BYTES)
        ends = payload.count(_END_BYTES)
        if starts == 0 and ends == 0:
            return None, None
        if starts != 1 or ends != 1:
            return None, "managed block markers must appear exactly once"
        start = payload.index(_START_BYTES)
        end_start = payload.index(_END_BYTES)
        if end_start < start:
            return None, "managed block end marker precedes start marker"
        return (start, end_start + len(_END_BYTES)), None

    @staticmethod
    def _newline(payload: bytes) -> bytes:
        return b"\r\n" if b"\r\n" in payload else b"\n"

    def _instruction_present_payload(
        self,
        current: bytes | None,
        skill_dir: Path,
    ) -> tuple[bytes, str | None]:
        payload = current or b""
        span, error = self._marker_span(payload)
        if error:
            return payload, error
        newline = self._newline(payload)
        block = self._managed_block(skill_dir, newline)
        if span is not None:
            return payload[: span[0]] + block + payload[span[1] :], None
        separator = b"" if not payload or payload.endswith(newline + newline) else newline
        return payload + separator + block + newline, None

    def _instruction_absent_payload(
        self,
        current: bytes | None,
    ) -> tuple[bytes | None, str | None]:
        if current is None:
            return None, None
        span, error = self._marker_span(current)
        if error:
            return current, error
        if span is None:
            return current, None
        return current[: span[0]] + current[span[1] :], None

    def _managed_block_ok(self, instruction_file: Path | None, skill_dir: Path) -> bool | None:
        if instruction_file is None:
            return None
        if not instruction_file.exists():
            return False
        payload = instruction_file.read_bytes()
        span, error = self._marker_span(payload)
        if error or span is None:
            return False
        actual = payload[span[0] : span[1]].replace(b"\r\n", b"\n")
        return actual == self._managed_block(skill_dir, b"\n")

    def _managed_block_absent(self, instruction_file: Path | None) -> bool | None:
        if instruction_file is None:
            return None
        if not instruction_file.exists():
            return True
        span, error = self._marker_span(instruction_file.read_bytes())
        return error is None and span is None

    @staticmethod
    def _prune_empty_directories(skill_dir: Path) -> None:
        if not skill_dir.exists():
            return
        directories = sorted(
            (path for path in skill_dir.rglob("*") if path.is_dir()),
            key=lambda path: len(path.parts),
            reverse=True,
        )
        directories.append(skill_dir)
        for directory in directories:
            try:
                directory.rmdir()
            except OSError:
                continue
