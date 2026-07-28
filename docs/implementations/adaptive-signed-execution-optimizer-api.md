# Adaptive signed execution, shared optimizer, and compact API

## Why

The StrategyAgent Qlib runner accepted only non-negative physical weights, while signed execution
required a complete weight matrix prepared before the run. That prevented an adaptive long/short
strategy from reacting to Qlib-confirmed fills and active-account state. Separately, the vendored
enhanced-index adapter imported an optimizer module that did not exist in the package, the public
portfolio path used a different algorithm, and the root package flattened 107 names into one
namespace.

## Outcome

- `run_strategy_execution` now selects either its existing long-only mode or an explicit
  `SignedExecutionConfig`. In signed mode the same StrategyAgent callback runs inside every Qlib
  decision step and may return negative active weights.
- `run_signed_execution` remains the convenience API for executing a stored signed-weight matrix;
  both paths use the same matched-capitalization backend and signed result construction.
- `qlibx.optimization` owns the CVXPY intent-tracking optimizer used by both
  `construct_enhanced_index` and the private Qlib enhanced-index batch adapter.
- The root API now contains 13 names: `Project`, `QlibxError`, and 11 responsibility modules.
  Detailed contracts are imported from their owner modules.
- CVXPY is a bounded direct dependency (`>=1.7,<2`) instead of an undeclared transitive dependency
  of Qlib. Qlib remains mandatory at `pyqlib==0.9.7`.

## Execution flow and authority

At decision step *t*, the backend reconstructs realized active quantity as long inventory minus
baseline inventory. The StrategyAgent receives that signed holding, active cash and NAV, and only
feedback recorded before *t*. Its signed target is validated for exact axes, finite values, and at
most 100% exposure on each side. The target is translated into the matched-capitalization composite
account, but only Qlib dealt quantities update the next state. Therefore a partial short sale, a
blocked cover, or a changed active NAV affects the next decision rather than being treated as if the
requested target had filled.

The combined checkpoint stores StrategyAgent memory and the Qlib backend checkpoint. Resuming from
it reproduces decisions, orders, fills, signed positions, active account rows, and reconciliation.

## Optimizer contract

The optimizer minimizes look-through tracking error plus declared turnover, transaction-cost, and
optional risk terms. It supports bounds, frozen holdings, named hard constraints, and penalized soft
constraints. Results distinguish `optimal`, `infeasible`, and `solver_error`, include solver
metadata, and are rechecked by a solver-independent validator. Post-solve lot rounding is followed
by the same hard-constraint validation; near-integer numerical residue is snapped before flooring.

## Trade-offs

Matched capitalization remains a compatibility representation over Qlib's long-only account. It
does not model native borrow, margin, recall, forced buy-in, or borrow fees. Signed side exposure is
bounded independently at 100%; leverage beyond that requires a future explicit contract.

The root API reduction is intentionally breaking at version 0.1.0. No dynamic compatibility aliases
were retained because they would preserve the broad namespace the change is meant to eliminate.
Detailed modules remain public and are covered by repository examples and tests.

## Validation

- Adaptive signed focused tests: 10 passed, including actual Qlib SELL and partial-fill feedback,
  active-NAV adaptation, and checkpoint/resume parity.
- Optimizer focused tests: 9 passed, including the private enhanced-index batch path, named
  constraints, explicit infeasibility and solver failure, look-through, and opaque ETF behavior.
- Public-surface and cross-responsibility focused tests: 29 passed.
- `qlibx.__all__` contains exactly 13 names and does not expose `run_signed_execution` at root.
- Locked dependency, full test, Ruff, formatting, and build results are recorded after completion
  validation below.

### Completion validation

- `uv run --locked pytest -q -p no:cacheprovider --basetemp <scoped C:\\tmp path>`:
  83 passed.
- `uv run --locked ruff check .`: passed.
- `uv run --locked ruff format --check .`: 96 files already formatted.
- `uv lock --check`: resolved 218 packages with no lock error.
- `uv build`: built `dist/qlibx-0.1.0.tar.gz` and
  `dist/qlibx-0.1.0-py3-none-any.whl`.
- Wheel inspection: 58 packaged files, no `references/` content, with metadata declaring
  `pyqlib==0.9.7` and `cvxpy>=1.7,<2`.

Pytest emitted existing Qlib/NumPy timedelta deprecation warnings and one pandas concatenation
future warning; there were no test failures. Managed Windows denied pytest's default and workspace
temporary roots, so validation used isolated paths under `C:\\tmp`. All task-created pytest and uv
temporary directories were removed afterward.
