# Rewrite qlibx PRD around a balanced native-first Qlib boundary

Status: complete

## Purpose

Preserve the current canonical PRD as `docs/qlibx-prd-old.md`, replace
`docs/qlibx-prd.md` with a newly structured product requirements document that
integrates the balanced and source-checked conclusions from both deeper Qlib
integration research documents, and remove the superseded files under
`docs/research/`.

## Scope and non-goals

In scope:

- Rename the current `docs/qlibx-prd.md` to `docs/qlibx-prd-old.md`.
- Write a new canonical `docs/qlibx-prd.md`.
- Preserve the product requirements that remain valid while removing duplicated
  implementation discussion.
- Integrate verified native Qlib reuse boundaries, signed-alpha limitations,
  clock semantics, initial-position accounting, diagnostics, optimizer,
  persistence, PIT, and production OMS boundaries.
- Delete the two files currently under `docs/research/` after their durable
  conclusions are represented in the new PRD.

Out of scope:

- Production source changes.
- Dependency changes.
- Architecture class design or migration implementation.
- Deleting `references/` or the untracked Qlib paper.
- Staging, committing, or pushing.

## Acceptance criteria

- `docs/qlibx-prd-old.md` is byte-for-byte equal to the pre-task
  `docs/qlibx-prd.md`.
- A new `docs/qlibx-prd.md` exists and is self-contained.
- The new PRD clearly separates Qlib runtime-kernel responsibilities from qlibx
  control-plane and evidence responsibilities.
- Long-short research diagnostics are distinguished from executable short
  portfolio accounting.
- Dynamic matched capitalization remains canonical; static initial endowment is
  explicitly bounded and does not silently satisfy full P6.
- Dense-calendar hold, portfolio-metric enablement, initial-position NAV
  denominator, per-order diagnostic preservation, provider isolation, PIT, and
  optimizer fallback requirements are explicit.
- Qlib `EnhancedIndexingOptimizer` is not described as mathematically equivalent
  to the qlibx optimizer contract.
- Qlib Recorder and config-driven workflow reuse do not replace the portable
  qlibx artifact/catalog contract.
- `docs/research/` contains no files after the rewrite.
- Markdown references to deleted research files are absent from the new PRD.
- Whitespace and link checks complete without errors attributable to this task.

## Repository context

- Canonical product requirements: `docs/qlibx-prd.md`
- Research inputs:
  - `docs/research/qlib-deeper-integration-claude.md`
  - `docs/research/qlib-deeper-integration-codex.md`
- Installed Qlib contract examined during the preceding investigation:
  `pyqlib==0.9.7`
- Current research files have user-visible modifications and are intentionally
  deleted only after their conclusions are incorporated.
- `references/` is non-authoritative and is not modified.

## Milestones

- [x] M1: Inventory the old PRD and both research documents into a replacement
  outline and requirement checklist.
- [x] M2: Preserve the old PRD and write the new canonical PRD.
- [x] M3: Validate coverage against the old PRD and research findings, then
  remove superseded research files.
- [x] M4: Run final filesystem, Markdown, diff, and status validation.

## Progress

- 2026-07-31: Confirmed exactly two files under `docs/research/`; both are in
  scope for deletion.
- 2026-07-31: Confirmed the current PRD has 2,085 lines and is not modified in
  the worktree.
- 2026-07-31: Completed the replacement outline. The new PRD will preserve
  onboarding, capability binding, error stages, logical datasets, PIT,
  StrategyAgent, signed research, catalog, ensemble, physical construction,
  signed execution, artifacts/reporting, extensions, and production OMS
  boundaries while consolidating native-Qlib integration requirements.
- 2026-07-31: Preserved the old PRD with SHA-256
  `BB6BA9B57CBF2167AE06746E0330BBA96EB923FCB928EE66057FDFBC4255B2BD`.
- 2026-07-31: Wrote a 17-section replacement PRD covering the complete
  product surface and the verified native-Qlib integration boundary.
- 2026-07-31: Deleted both superseded research files after coverage checks.
- 2026-07-31: Final validation found 0 research files, balanced Markdown
  fences, no missing local links, and no stale research references in the new
  PRD.

## Discoveries

- `cvxpy` is already a declared and installed dependency. The installed solver
  set does not include ECOS, while Qlib 0.9.7's enhanced-index optimizer
  hard-codes ECOS and falls back to current weights after solver failure.
- Qlib `Account` uses `init_cash` both as position cash and the first portfolio
  return denominator; initial stock positions therefore require explicit
  starting-NAV treatment.
- The current qlibx exchange holds only one last execution diagnostic, while the
  native SimulatorExecutor can execute multiple orders before qlibx regains
  control.
- Qlib Account defaults portfolio metrics on, but every native executor defaults
  `generate_portfolio_metrics` off and resets the Account flag. Dense no-trade
  rows therefore require an explicit enabled executor profile.

## Decision log

- Preserve dynamic matched capitalization as the canonical full signed
  compatibility requirement because it is already required by the current PRD.
- Treat static initial endowment as a bounded optional profile, not an automatic
  replacement.
- Describe Qlib's enhanced-index optimizer as a comparison or conditional
  backend behind the qlibx result contract, not as a 1:1 mathematical core.
- Keep implementation class names, subclass choices, and migration phases out of
  the product requirements.

## Validation

- Old PRD archive SHA-256:
  `BB6BA9B57CBF2167AE06746E0330BBA96EB923FCB928EE66057FDFBC4255B2BD`
- New PRD: 1,304 lines before final whitespace cleanup, 17 top-level sections.
- Markdown fences: 18, balanced.
- Local Markdown links: 1, all resolved.
- `docs/research/` file count: 0.
- Required native-Qlib boundary terms and acceptance criteria: present.
- New PRD references to deleted research files: none.
- `git diff --check`: passed after the final whitespace cleanup; only the
  repository line-ending warning was emitted.

## Risks and recovery

- The old PRD must be preserved before replacement. Verify its hash before and
  after the rename.
- Research files contain modified user work. Their deletion is explicitly
  authorized, but only after coverage validation.
- If the new PRD loses a material existing product requirement, restore the
  missing requirement from `docs/qlibx-prd-old.md`; do not edit the archive.

## Next action

Move this completed plan to `.agent/plans/completed/` and report the rewritten
PRD, preserved archive, deletions, and validation result.
