# 019 Explicit ambiguous requirement resolution

## Why

Requirement resolution silently selected the alphabetically first dataset whenever more than one
registration exposed the same semantic role and the requirement omitted `dataset_id`. This made a
new benchmark registration capable of changing constraint adjustment, validation, or monitoring
without a config change. It violated the PRD requirements to avoid guessed economic meaning and to
prefer explicit failure over silent fallback.

## Outcome

`RequirementResolver` now returns `REQUIREMENT_AMBIGUOUS` when multiple compatible registrations
remain. The error reports a bounded, deterministic list of candidate dataset IDs and registration
identities. `ConstraintDeclaration` can pin `benchmark_dataset_id`, and both constraint calculation
and independent monitoring pass that identity into their declared requirement.

## Responsibility and flow

The resolver owns ambiguity detection but does not choose a candidate or prescribe an economic
meaning. A caller that knows the intended dataset supplies `dataset_id`; otherwise the package
returns machine-readable evidence for the agent and user to resolve. Constraint configuration owns
the benchmark selection because adjustment, validation, and monitoring must share one economic
declaration.

## Alternatives and trade-offs

Retaining deterministic alphabetical selection was rejected because determinism does not make an
economically arbitrary choice correct. Adding the dataset field only to a monitoring request was
also rejected because it could let monitoring evaluate a different benchmark from pre-execution
constraint operations. The optional declaration field preserves existing one-candidate configs
while forcing an explicit choice only when the registry is ambiguous.

## Validation

- Focused resolver and real-DW constraint/monitoring suite:
  `uv run pytest tests/test_data_registration.py tests/acceptance/test_research_scenarios.py::test_uc_constraint_002_and_uc_constraint_adjust_001_use_confirmed_k200_cutoff tests/acceptance/test_research_scenarios.py::test_uc_exec_003_monitors_real_no_trade_price_drift_without_mutation -p no:cacheprovider --basetemp=<task path> -q`
  -> 8 passed.
- Full suite: `uv run pytest -p no:cacheprovider --basetemp=<task path> -q` -> 84 passed.
- Ruff on the six changed source/test files -> passed.
- `git diff --check` -> passed.

The Windows environment required a task-scoped ASCII `UV_CACHE_DIR` and an elevated,
repository-local pytest basetemp because the default user cache and sandbox-created temp
directories were not readable.

## Remaining limitations

The package reports at most the first 20 candidate identities in error context while preserving the
full candidate count. It intentionally does not rank candidates or infer which benchmark the user
meant.
