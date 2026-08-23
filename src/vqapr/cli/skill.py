"""`vqapr skill install|remove|list` — manage the agent skill in a project.

스킬은 `.agents/skills/vqapr/`에 설치된다. Claude 타겟이 요청되면 `.claude/skills/vqapr-skill/`에
thin adapter를 추가로 놓는다. adapter는 `.agents/skills/vqapr/SKILL.md`를 읽으라는 한 줄짜리
포인터이며, 본문을 복사하지 않는다 — 복사본이 두 개가 되는 순간 하나는 반드시 stale해진다.

설치 루트는 `.git`이 있는 가장 가까운 조상이며, `--into`로 덮어쓸 수 있다.
`AGENTS.md`와 `CLAUDE.md`는 건드리지 않는다.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
from importlib import metadata, resources
from pathlib import Path
from typing import Any

from vqapr.cli.envelope import success
from vqapr.cli.inputs import InputError

_SKILL_PACKAGE = "vqapr.agent.skill"

_AGENTS_SKILL_DIR = ".agents/skills/vqapr"
_CLAUDE_SKILL_DIR = ".claude/skills/vqapr-skill"

_MANIFEST_NAME = ".vqapr-skill.json"

_ADAPTER_BODY = """\
---
name: vqapr
description: Thin adapter — read the full skill at .agents/skills/vqapr/SKILL.md
---

This is an adapter. The authoritative skill file is at `.agents/skills/vqapr/SKILL.md`.
Read that file before acting.
"""


def _package_version() -> str:
    """The installed distribution's version, or a marker when it cannot be read.

    An editable install still reports a version, and the manifest pairs it with per-file sha256 so
    content drift is detectable even when the version does not move.
    """
    try:
        return metadata.version("vqapr")
    except metadata.PackageNotFoundError:
        return "unknown"


def _find_git_root(start: Path) -> Path | None:
    """Walk up from *start* looking for `.git`."""
    for parent in (start, *start.parents):
        if (parent / ".git").exists():
            return parent
    return None


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


_INSTALLED_FILES = ("SKILL.md",)
"""What actually gets installed.

`README.md`는 제외한다. 그것은 이 디렉터리를 유지보수하는 사람에게 하는 말이지 skill을 읽는
agent에게 하는 말이 아니다. 설치본에 섞이면 agent가 자기 대상이 아닌 문서를 권위로 읽는다.
"""


def _collect_skill_files() -> dict[str, bytes]:
    """Read the files this package ships as installable skill content."""
    ref = resources.files(_SKILL_PACKAGE)
    files: dict[str, bytes] = {}
    for name in _INSTALLED_FILES:
        item = ref / name
        if item.is_file():
            files[name] = item.read_bytes()
    return files


def _install(root: Path, *, targets: tuple[str, ...], dry_run: bool) -> dict[str, Any]:
    skill_dir = root / _AGENTS_SKILL_DIR

    if dry_run:
        resolved: dict[str, str] = {"agents": str(skill_dir)}
        if "claude" in targets or "both" in targets:
            resolved["claude"] = str(root / _CLAUDE_SKILL_DIR)
        return success("skill.install.dry_run", root=str(root), paths=resolved)

    # Collect source files from the package resource.
    source_files = _collect_skill_files()
    if not source_files:
        raise InputError(
            "cli.input.skill_empty",
            requirement="the vqapr package must ship skill files",
            observed="no files found in the skill resource directory",
        )

    # Write skill files.
    skill_dir.mkdir(parents=True, exist_ok=True)
    manifest_entries: dict[str, dict[str, str]] = {}
    installed_paths: list[str] = []
    for name, content in sorted(source_files.items()):
        target = skill_dir / name
        target.write_bytes(content)
        manifest_entries[name] = {"sha256": _sha256(content)}
        installed_paths.append(str(target))

    # Claude adapter.
    if "claude" in targets or "both" in targets:
        claude_dir = root / _CLAUDE_SKILL_DIR
        claude_dir.mkdir(parents=True, exist_ok=True)
        adapter_path = claude_dir / "SKILL.md"
        adapter_path.write_text(_ADAPTER_BODY, encoding="utf-8")
        installed_paths.append(str(adapter_path))

    manifest = {
        "package_version": _package_version(),
        "files": manifest_entries,
    }
    manifest_path = skill_dir / _MANIFEST_NAME
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    return success(
        "skill.install",
        root=str(root),
        files=installed_paths,
        manifest=str(manifest_path),
    )


def _remove(root: Path, *, force: bool) -> dict[str, Any]:
    skill_dir = root / _AGENTS_SKILL_DIR
    manifest_path = skill_dir / _MANIFEST_NAME
    removed: list[str] = []
    skipped: list[str] = []

    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for name, meta in manifest.get("files", {}).items():
            path = skill_dir / name
            if not path.exists():
                continue
            if not force and _sha256(path.read_bytes()) != meta.get("sha256"):
                skipped.append(str(path))
                continue
            path.unlink()
            removed.append(str(path))
        manifest_path.unlink()
        removed.append(str(manifest_path))
    elif force:
        # No manifest — remove everything if forced.
        if skill_dir.exists():
            for path in skill_dir.iterdir():
                path.unlink()
                removed.append(str(path))
    else:
        return success("skill.remove", removed=[], skipped=[], note="no manifest found")

    # Clean empty dirs.
    for d in (skill_dir, root / _CLAUDE_SKILL_DIR):
        if d.exists():
            adapter = d / "SKILL.md"
            if adapter.exists():
                adapter.unlink()
                removed.append(str(adapter))
            with contextlib.suppress(OSError):
                d.rmdir()

    return success("skill.remove", removed=removed, skipped=skipped)


def _list(root: Path) -> dict[str, Any]:
    skill_dir = root / _AGENTS_SKILL_DIR
    manifest_path = skill_dir / _MANIFEST_NAME
    if not manifest_path.exists():
        return success("skill.list", installed=False, root=str(root))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = list(manifest.get("files", {}).keys())
    return success(
        "skill.list",
        installed=True,
        root=str(root),
        package_version=manifest.get("package_version", "unknown"),
        files=files,
    )


_INTO_HELP = "install into this directory instead of the auto-detected .git root"


def add_arguments(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="skill_action", required=True, metavar="ACTION")

    install_parser = sub.add_parser("install", help="install the agent skill into this project")
    install_parser.add_argument(
        "--target",
        choices=("agents", "claude", "both"),
        default="both",
        help="which skill directory to target (default: both)",
    )
    install_parser.add_argument("--into", type=Path, default=None, help=_INTO_HELP)
    install_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the resolved paths and exit without writing",
    )

    remove_parser = sub.add_parser("remove", help="remove the installed agent skill")
    remove_parser.add_argument("--into", type=Path, default=None, help=_INTO_HELP)
    remove_parser.add_argument(
        "--force",
        action="store_true",
        help="remove even if files have been modified since install",
    )

    # `--into` is accepted by all three. `list` is the action most likely to be asked about a
    # directory other than the current one ("is it installed over there?"), and an option that
    # works on two of three sibling actions reads as a bug rather than as a boundary.
    list_parser = sub.add_parser(
        "list", help="show whether the skill is installed and which files are present"
    )
    list_parser.add_argument("--into", type=Path, default=None, help=_INTO_HELP)


def run(args: argparse.Namespace, *, project_root: Path) -> dict[str, Any]:
    root = Path(args.into) if getattr(args, "into", None) else _find_git_root(project_root)
    if root is None:
        raise InputError(
            "cli.input.no_git_root",
            requirement="skill install needs a .git root (or pass --into)",
            observed=f"no .git found above {project_root}",
        )

    action = args.skill_action
    if action == "install":
        return _install(root, targets=(args.target,), dry_run=args.dry_run)
    if action == "remove":
        return _remove(root, force=getattr(args, "force", False))
    if action == "list":
        return _list(root)

    raise InputError(
        "cli.input.unknown_action",
        requirement="skill action must be install, remove, or list",
        observed=action,
    )
