# Rebuild qlibx around YAML-configured data

Status: completed

## Purpose

Rebuild qlibx from the clean repository skeleton so the primary data journey is YAML-configured:
explicit generic registration creates canonical Parquet, and a config-driven loader resolves
logical tables/matrices from YAML.

## Scope and non-goals

- In scope: package metadata, project model, strict YAML config, generic registration,
  config-driven loader, agent-readable requirements/errors, CLI, tests, current project YAML,
  real canonical data, and a bounded Qlib integration proof.
- Non-goal: modify upstream user data or anything under `references/`.
- Constraint: qlib is mandatory; current branch only; no stage/commit/push.

## Acceptance criteria

- `config/` contains only user-authored YAML/CSV, never generated snapshot JSON or Markdown.
- YAML registration specs know only `available_at`, `ticker`, and opaque information mappings.
- Registration reads upstream files without modifying them and writes processed Parquet under
  `data/qlibx/`; generated provenance goes under `.qlibx/`.
- `ConfigDrivenDataLoader` loads YAML-named logical tables and matrices through DuckDB.
- Current market, K200 membership, and sector data register with the user-confirmed availability
  offsets; selected values are unchanged.
- qlib is a mandatory wheel dependency.
- Focused and full tests, lint, format, build, and real-data smoke pass.

## Repository context

- Clean baseline restored on branch `exp/one-shot`.
- Preserved upstream hashes:
  - adjusted prices: `63a4321aaecb...e284c8`
  - K200 members: `c31e8cfaad30...9e424`
  - sector classification: `e7f9322b3d54...59409`
- Comparative YAML pattern comes from `references/configs/` and the reference
  `ConfigDrivenDataLoader`.
- Canonical requirements come from `docs/qlibx-prd.md` sections 6.1-6.4 and P1.

## Milestones

- [x] M1: Build package foundation, strict YAML catalog, and loader with contract tests.
- [x] M2: Build generic YAML registration and agent-facing requirement/error flow.
- [x] M3: Author current project YAML, register real data, and verify lossless values/availability.
- [x] M4: Run bounded Qlib integration proof and complete foundation validation/documentation.
- [x] M5: Implement and prove the remaining canonical PRD public research/execution surfaces.

## Progress

- 2026-07-27: Removed the previous implementation, config, generated data, state, tests, and
  experiment; restored tracked skeleton to HEAD.
- 2026-07-27: Verified protected upstream/reference/PRD boundaries and source hashes.
- 2026-07-27: Implemented strict YAML config, physical/logical catalog, parameterized DuckDB
  loader, generic registration, CLI, and generated agent skill.
- 2026-07-27: Registered all three real datasets and verified exact selected values plus every-row
  availability offsets. Loader returned a real 7x2 matrix with 14 valid observations.
- 2026-07-27: Fresh 2025-Q1 signed long-short run passed through Qlib 0.9.7 using only YAML-loaded
  qlibx matrices: 59 dates, 201 tickers, 552 held short rows, zero composite shortfall, and
  This earlier availability-indexed PnL claim was invalidated and its experiment was removed.
  Current event-time evidence is recorded only in `exp_003_event_time_qlib_pnl`.
- 2026-07-27: Moved the proven runner/backend into the qlibx wheel; isolated-wheel execution
  reproduced the same PnL without importing `references/`.
- 2026-07-27: Added bounded strategy, alpha built-ins, immutable research publication,
  orthogonality, ensemble, enhanced-index feasibility, local extension, public help/schema, and
  stored-artifact reporting contracts.

## Discoveries

- The reference config contract cleanly separates physical sources from logical SQL datasets.
- Generated registration state must not share the user config root.
- The reference matched-capitalization backend needs a separately sized inventory-transition
  reserve for long horizons; the bounded proof deliberately does not claim a full-year policy.

## Decision log

- Use stable canonical files `data/qlibx/<dataset>.parquet` selected by YAML sources.
- Keep registration specs in YAML and provenance in `.qlibx/registrations`.
- qlibx registration has no financial field vocabulary.

## Validation

- Contract/integration suite: 26 passed.
- Dependency tree and lock check passed; qlib is mandatory at pyqlib 0.9.7.
- Wheel and sdist built; wheel metadata and packaged modules inspected.
- Qlib proof: `experiments/exp_003_event_time_qlib_pnl`, PASS.
- Isolated installed-wheel import, PnL, and stored-artifact report: PASS.

## Risks and recovery

- Stable derived files are replaceable generated outputs; writes must be staged and atomic.
- Large real sources require projected reads and bounded loader smoke.

## Next action

Completed. Protected-source hashes and final Git boundary are recorded at handoff.
