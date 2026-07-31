# Splitting `strategy_manifest` into a package

## Why this change exists

`strategy_manifest.py` was 1061 lines holding five unrelated responsibilities behind one
name: what a manifest declares, how its YAML parses, whether a project can satisfy it, what
data a bound Strategy may read, and what happens when it runs.

The immediate motive is the next task rather than the file size. Generalizing the capability
protocol — `profiles`, `alpha.exposure` and this module each hand-write
declare/evidence/evaluate/plan — means editing that cycle. Doing it inside 1061 lines means
finding it first. `strategy_manifest/capability.py` is now a 186-line file holding exactly
that cycle, so the follow-up is an edit to a named file rather than a search.

## What outcome it serves

No user-visible outcome. This is preparatory structure, and it is deliberately behavior-free
so that the capability work that follows has an unambiguous diff.

## Structural changes (no behavior change)

| File | Lines | Responsibility |
|---|---|---|
| `contracts.py` | 185 | value objects, and the requirements a manifest declares |
| `loading.py` | 251 | manifest and binding YAML to contracts |
| `capability.py` | 186 | evidence against a project, and the read-only plan |
| `resolution.py` | 240 | approved binding to bounded pandas inputs |
| `invocation.py` | 184 | trusted callable loading, invocation, Qlib execution adapter |
| `__init__.py` | 56 | re-export of the unchanged 19-name public surface |

Code moved verbatim. Every raise, code, message, action and context is byte-identical, which
is what makes the unchanged test suite meaningful evidence rather than a coincidence.

## Decisions

**Declaration lives with the contracts, not with the capability.** `StrategyManifest.
requirements()` is public — `cli.py:193` calls it — so it cannot move off the dataclass. It
calls `_input_requirement`, which would have made `contracts` import `capability` and closed
a cycle. The resolution is not a deferred import: `_input_requirement` depends only on
`qlibx.requirements` (layer 0), never on the project or catalog, so it belongs in
`contracts.py` outright. That is also the better boundary. "What this capability needs" is
intrinsic to the manifest; "what the project can currently supply" is evidence about the
world. When the protocol is generalized, `requirements()` is the concrete implementation of
its `declare` step, and `capability.py` holds the other three.

**One rename.** `_manifest_dict`, `_binding_dict` and `_input_dict` become
`manifest_document`, `binding_document` and `input_document` in `contracts.py`.
`input_document` has two callers that landed in different files (`requirements()` and
`manifest_document`), so leaving them private would have meant importing a `_private` name
across a module boundary — which the previous review already flagged as a smell in this
package. They are public in effect anyway: they are the JSON an agent reads out of a plan.

## Trade-offs

- `resolution` imports `capability` for `require_strategy_binding`, so the dependency inside
  the package is not a flat fan-out. That is real: you cannot resolve inputs you have not
  established are satisfiable, and hiding that by duplicating the check would be worse.
- `invocation` keeps its two function-level imports of `qlibx.strategy` and
  `qlibx.execution`. Those exist to keep `import qlibx` from loading the Qlib runtime
  (`test_architecture.py::test_importing_the_facade_does_not_load_the_execution_runtime`),
  and the split does not change that constraint.
- `loading.py` at 251 lines is the largest file and is still mostly one long function.
  Decomposing `load_strategy_manifest` further is defensible but is a behavior-adjacent edit
  to validation order, so it was left out rather than started and abandoned.

## Validation

- `uv run ruff check .` and `uv run ruff format --check .` — clean.
- `uv run pytest` — `128 passed, 1 failed`, identical to the pre-split baseline. The failure
  is the pre-existing Windows `cp949` console-codec error in
  `tests/acceptance/test_p0_p1_agent_journey.py`, confirmed on a stashed tree at `41f0928`
  and unrelated to this change.
- Public surface checked directly: `strategy_manifest.__all__` is the same 19 names in the
  same order, and every one resolves.
- No test was edited. That is the point of the change and the strongest available evidence:
  `tests/test_architecture.py` maps a package directory to its directory name, so the layer
  assignment, acyclicity, vendor-gateway and importability checks all still bind on
  `strategy_manifest` after it stopped being a single file. Tests written against module
  files would have gone silently vacuous here instead of staying green.

## Follow-up this enables

`capability.py` now isolates one hand-written declare/evidence/evaluate/plan cycle.
`profiles.py` and `alpha/exposure.py` hold two more. Generalizing the protocol across the
three is the next queued task; see `.agent/plans/active/strategy-manifest-split.md`.
