# 167 - Explicit runtime ownership and readable execution boundaries

Status: in progress. User authorized implementation after the 2026-09-07 call-flow review.

## Why and outcome
Construction could leave a writer claimed and session unclosed; empty contexts, unused phase back-references and higher-order boundaries obscured the runtime spine. Preserve economic state transitions and failure evidence while making ownership and direct calls explicit.

## Changes and trade-offs
M1 and M2 landed: orchestration owns the session and the writer inside cleanup boundaries and
releases only what it acquired; FlowContext and SimulationFlow take their dependencies through the
constructor instead of post-assignment; the ValuationPhase callback back-reference and
Workspace._commit are gone. M3 (lexical error and timing boundaries), M4 (preparation and sample
alignment) and M5 (full validation) remain; see .agent/plans/active/v060-runtime-refactor.md.

## Validation
Partial, at the 2026-09-07 checkpoint commit: `pytest tests/flow -q` 181 passed, 5 deselected;
`ruff check src/` clean. The full manifest `test_all`, the Vulture triage and the before/after
economic tables belong to M5 and have not run yet.