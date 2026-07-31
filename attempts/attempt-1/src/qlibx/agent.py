"""Version-matched agent instructions for interactive data registration."""

from __future__ import annotations

from pathlib import Path

from qlibx.documentation import (
    error_guidance,
    help_topic,
    public_example,
    public_schema,
    task_guide,
)
from qlibx.onboarding import (
    apply_instruction,
    detect_instruction_targets,
    plan_instruction,
    remove_instruction,
)
from qlibx.skill import SkillPlan, apply_agent_skill, plan_agent_skill


def generate_data_skill(output: str | Path, *, force: bool = False) -> Path:
    plan = plan_agent_skill(output)
    return apply_agent_skill(plan, force=force)


__all__ = [
    "SkillPlan",
    "apply_agent_skill",
    "apply_instruction",
    "detect_instruction_targets",
    "error_guidance",
    "generate_data_skill",
    "help_topic",
    "plan_agent_skill",
    "plan_instruction",
    "public_example",
    "public_schema",
    "remove_instruction",
    "task_guide",
]
