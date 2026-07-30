"""Idempotent, user-content-preserving agent onboarding."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from qlibx.errors import QlibxError
from qlibx.project import Project
from qlibx.serialization import digest_text

START = "<!-- qlibx:managed:start -->"
END = "<!-- qlibx:managed:end -->"


@dataclass(frozen=True, slots=True)
class InstructionPlan:
    path: Path
    action: str
    before: str
    after: str
    existed: bool
    before_digest: str


def plan_instruction(project: Project, target: str | Path) -> InstructionPlan:
    path = project.contained(target)
    existed = path.exists()
    before = path.read_text(encoding="utf-8") if existed else ""
    block = (
        f"{START}\n"
        "Use `qlibx --help`, `qlibx data requirements`, and the generated qlibx skill. "
        "Treat project source data as read-only; use only public qlibx APIs; never edit installed "
        "qlibx or Qlib.\n"
        f"{END}"
    )
    if START in before or END in before:
        if before.count(START) != 1 or before.count(END) != 1:
            raise ValueError("instruction file has an invalid qlibx managed block")
        start = before.index(START)
        end = before.index(END, start) + len(END)
        after = before[:start] + block + before[end:]
        action = "unchanged" if after == before else "update"
    else:
        separator = "" if not before else ("" if before.endswith("\n\n") else "\n\n")
        after = before + separator + block + "\n"
        action = "create" if not path.exists() else "append"
    return InstructionPlan(path, action, before, after, existed, digest_text(before))


def apply_instruction(plan: InstructionPlan) -> Path:
    exists = plan.path.exists()
    current = plan.path.read_text(encoding="utf-8") if exists else ""
    if exists != plan.existed or digest_text(current) != plan.before_digest:
        raise QlibxError(
            "ONBOARDING",
            f"Instruction file changed after planning: {plan.path}",
            expected="Create a new dry-run plan and review the updated user content.",
        )
    plan.path.parent.mkdir(parents=True, exist_ok=True)
    staging = plan.path.with_name(f".{plan.path.name}.{uuid4().hex}.staging")
    try:
        staging.write_text(plan.after, encoding="utf-8")
        staging.replace(plan.path)
    finally:
        staging.unlink(missing_ok=True)
    return plan.path


def remove_instruction(project: Project, target: str | Path) -> InstructionPlan:
    path = project.contained(target)
    existed = path.exists()
    before = path.read_text(encoding="utf-8") if existed else ""
    if START not in before or END not in before:
        return InstructionPlan(path, "unchanged", before, before, existed, digest_text(before))
    start = before.index(START)
    end = before.index(END, start) + len(END)
    after = (before[:start] + before[end:]).replace("\n\n\n", "\n\n")
    return InstructionPlan(path, "remove", before, after, existed, digest_text(before))


def detect_instruction_targets(project: Project) -> tuple[dict[str, object], ...]:
    """Detect supported agent instruction files without creating anything."""
    return tuple(
        {
            "target": name,
            "path": str(project.root / name),
            "exists": (project.root / name).is_file(),
            "managed": (
                START in (project.root / name).read_text(encoding="utf-8")
                if (project.root / name).is_file()
                else False
            ),
        }
        for name in ("AGENTS.md", "CLAUDE.md")
    )
