# Alpha operation and budget-policy registries

## Why this change exists

A code review against `docs/qlibx-prd.md` found that adding a signal operation or a
weight-scaling rule required editing branching dispatch code inside the package, which
PRD §4.6 and §12.2 forbid for project-local work. The review also confirmed three
correctness defects and one broken public example.

## What outcome it serves

- PRD §8.2: every built-in operation documents axis, tie, NaN, minimum-observation,
  group-missing and dtype semantics, and contributes its operation ID and version to
  result lineage.
- PRD §4.6: an agent can list the installed built-ins and their contracts from the
  installed public surface before writing a helper.
- PRD §8.4: fixed and flexible budgets are declared policies, and unused flexible budget
  is reported rather than silently rescaled.
- PRD §12.1/§12.2: a project-local operation or a validated `signal_transform` extension
  composes with built-ins through the same registry and lineage.

## How it works

`qlibx.alpha` owns two registries.

- `OperationRegistry` maps a name to an `OperationSpec` that carries both the declared
  semantics and the implementation. `apply_transform` and the new `apply_pipeline`
  dispatch through it, so there is no branching dispatch and exactly one edit site per
  operation. `OperationSpec.contract()` produces the `OperationContract` recorded in
  `TransformResult.lineage`; `resolve_minimum_observations` lets a parameterized window
  report the count actually required. Declared parameters are validated on every call, so
  a misspelled keyword fails explicitly instead of reaching pandas.
- `BudgetPolicyRegistry` maps a name to a `BudgetPolicySpec` whose `resolve` returns the
  per-side scales. `apply_budget` returns a `BudgetResult` with per-date used and leftover
  side budget; `rescale_budget` remains a thin frame-returning wrapper.

`qlibx.extensions.signal_transform_operation` adapts a validated extension into an
`OperationSpec`, recording its source digest in lineage. `qlibx alpha operations`,
`qlibx alpha operation <name>` and `qlibx alpha budgets` expose both registries, the
`alpha_operation` and `budget_policy` schemas describe them, and the generated agent skill
renders `references/alpha-operations.md` from the live registries so it stays
version-matched.

Operations that existed as unreachable public functions (`cross_sectional_zscore`,
`winsorize`, `top_bottom`) are now registered, and the PRD-named `clip`, `lag`,
`rolling_mean`, `rolling_std` and `per_name_cap` were added.

## Correctness fixes included

- `alpha.hump` propagated missingness for the remainder of a ticker's series after a
  single gap, because the limiter differenced against a missing previous value. A gap now
  restarts the limiter.
- `alpha.top_bottom` assigned one name to both sides when fewer than `2 * count` valid
  observations existed on a date, and the short assignment silently won. It now fails
  explicitly and names the offending dates.
- `ensemble.combine_signed_weights` computed leave-one-out marginal contribution with NaN
  propagation, so a cell where a member was missing dropped out of the norm entirely and
  every member was credited for exposure it did not supply.
- The documented `signed_execution` example passed a nonexistent `observed=` keyword,
  omitted the required `datasets=`, and read `reconciliation` off the wrong object.

## Trade-offs

- `top_bottom` now fails on thin dates rather than degrading. This follows the repository
  rule preferring explicit failure over silent fallback; a caller wanting partial
  selection chooses a `count` that fits the date's coverage.
- `OperationContract` gained defaulted `summary`, `selection_behavior`, `implementation`
  and `implementation_digest` fields. They are appended after `parameters`, so existing
  keyword construction and attribute access are unaffected.
- Beta estimation and residualization from PRD §8.2/§8.3 remain unimplemented. They
  require estimation-window and factor-source semantics the PRD does not fix, so inventing
  them here would have guessed a public contract.

## Shared serialization

`qlibx.serialization` now owns canonical JSON encoding, byte/text/file digests, and stored
name validation. `research`, `artifacts`, `registration`, `onboarding` and `skill`
previously carried byte-identical private copies; consolidating them keeps durable
identities comparable. The vendored `_vendor/qlib_engine/hashing.py` is deliberately left
alone so the vendored subtree stays self-contained.

`research.ResearchCatalog._lock` now acquires the file lock outside the release scope. On
Windows a lock-acquisition timeout previously ran `msvcrt.locking(..., LK_UNLCK)` on a
never-locked region, and the resulting `OSError` masked the original `TimeoutError`.

## Validation

- `uv run ruff check .` — clean.
- `uv run pytest` — 93 passed (83 before; 10 new tests cover the three correctness fixes,
  registry dispatch and parameter validation, pipeline lineage, project-local operation
  registration, budget-policy registration and leftover reporting, and the new CLI).
- `tests/test_documentation.py::test_documented_examples_bind_against_real_public_signatures`
  binds documented example call sites against real signatures; the previous test only
  compiled the example text, which is why the broken `signed_execution` example passed.
