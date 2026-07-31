# Promote PRD Candidate A with Constraint and Monitoring Contracts

Status: complete

## Purpose

Add the agreed selective-trigger, constraint-adjustment, validation, and independent monitoring
requirements to `docs/qlibx-prd-a.md`, then replace the canonical PRD with that candidate and remove
the superseded old PRD.

## Scope and non-goals

In scope:

- revise `docs/qlibx-prd-a.md`;
- delete `docs/qlibx-prd.md` and `docs/qlibx-prd-old.md`;
- move the revised candidate to `docs/qlibx-prd.md`;
- validate content, headings, code fences, exact paths, and Git state.

Non-goals:

- implementation changes;
- dependency changes;
- staging, committing, or pushing;
- fixing concrete Python class names or package layout in the PRD.

Constraints:

- Keep the requirements architecture-neutral.
- Treat the constraint optimizer as best-effort adjustment, not the compliance authority.
- Keep pre-execution validation and actual-account monitoring separate.
- Both strategy and compliance data obey their own point-in-time cutoff.
- Do not use `git apply`.
- Preserve unrelated worktree changes.

## Acceptance criteria

- The canonical PRD explains the flow from physical target through constraint adjustment,
  validation, execution, and actual-account monitoring.
- Selective trigger, explicit hold, dense account state, and independent monitoring clock are
  testable requirements.
- Constraint declaration, adjustment result, validation finding, and monitoring finding are
  portable result categories.
- Pre-execution error/warning behavior and post-execution actual-state monitoring are distinct.
- Compliance data has an independent requirement binding and cannot leak into strategy input
  without an explicit dependency.
- Acceptance scenarios cover monthly trigger/daily monitoring, passive breach, partial fill, and
  historical re-evaluation.
- `docs/qlibx-prd.md` exists with the revised candidate content.
- `docs/qlibx-prd-a.md` and `docs/qlibx-prd-old.md` no longer exist.

## Repository context

- Manifest canonical path: `docs/qlibx-prd.md`
- Candidate: `docs/qlibx-prd-a.md`
- Superseded comparison document: `docs/qlibx-prd-old.md`
- Both canonical and old PRDs are currently tracked and clean; the candidate is untracked.
- Related non-authoritative design records:
  `docs/thoughts/decision-clock-and-rebalance-trigger.md` and
  `docs/thoughts/constraint-limits-and-the-monitoring-clock.md`.

## Milestones

- [x] M1: Verify exact source, destination, deletion targets, and current Git state.
- [x] M2: Add semantic roles, invariants, data contracts, lifecycle, adjustment, validation,
  monitoring, artifact, and extension requirements.
- [x] M3: Add acceptance criteria and run content consistency checks.
- [x] M4: Remove superseded PRDs, promote the candidate to the canonical path, and validate final
  repository state.

## Progress

- Confirmed `.agent/project.yaml` declares `docs/qlibx-prd.md` as canonical.
- Confirmed all three PRD paths exist.
- Confirmed the candidate is untracked while the current and old PRDs have no local modifications.
- Added the agreed constraint and selective-trigger contracts across product thesis, semantics,
  invariants, ownership, data/PIT, lifecycle, construction, native execution, artifacts,
  monitoring, production, acceptance criteria, and compatibility gates.
- Changed the candidate header to canonical status in preparation for promotion.
- Deleted the prior canonical and old comparison PRDs and promoted the validated candidate to
  `docs/qlibx-prd.md`.

## Discoveries

- Current candidate already defines four clocks, explicit hold, trigger, physical construction,
  and generic monitoring, but lacks the agreed constraint-specific contracts.
- Existing physical-construction optimizer must remain distinct from the new execution-time
  constraint adjustment responsibility.
- A move-only apply-patch hunk was rejected as empty before any filesystem change. Retried with a
  context line; the combined delete/move then succeeded.

## Decision log

- Final pre-execution validation occurs after the last quantity-changing conversion or is repeated
  after such conversion.
- Constraint monitoring consumes actual account state and remains independent of strategy
  triggering.
- Exact public error-stage codes are product protocol and may be specified without fixing a class
  architecture.

## Validation

- Revised candidate: 2,279 lines.
- Code fences: 30 and balanced.
- Duplicate numbered headings: zero.
- No stale Candidate A, temporary-draft, or old §10.8 references remain.
- Required semantic roles, error stages, PIT separation, trigger evidence, monthly-decision/daily-
  monitoring acceptance, and historical as-was/as-if evaluation are present.
- No repository file outside the two PRDs scheduled for deletion references
  `qlibx-prd-a.md` or `qlibx-prd-old.md`.
- Pre-promotion candidate SHA-256:
  `1616FC6D08D3241247846AA8AF95EA718F400878E5025E02EFE1762131EBD46C`.
- Final canonical SHA-256 matches the candidate exactly:
  `1616FC6D08D3241247846AA8AF95EA718F400878E5025E02EFE1762131EBD46C`.
- Final filesystem state: canonical exists; candidate and old PRD do not exist.
- `git diff --check` reports no whitespace errors. Git only reports the repository's Windows
  LF-to-CRLF conversion warning.
- No remaining non-reference repository file mentions `qlibx-prd-a.md` or `qlibx-prd-old.md`.

## Risks and recovery

- Deleting tracked PRDs is intentional and explicitly authorized by the user.
- The candidate will be fully validated before destructive promotion.
- If promotion fails, leave the validated candidate intact and do not partially delete targets.

## Next action

Hand off the promoted canonical PRD for user review. Do not stage or commit until explicitly asked.
