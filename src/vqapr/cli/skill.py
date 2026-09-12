"""`vqapr skill install|remove|list` — 프로젝트의 agent skill 집합을 관리한다.

skill은 PRD §11.2가 정한 집합이고, target마다 `<target>/skills/vqapr-<skill-name>/`에 설치된다.
**두 target은 같은 bytes를 받는다.** 한쪽을 authoritative로 두고 다른 쪽에 pointer를 놓지 않는다.

이 파일은 예전에 그 반대를 했고, 이유는 이렇게 적혀 있었다 -- "복사본이 두 개가 되는 순간 하나는
반드시 stale해진다". 그 논증은 **드리프트를 탐지할 방법이 없을 때** 맞았다. 이제 출하 이력 표가
있어서 어긋난 사본이 target별·파일별로 이름을 드러내므로(`agent/skillset.py`), 막을 이유가
사라졌다. 반대로 pointer는 읽는 쪽에 한 단계를 더 강요하는데, 그것은 PRD §11.2가 중첩 참조를
금지한 것과 같은 문제다.

판정은 이 파일이 하지 않는다. `agent/skillset.py`가 소유하고 여기는 동사와 봉투만 담당한다 --
record `168`: CLI만 묻는 판정은 결함이다.

설치 루트는 workspace root -- 다른 모든 명령이 일하는 그 디렉터리(현재 디렉터리, 또는
`vqapr --project-root`)이며 `--into`로 덮어쓴다. `AGENTS.md`와 `CLAUDE.md`는 건드리지 않는다.

전에는 `.git`이 있는 가장 가까운 조상이었다. 프로젝트가 다른 저장소 안에 들어 있으면 skill이 그
바깥 저장소에 깔렸고, 그 저장소를 연 agent가 부르지 않은 skill을 읽었다. 다른 모든 명령이 부르는
stale 검사(`upgrade_note`)는 workspace root를 읽으므로 그렇게 깔린 사본은 한 번도 검사되지 않았다 --
루트가 둘이었다. 설치 위치를 추측하지 않는 것은 PRD §11.2의 규칙이다(record `258`).
"""

from __future__ import annotations

import argparse
import contextlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from vqapr.agent.skillset import (
    MANIFEST_NAME,
    WRITABLE_WITHOUT_FORCE,
    FileState,
    SkillVerdict,
    judge,
    package_version,
    read_manifest,
    released_hashes,
    shipped_skills,
)
from vqapr.cli.envelope import success
from vqapr.domain.errors import InputError, Status

_TARGET_ROOTS = {
    "agents": Path(".agents") / "skills",
    "claude": Path(".claude") / "skills",
}
"""target별 skill 뿌리. 두 이름은 PRD §11.2의 normative contract다."""

_DIRECTORY_PREFIX = "vqapr-"
"""skill directory 이름은 `vqapr-<skill-name>`.

접두사가 필요한 이유는 이 뿌리를 vqapr가 독점하지 않기 때문이다 -- 같은 `skills/` 아래에 다른
도구와 사용자의 skill이 함께 산다. 접두사가 없으면 `register-dataset` 같은 일반적인 이름이 남의
것과 충돌한다.
"""


def _resolve_targets(target: str) -> tuple[str, ...]:
    return tuple(_TARGET_ROOTS) if target == "both" else (target,)


def _read_installed(skill_dir: Path) -> dict[str, bytes]:
    """설치된 skill directory 안의 모든 파일. `{상대 posix 경로: 내용}`.

    출하 목록이 아니라 **디스크에 있는 것 전부**를 읽는다. 그래야 우리가 출하한 적 없는 파일이
    `UNKNOWN`으로 드러난다 -- 그것을 안 읽으면 사용자가 넣어둔 파일을 못 본 채 디렉터리를
    지우게 된다.
    """
    if not skill_dir.is_dir():
        return {}
    found: dict[str, bytes] = {}
    for path in sorted(skill_dir.rglob("*")):
        if not path.is_file():
            continue
        found[path.relative_to(skill_dir).as_posix()] = path.read_bytes()
    return found


def _verdicts(root: Path, target: str) -> dict[str, SkillVerdict]:
    """한 target에 설치된 모든 skill의 판정."""
    shipped = shipped_skills()
    released = released_hashes()
    base = root / _TARGET_ROOTS[target]
    return {
        name: judge(
            name,
            _read_installed(base / f"{_DIRECTORY_PREFIX}{name}"),
            shipped=files,
            released=released,
        )
        for name, files in shipped.items()
    }


def _verdict_body(verdict: SkillVerdict) -> dict[str, Any]:
    """한 skill의 판정을 봉투에 실을 모양으로."""
    body: dict[str, Any] = {"state": verdict.state.value}
    detail = {
        state.value: [f.path for f in verdict.files if f.state is state]
        for state in (FileState.OUTDATED, FileState.MODIFIED, FileState.ABSENT, FileState.UNKNOWN)
    }
    body.update({key: paths for key, paths in detail.items() if paths})
    return body


def _require_shipped() -> Mapping[str, Mapping[str, bytes]]:
    shipped = shipped_skills()
    if not shipped:
        raise InputError(
            "argument.skill_empty",
            requirement="the vqapr package must ship agent skills",
            observed="no skill directories found in the skill resource package",
            # 호출자가 고칠 수 있는 것이 아니다: skill 없이 설치된 package는 packaging 결함이고,
            # status가 그것을 upstream에 보고하라고 말한다.
            status=Status.INTERNAL,
        )
    return shipped


def _install(root: Path, *, targets: tuple[str, ...], dry_run: bool, force: bool) -> dict[str, Any]:
    shipped = _require_shipped()

    planned: dict[str, dict[str, Any]] = {}
    written: list[str] = []
    refused: list[str] = []
    preserved: list[str] = []

    for target in targets:
        base = root / _TARGET_ROOTS[target]
        per_target: dict[str, Any] = {}
        for name, verdict in _verdicts(root, target).items():
            skill_dir = base / f"{_DIRECTORY_PREFIX}{name}"
            per_target[name] = _verdict_body(verdict)
            preserved.extend(str(skill_dir / path) for path in verdict.not_ours)

            for file_verdict in verdict.files:
                if file_verdict.state is FileState.UNKNOWN:
                    continue
                target_path = skill_dir / file_verdict.path
                writable = file_verdict.state in WRITABLE_WITHOUT_FORCE or force
                if not writable:
                    refused.append(str(target_path))
                    continue
                if file_verdict.state is FileState.CURRENT:
                    continue
                if not dry_run:
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    target_path.write_bytes(shipped[name][file_verdict.path])
                written.append(str(target_path))

        planned[target] = per_target

        if not dry_run:
            base.mkdir(parents=True, exist_ok=True)
            manifest = {
                "package_version": package_version(),
                "target": target,
                "skills": sorted(shipped),
            }
            (base / MANIFEST_NAME).write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )

    kind = "skill.install.dry_run" if dry_run else "skill.install"
    body: dict[str, Any] = {
        "root": str(root),
        "targets": list(targets),
        "skills": planned,
        "written": written,
    }
    if refused:
        body["refused"] = refused
        # 문장이 지목하는 flag가 실제로 존재해야 한다. `docs/issues/archive/025`는 없는 flag를
        # 지목한 메시지가 남긴 비용의 기록이고, 그 비용은 읽는 사람마다 다시 든다.
        body["note"] = (
            "these files differ from every release vqapr has shipped, so they hold edits that are "
            "not ours to discard; they were left alone. Run `vqapr skill install --force` to "
            "overwrite them."
        )
    if preserved:
        body["preserved"] = preserved
    return success(kind, **body)


def _remove(root: Path, *, targets: tuple[str, ...], force: bool) -> dict[str, Any]:
    removed: list[str] = []
    skipped: list[str] = []
    preserved: list[str] = []

    for target in targets:
        base = root / _TARGET_ROOTS[target]
        for name, verdict in _verdicts(root, target).items():
            skill_dir = base / f"{_DIRECTORY_PREFIX}{name}"
            for file_verdict in verdict.files:
                path = skill_dir / file_verdict.path
                if file_verdict.state is FileState.UNKNOWN:
                    # 우리가 출하한 적 없는 경로다. 우리 것이 아니므로 제거 대상이 아니다.
                    preserved.append(str(path))
                    continue
                if file_verdict.state is FileState.ABSENT:
                    continue
                if file_verdict.state is FileState.MODIFIED and not force:
                    skipped.append(str(path))
                    continue
                path.unlink()
                removed.append(str(path))
            _prune(skill_dir)

        manifest_path = base / MANIFEST_NAME
        if manifest_path.is_file():
            manifest_path.unlink()
            removed.append(str(manifest_path))
        _prune(base)

    body: dict[str, Any] = {"removed": removed, "skipped": skipped}
    if skipped:
        body["note"] = (
            "these files differ from every release vqapr has shipped, so they were kept. "
            "Run `vqapr skill remove --force` to remove them."
        )
    if preserved:
        body["preserved"] = preserved
    return success("skill.remove", **body)


def _prune(directory: Path) -> None:
    """빈 디렉터리만 지운다. 안에 무엇이 남아 있으면 그대로 둔다."""
    with contextlib.suppress(OSError):
        directory.rmdir()


def _list(root: Path, *, targets: tuple[str, ...]) -> dict[str, Any]:
    shipped = _require_shipped()
    per_target: dict[str, Any] = {}
    any_installed = False

    for target in targets:
        base = root / _TARGET_ROOTS[target]
        manifest = read_manifest(base / MANIFEST_NAME)
        verdicts = _verdicts(root, target)
        installed = any(v.state is not FileState.ABSENT for v in verdicts.values())
        any_installed = any_installed or installed
        per_target[target] = {
            "directory": str(base),
            "installed": installed,
            "installed_from": (manifest or {}).get("package_version"),
            "skills": {name: _verdict_body(v) for name, v in verdicts.items()},
        }

    return success(
        "skill.list",
        root=str(root),
        package_version=package_version(),
        installed=any_installed,
        available=sorted(shipped),
        targets=per_target,
    )


_INTO_HELP = (
    "act on this directory instead of the workspace root (the current directory, or --project-root)"
)

_TARGET_HELP = (
    "which target's skill directory to act on (default: both). Both receive identical bytes."
)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="skill_action", required=True, metavar="ACTION")

    install_parser = sub.add_parser("install", help="install the agent skills into this project")
    install_parser.add_argument(
        "--target", choices=("agents", "claude", "both"), default="both", help=_TARGET_HELP
    )
    install_parser.add_argument("--into", type=Path, default=None, help=_INTO_HELP)
    install_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what each file's state is and what would be written, without writing",
    )
    install_parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "overwrite files that differ from every release vqapr has shipped. Without it, an "
            "outdated file is updated silently and an edited one is left alone and reported"
        ),
    )

    remove_parser = sub.add_parser("remove", help="remove the installed agent skills")
    remove_parser.add_argument(
        "--target", choices=("agents", "claude", "both"), default="both", help=_TARGET_HELP
    )
    remove_parser.add_argument("--into", type=Path, default=None, help=_INTO_HELP)
    remove_parser.add_argument(
        "--force",
        action="store_true",
        help="remove even the files that differ from every release vqapr has shipped",
    )

    # `--into`는 셋 다 받는다. `list`는 다른 디렉터리에 대해 물을 일이 가장 많고("저쪽에는
    # 깔려 있나?"), 형제 셋 중 둘에서만 되는 옵션은 경계가 아니라 버그로 읽힌다.
    list_parser = sub.add_parser(
        "list", help="show which skills are installed and whether each matches what vqapr ships"
    )
    list_parser.add_argument(
        "--target", choices=("agents", "claude", "both"), default="both", help=_TARGET_HELP
    )
    list_parser.add_argument("--into", type=Path, default=None, help=_INTO_HELP)


def run(args: argparse.Namespace, *, project_root: Path) -> dict[str, Any]:
    # The root `upgrade_note` reads, so the skills a command warns about are the skills installed.
    root = Path(args.into or project_root).resolve()
    targets = _resolve_targets(args.target)
    action = args.skill_action
    if action == "install":
        return _install(root, targets=targets, dry_run=args.dry_run, force=args.force)
    if action == "remove":
        return _remove(root, targets=targets, force=args.force)
    if action == "list":
        return _list(root, targets=targets)

    raise InputError(
        "argument.unknown_action",
        requirement="skill action must be install, remove, or list",
        observed=action,
        status=Status.INVALID,
    )
