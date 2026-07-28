# Unify adaptive signed execution, enhanced-index optimization, and public API

Status: completed

## Purpose

Make qlibx expose one StrategyAgent-to-Qlib runner that supports both long-only physical weights and
adaptive signed active weights, restore the enhanced-index batch path with a package-owned CVXPY
optimizer, and reduce the root package API from 107 flat names to a small responsibility-based
surface.

## Scope and non-goals

- Change production code under `src/qlibx/`, corresponding tests, package metadata/lockfile,
  README/public documentation, and one implementation record.
- Use `docs/qlibx-prd.md` as the only authoritative product contract.
- Treat `references/qlib-integration-codex/` as read-only behavioral evidence only.
- Keep Qlib as required `pyqlib==0.9.7`; do not modify Qlib or site-packages.
- Do not modify upstream or registered user data and do not add correction-factor behavior.
- Do not stage, commit, push, publish, or release.

## Acceptance criteria

- `run_strategy_execution` accepts a declared signed execution mode and invokes the StrategyAgent
  inside each Qlib decision step rather than precomputing a signed matrix.
- Signed StrategyAgent decisions see only prior Qlib-confirmed active-account feedback and actual
  realized signed holdings; negative intent produces actual Qlib SELL orders.
- Partial fills and blocked covers advance only from Qlib dealt quantity; combined Strategy/Qlib
  checkpoint-resume matches uninterrupted signed execution.
- Stored signed alpha continues to run through `run_signed_execution` using the same matched-
  capitalization implementation.
- The enhanced-index batch policy imports no missing vendor module and uses a package-owned CVXPY
  optimizer with explicit optimal/infeasible/solver-error results and post-solve validation.
- `construct_enhanced_index` and the vendor batch policy share the same optimizer contract instead
  of maintaining unrelated solvers.
- CVXPY is an explicit bounded production dependency; lockfile changes contain no unrelated
  upgrades and Python 3.10-3.12 resolution remains valid.
- Root `qlibx.__all__` contains at most 15 stable responsibility namespaces/core objects, with
  public examples/tests importing detailed contracts from their owning submodules.
- Narrow tests, full `uv run pytest`, Ruff check/format check, locked dependency check, and build
  pass in the managed Windows environment using scoped ASCII cache/temp paths where needed.

## Repository context

- `src/qlibx/execution.py::run_strategy_execution` currently rejects negative weights and cannot
  combine StrategyAgent state with matched capitalization.
- `src/qlibx/execution.py::run_signed_execution` accepts only a precomputed signed matrix.
- `src/qlibx/_vendor/qlib_backend/backend.py` explicitly forbids target policies together with
  matched capitalization.
- `src/qlibx/_vendor/qlib_engine/enhanced.py` imports the missing
  `qlibx._vendor.qlib_backend.constraint_optimization` module.
- `src/qlibx/portfolio.py` has a separate projected-gradient implementation with a different
  optimizer contract.
- `src/qlibx/__init__.py` exports 107 flat names.
- CVXPY is transitively installed by pyqlib but is not a declared direct dependency. The current
  lock contains CVXPY 1.7.5 for Python 3.10 and 1.9.2 for Python 3.11-3.12.

## Milestones

- [x] M1: Establish PRD contract, baseline architecture, dependency state, and failure evidence.
- [x] M2: Implement adaptive signed StrategyAgent execution and checkpoint/feedback tests.
- [x] M3: Introduce the package-owned CVXPY optimizer and route both portfolio paths through it.
- [x] M4: Replace flat root exports with responsibility namespaces and update public consumers.
- [x] M5: Update dependency metadata, documentation, implementation record, and validate completion.

## Progress

- 2026-07-28: Read the canonical PRD sections for StrategyAgent, signed alpha, enhanced index,
  matched capitalization, extension boundaries, and acceptance criteria.
- 2026-07-28: Confirmed root public API count is 107.
- 2026-07-28: Confirmed the vendor enhanced policy fails through a missing optimizer import while
  the public portfolio uses an unrelated projected solver.
- 2026-07-28: Baseline test attempt produced 43 passes and 34 setup errors solely because pytest's
  default non-ASCII profile temp root was access-denied; no baseline assertion failed.
- 2026-07-28: Added adaptive signed target-policy support at the backend decision boundary and an
  explicit `SignedExecutionConfig` mode on `run_strategy_execution`.
- 2026-07-28: Verified that a partial SELL fill leaves actual signed quantity -5 in the next
  decision context, active NAV 1,040 changes the later decision, and signed resume matches an
  uninterrupted run.
- 2026-07-28: Added `qlibx.optimization` with CVXPY objective, named hard/soft constraints,
  solver-independent post-solve validation, explicit infeasible/solver-error results, and metadata.
- 2026-07-28: Replaced the public portfolio projected solver and the vendor's missing import with
  that shared optimizer. Corrected solver-near-integer lot rounding without changing genuine
  fractional lot floors.
- 2026-07-28: Reduced the root API from 107 names to 13 core objects/responsibility modules and
  migrated repository tests, examples, showcases, generated agent guidance, and README imports.
- 2026-07-28: Declared `cvxpy>=1.7,<2` directly. The existing lock resolution remains CVXPY 1.7.5
  on Python 3.10 and 1.9.2 on Python 3.11-3.12; `pyqlib==0.9.7` remains required.

## Discoveries

- The backend currently treats `target_policy` as long-only physical intent and forbids combining it
  with matched capitalization, so signed adaptivity must be added at the backend decision boundary.
- For signed feedback, the next decision must receive active NAV/cash and reconstructed signed
  holdings, not composite Qlib account values that include baseline endowment.
- CVXPY is already a pyqlib transitive dependency but direct production use requires qlibx to
  declare its own bounded dependency.
- Managed Windows requires an explicit workspace `--basetemp` for pytest and a task-scoped ASCII
  `UV_CACHE_DIR` for uv operations.
- Transaction cost now affects the enhanced-index optimization objective, matching the reference
  economic behavior; it is no longer merely reported after selecting a target.

## Decision log

- Keep one public `run_strategy_execution` entry point and add an explicit signed execution policy;
  do not create a second adaptive runner.
- Preserve `run_signed_execution` as the stored-alpha convenience path, but share the same backend
  and result-building logic.
- Create a package-owned optimizer module and have both the portfolio facade and vendored batch
  adapter import it. Do not copy a module into the vendor namespace.
- Reduce root exports to modules plus `Project`, `QlibxError`, and version. Detailed types/functions
  remain public from their responsibility modules.

## Validation

- Baseline: root `__all__` = 107.
- Baseline: `.venv/Scripts/pytest.exe -q` -> 43 passed, 34 setup errors caused by
  `PermissionError` at the default pytest temp root; final validation used an isolated temp root.
- Focused signed execution: `.venv/Scripts/pytest.exe -q -p no:cacheprovider --basetemp
  .agent/tmp/pytest-signed tests/test_strategy_qlib_integration.py
  tests/test_signed_execution_journey.py` -> 10 passed.
- Focused optimizer/portfolio tests without tmp fixtures -> 9 passed, including package-owned
  vendor import, named constraint, infeasibility, solver failure, opaque ETF, and look-through.
- Public-surface and cross-responsibility focused tests -> 29 passed.
- Final `uv run --locked pytest` -> 83 passed.
- `uv run --locked ruff check .` and `uv run --locked ruff format --check .` -> passed; 96 files
  formatted.
- `uv lock --check` -> passed with 218 resolved packages.
- `uv build` -> built the 0.1.0 sdist and wheel. Wheel inspection found 58 files, no `references/`
  content, and metadata requiring `pyqlib==0.9.7` and `cvxpy>=1.7,<2`.

## Risks and recovery

- Root API cleanup is intentionally breaking at version 0.1.0. Update every repository-owned
  consumer and installed documentation in the same change.
- Adaptive signed feedback touches backend ordering. Preserve stored-alpha tests and add resume,
  partial-fill, blocked-cover, and active-account assertions before broader refactoring.
- Solver numerical output can vary slightly by CVXPY version. Validate economic constraints with a
  solver-independent post-solve validator and use tolerances only for numerical residue.
- All source changes are local and uncommitted; recovery is file-level patch reversal, never Git
  reset or reference modification.

## Next action

Complete. No approval-required action remains and all task-created temporary directories were
removed.
