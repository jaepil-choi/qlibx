# ExecPlan Standard

Use an ExecPlan for complex features, significant refactors, long-running investigations, or work
that must remain restartable after context compaction.

An ExecPlan must be self-contained. A new agent should be able to continue from the plan and the
repository without relying on chat history.

## Required properties

- State the user-visible or observable outcome.
- Define scope, non-goals, constraints, and acceptance criteria.
- Describe the current repository state using concrete paths and symbols.
- Divide work into bounded milestones with observable validation.
- Maintain `Progress`, `Discoveries`, `Decision Log`, and `Validation`.
- Record failed approaches when they affect the next hypothesis.
- Keep the next action explicit and restartable.
- Move a completed plan from `.agent/plans/active/` to `.agent/plans/completed/`.

## Template

```markdown
# <Outcome-oriented title>

Status: in_progress

## Purpose

## Scope and non-goals

## Acceptance criteria

## Repository context

## Milestones

- [ ] M1:
- [ ] M2:

## Progress

## Discoveries

## Decision log

## Validation

## Risks and recovery

## Next action
```

Update the plan after each milestone and before compaction. `Status` must be one of
`in_progress`, `needs_approval`, `blocked`, or `complete`.
