# 192 — `authoring` is a package, and the door it presents is unchanged

**Date:** 2026-09-08. **Branch:** `develop` (layering campaign M3;
`docs/refactoring/2026-09-08-the-layering-campaign.md`, ExecPlan
`.agent/plans/active/layering-campaign.md`). **Reported by:** the campaign's diagnosis —
`authoring.py` was 1,235 lines at the top level of the package, and the last of the three
value-driven cycles ran through it.

## Why

Two problems, one move.

**The cycle.** `authoring.py` imported `account/history.py` for the field names and the projection
type; `account/history.py` imported `AccountHistoryInput` back, under `TYPE_CHECKING`, with a
comment that named the cycle instead of resolving it:

> The declaration is `authoring`'s, and `authoring` imports this module for the field names and the
> projection type, so the type lives here as an annotation only.

The rule record `191` applied — a value two packages exchange lives in `domain/` — does not fit
this one. `AccountHistoryInput` is what a StrategyModel *declares* and `AccountHistory` is what it
is then *handed*; neither is meaningful without the other, and `domain/` would hold half a contract.
They are one thing in two packages, so the fix is one package.

**The size.** 1,235 lines is not itself a defect, but the file had already drawn its own seams:
three banner comments reading *"Shared validation helpers"*, *"StrategyModel algebra"* and
*"Constraint algebra"*. A reader looking for what a `Rebalance` refuses had 332 lines to find inside
1,235 that also declare four abstract contracts and eight validators.

## What

**Nine modules and a door, laid out so the door has no cycle behind it.**

| module | lines | holds |
|---|---|---|
| `__init__.py` | 78 | the door: the package argument, and the same 22 exports |
| `_validation.py` | 140 | four reserved-name sets, `_VALUE_CONFIG`, eight shared validators |
| `reads.py` | 62 | `DatasetInput`, `requirements_for` |
| `history.py` | 151 | `AccountHistory` + `AccountHistoryInput`, the two halves reunited |
| `view.py` | 166 | `EconomicAccountView`, `ConstraintBounds` |
| `result.py` | 500 | `Hold`, `Rebalance`, `ConstraintFinding` |
| `call.py` | 145 | `DataCall`, `StrategyCall`, `ConstraintCall` |
| `component.py` | 263 | `Component`, `DataModel`, `StrategyModel`, `Constraint` |
| `records.py` | 170 | was `authoring_records.py` |
| `context.py` | 251 | was `calls.py` |

Layered `_validation` -> {`reads`, `history`, `view`, `result`} -> `call` -> `component`, with
`records` independent and `context` above everything. Every line of code is the old line: the split
is by range, so no docstring was re-typed and none was lost.

`reads.py` exists so `component.py` and `data`-side declarations do not import each other:
`Component.requirements()` reads a `DatasetInput` while `DataModel` **is** a `Component`, and
keeping the declaration below the class that consumes it is what stops that pair from being a
cycle at file scale after being one at package scale.

**The door is byte-identical in what it offers.** `__all__` is the same 22 names in the same order.
This was not free — the first draft widened it by five (`ACCOUNT_FIELDS`, `INSTRUMENT_FIELDS`,
`InvocationRecorder`, `RecorderManifest`, `retained_marks`) on the reasoning that they were now
in-package, and `tests/models/test_agent_first_authoring.py::test_module_exports_are_exact` refused
it. That test is right: M3 is a move, and a move that quietly grows the published surface is not
one. Those names are reachable at `vqapr.authoring.history` and `vqapr.authoring.records`.

**One caller was leaning on incidental leakage.** `authoring.py` imported `Budget`,
`PortfolioDirection`, `QUANTUM` and `rescale` for its own use, which made them importable from
`vqapr.authoring` without being exported. An AST sweep of `src/`, `tests/` and `showcases/` found
exactly one place taking a name from that shadow surface: the strategy source
`tests/flow/strategy/test_valuation_clock.py` writes into a temporary directory imports `Budget`
and `PortfolioDirection` from `vqapr.authoring`. It now imports them from
`vqapr.portfolio.budgets`, where they are declared. No `src/` module and no showcase did this.

**The package invariant is restated, because the old one could not survive the split.**
`authoring.py` said *"pure algebra: it declares contracts only. No runtime adapter, store, catalog,
or Flow wiring lives here."* `context.py` — the old `calls.py` — is precisely a runtime adapter: it
binds a `ModelWindow` to a callback. Under the old wording it could not join the package it belongs
to. The wording was one file's, and what it was protecting is a direction, so the package says the
direction instead:

> **Everything a Component sees, and nothing above it.**

Nothing under `authoring/` may import `exchange/`, `extension/`, `project/`, `flow/` or the facade,
and `tests/boundaries/test_the_layers_hold.py` enforces that rather than a docstring promising it.

**`__init__.py` re-exports, which almost no other package here does.** The convention in this tree
is that `__init__.py` carries the package's argument and nothing else. Two packages are exceptions
for two different reasons, and the door says which: `record/` hides its module layout deliberately;
`authoring/` is a **published import path**, written into the shipped skills, the emitted scaffolds
and all nine showcases, so the nine modules below it are an implementation detail.

**`OPEN` loses `("account", "authoring")`**, and `authoring_records` and `calls` leave `LAYERS`
because the nodes are gone. `CEILING` does not move: the `TYPE_CHECKING` import that held this cycle
open sat at module scope, and that ratchet counts function-local imports only — which is worth
noting, since it means a `TYPE_CHECKING` cycle is invisible to it and visible only to the layer
table.

## Trade-offs

**Ten files where there was one.** The door is what makes this affordable: a reader who wants the
contract opens `vqapr.authoring` and sees 22 names and the argument for them; a reader who wants to
know what `Rebalance` refuses opens `result.py` and reads 500 lines instead of 1,235. The cost is
real for anyone who navigated by scrolling one file.

**`result.py` at 500 lines is the largest piece and stays whole.** `Hold`, `Rebalance` and
`ConstraintFinding` are one question — what a Component returns — and `Rebalance` is 332 of those
lines because naming one complete desired portfolio is the decision the framework exists to take.
Splitting by role instead would have put `ConstraintFinding` in a 50-line file of its own.

**`vqapr.calls` and `vqapr.authoring_records` are breaking.** Neither is in `vqapr.public`'s
import path for users — `public` re-exports `DataModelContext`, `StrategyModelContext` and
`TableSpec` unchanged — and no showcase imported either.

## Validation

- `uv run ruff check src/` — clean. Fixing it took two passes: `ruff --fix` was scoped to `src/`
  only this time, after record `191` had to revert 19 unrelated test files it reformatted.
- `uv run pyright` — `0 errors, 0 warnings, 0 informations`.
- `uv run pytest tests/characterization/test_refusal_codes.py -q` — 10 passed, **0 codes lost**
  across a ten-way split of the file that raises the authoring refusals.
- `uv run pytest tests/boundaries/ -q` — 37 passed, after `OPEN` was tightened. Before tightening
  it failed as designed: *"these OPEN entries no longer violate anything: [('account',
  'authoring')]"*.
- `uv run pytest tests/ -q` — 1578 passed, 2 failed: the two pre-existing
  `tests/agent/test_the_release_records_what_it_ships.py` failures from record `190`, unchanged.
  An intermediate run had 3 failed and 4 errors — the widened `__all__` and the fixture leaning on
  the shadow surface, both described above and both fixed rather than accommodated.
- `uv run pytest tests/ -q -m ""` — 1603 passed, 2 failed in 308 s: identical to the pre-campaign
  baseline. The slow set adds no failure.
- The nine shipped skills under `src/vqapr/agent/skills/` name no retired module path: they are
  written against `vqapr.public` and `vqapr.authoring`, both unchanged.
