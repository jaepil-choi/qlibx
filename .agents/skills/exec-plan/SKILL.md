---
name: exec-plan
description: Create and maintain a restartable living plan for complex or long-running agent work.
---

# ExecPlan Workflow

Read `.agent/PLANS.md` completely before creating or updating a plan.

- Create one plan under `.agent/plans/active/` with an outcome-oriented name.
- Keep its status, milestones, progress, discoveries, decisions, validation, and next action current.
- After each milestone, record evidence before selecting the next milestone.
- Before compaction, make the plan sufficient for a fresh agent to resume without chat history.
- After repeated failure, change the hypothesis or strategy; do not rerun mechanically.
- On completion, set `Status: complete` and move the plan to `.agent/plans/completed/`.
- On an approval boundary or blocker, record the exact condition and the smallest required user action.
