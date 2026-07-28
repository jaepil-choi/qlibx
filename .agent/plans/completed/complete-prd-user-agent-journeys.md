# Complete every qlibx PRD user and agent journey

Status: complete

## Purpose

Make every scenario in canonical `docs/qlibx-prd.md` work through installed public qlibx surfaces,
then prove the human and AI-agent journeys against real project data and isolated artifacts.

## Scope and non-goals

- In scope: PRD P0-P7 and sections 3-12, public CLI/API/docs/schema/examples/errors, point-in-time
  data, StrategyAgent, signed alpha, research history, ensemble/enhanced index, Qlib execution,
  extensions, portable artifacts, reporting, concurrent publication and recovery.
- `references/` is comparative implementation material only; it is never runtime input and is not
  modified.
- Protected upstream `data/preprocessed`, `data/Dataguide`, and `data/DW` remain read-only.
- Current branch only; no stage, commit, push, publish or upstream-source mutation.
- Non-goal: claim native borrow/margin/recall/borrow-fee support or replace Qlib execution.

## Acceptance criteria

- Every P0-P7 bullet has direct public-surface evidence in `.agent/runs/prd-journey-audit.md`.
- Fresh onboarding/data and real research/execution journeys work from an isolated wheel.
- Failure/invalid/incomplete, cache, conflict, recovery, stale CAS, three-process publication,
  frozen-input stability and no-look-ahead are exercised.
- Stored ensemble and reporting do not invoke original strategies.
- Qlib matched mode proves actual SELL/partial fill, `A=C-B`, non-negative composite, NAV-neutral
  capitalization, blocked-cover retention/release, active denominator and checkpoint parity.
- Wheel and sdist boundaries exclude all project-owned state and require `pyqlib==0.9.7`.
- Upstream hashes and protected Git paths remain unchanged; config contains only user-authored YAML.

## Milestones

- [x] M1: Requirement-to-evidence audit for every P0-P7 bullet and journey step.
- [x] M2: P0/P1 onboarding, discovery, mapping, validation, registration and daily profile.
- [x] M3: P2/P3 StrategyAgent lifecycle, Qlib feedback, nesting, resume, transforms and diagnostics.
- [x] M4: P4 proposal/session/freeze/publication/query/orthogonality/concurrency/recovery/CAS.
- [x] M5: P5/P6 stored ensemble, enhanced index, ETF/look-through and signed Qlib invariants.
- [x] M6: P7 extension validation, artifact export/import and composable reporting.
- [x] M7: Fresh real-data human/agent journey, negative paths and isolated-wheel showcase.
- [x] M8: Final Ruff/format/lock/test/artifact/protected-boundary completion gate.

## Progress

- 2026-07-27: Reopened the audit because the original narrow prototype did not prove the PRD.
- 2026-07-27: Rebuilt YAML data registration/loader with separate event and availability clocks and
  canonical generated Parquet only under `data/qlibx/`.
- 2026-07-27: Added installed task docs/schema/examples/errors, safe instruction/skill onboarding,
  structured recovery guidance and user-confirmation markers.
- 2026-07-27: Implemented deterministic StrategyAgent, nested isolation/composition, complete alpha
  diagnostics and direct Qlib decision/confirmed-feedback/checkpoint integration.
- 2026-07-27: Implemented frozen/concurrent research publication, context query, three-level
  orthogonality, stored ensemble, physical/ETF/look-through portfolio, signed execution, artifact,
  extension and reporting journeys.
- 2026-07-27: Removed the discarded availability-indexed PnL experiment. Current PnL evidence is
  only `experiments/exp_003_event_time_qlib_pnl`.
- 2026-07-27: Final wheel passed all 77 tests on Python 3.10.20, 3.11.15 and 3.12.13. Python 3.12
  wheel passed the real-data showcase.
- 2026-07-27: Final protected-boundary gate passed: branch `exp/one-shot`, staged/protected changes
  zero, upstream hashes 3/3 unchanged, config 8/8 YAML, stale experiment absent.

## Decisions and discoveries

- `available_at` controls access. A separate event/observation field exists only when the user
  explicitly maps it and never acts as the availability proxy.
- Registration copies user-confirmed opaque information and never interprets correction factors.
- Public error recovery and exact executable journey examples are required agent surfaces, not
  optional prose.
- Matched capitalization remains an explicitly labeled Qlib long-only compatibility mode.
- A first non-elevated Windows artifact-test run failed to create `C:\tmp` pytest state. Re-running
  with a new explicit base temp under the corporate-Windows procedure passed all tests; this was an
  environment permission failure, not a package failure.

## Current validation evidence

- Source: 77 passed.
- Wheel: 77 passed independently on Python 3.10, 3.11 and 3.12, imported from `site-packages`.
- Real wheel showcase: PASS; 1,020 SELL orders, 2,201 positive fills, 1,180 short rows.
- Wheel SHA-256:
  `dd5853a55b877f4aeabedee1deaf45b2d255698a68bc62dc63a5288aa0bfb6cf`.
- Sdist SHA-256:
  `1f2e46a596a76537cfd392148f7787f04d2ecb702436b5bb9a164efc1297b393`.
- Sdist rebuild produced the identical wheel hash; both artifacts contain 56 files and no
  project-owned paths.

## Completion

Every canonical P0-P7 requirement and human/agent journey has direct current evidence in
`.agent/runs/prd-journey-audit.md`; no approval-required action remains implicit.
