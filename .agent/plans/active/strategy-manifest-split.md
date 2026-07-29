# Split `strategy_manifest` into a package with one responsibility per file

Status: complete

## Purpose

`src/qlibx/strategy_manifest.py` is 1061 lines holding five unrelated responsibilities
behind one name. The next queued task — generalizing the capability protocol, which
`profiles`, `alpha.exposure` and this module currently hand-write four times — has to edit
the declare/evidence/evaluate/plan cycle. Doing that inside a 1061-line file means finding
it first. Splitting first creates `strategy_manifest/capability.py` as an explicit target,
so the protocol work is an edit to a named file rather than a search.

## Scope and non-goals

In scope: moving existing code into a package, and the minimum renames required to avoid
private cross-module imports.

Non-goals:

- No behavior change. Every raise, message, code and context stays byte-identical.
- No rename of `strategy_manifest` itself, and no rename of `strategy`. Review §16 records
  that naming cleanup; doing it here would mix a rename into a move and make the diff
  unreadable.
- No capability-protocol generalization. That is the next task; this one only prepares it.

## Acceptance criteria

- `from qlibx.strategy_manifest import X` keeps working for every name in the current
  `__all__` (18 names). `tests/test_architecture.py::test_public_module_paths_stay_importable`
  covers this and must stay green without modification.
- `uv run pytest` shows the same result as the baseline: 128 passed, plus the one
  pre-existing `cp949` acceptance failure.
- `uv run ruff check .` and `uv run ruff format --check .` clean.
- No file in the new package exceeds ~350 lines.
- No module imports a `_private` name from a sibling module.

## Repository context

Current single module, with the clusters that become files:

| Lines | Cluster | Destination |
|---|---|---|
| 30-135, 986-1038 | dataclasses, `base_universe_input`, declaration, dict views | `contracts.py` |
| 138-259, 508-577, 943-983 | YAML to contracts | `loading.py` |
| 262-299, 614-730, 1027-1038 | evidence, plan, inventory, effective config id | `capability.py` |
| 302-353, 733-940 | binding to bounded pandas | `resolution.py` |
| 356-505, 910-930 | callable loading, invocation, execution adapter | `invocation.py` |

Consumers that must not change: `src/qlibx/cli.py:52` and `:193`,
`tests/test_strategy_manifest.py:11`, `src/qlibx/__init__.py:33`.

`tests/test_architecture.py` `LAYERS` places `strategy_manifest` in layer 5 and its
`_top_level()` already maps a package directory to its directory name — the comment at
line 172 of `tests/test_documentation.py` notes the same. Both should keep working with no
edit, which is itself a check that the layering tests were written honestly.

Convention to follow, from the `alpha` package: `__init__.py` carries a `Layout::` docstring
and re-exports the whole surface; intra-package imports are relative (`from .contracts
import X`), cross-package imports absolute (`from qlibx.catalog import X`).

## Milestones

- [x] M1: Create the package with `contracts.py` and `loading.py`; delete nothing yet.
- [x] M2: Add `capability.py` and `resolution.py`.
- [x] M3: Add `invocation.py` and `__init__.py`; delete the old module.
- [x] M4: Full validation, implementation record.

## Progress

Complete. 1061 lines became six files; the largest is `loading.py` at 251.

| File | Lines |
|---|---|
| `__init__.py` | 56 |
| `capability.py` | 186 |
| `contracts.py` | 185 |
| `invocation.py` | 184 |
| `loading.py` | 251 |
| `resolution.py` | 240 |

No file imports a `_private` name from a sibling. The 19-name public surface resolves
identically and `__all__` is unchanged.

## Discoveries

- `StrategyManifest.requirements()` is public: `cli.py:193` calls it. It cannot move off the
  dataclass without changing the CLI.
- That method calls `_input_requirement`, which would create a `contracts` to `capability`
  cycle if the declaration lived in `capability.py`.
- `_input_dict` has two callers that would land in different files: `requirements()`
  (line 93) and `_manifest_dict` (line 1006).

## Decision log

- **Declaration lives with the contracts, not with the capability.** `_input_requirement`
  and `requirements()` depend only on `qlibx.requirements` (layer 0), never on the project
  or catalog. Putting them in `contracts.py` breaks the cycle with no deferred import, and
  is the better boundary anyway: "the capability declares what it needs" is intrinsic to the
  manifest, while "what the project can currently supply" is evidence. When the protocol is
  generalized, `requirements()` is the concrete implementation of its `declare` step.
- **`_manifest_dict`/`_binding_dict`/`_input_dict` become `manifest_document`/
  `binding_document`/`input_document` in `contracts.py.`** They are read by two files after
  the split, and the previous review already flagged private-looking names crossing module
  boundaries. They are also genuinely public in effect: they are the JSON an agent reads out
  of a capability plan. This is the only rename in the change.

## Validation

Baseline before the split, recorded so a regression is attributable: `128 passed, 1 failed`
(`tests/acceptance/test_p0_p1_agent_journey.py`, pre-existing Windows `cp949` console-codec
error, confirmed on a stashed working tree at commit `41f0928`).

After the split: `128 passed, 1 failed` — the same pre-existing acceptance failure, no
other change. `uv run ruff check .` and `uv run ruff format --check .` clean.

`tests/test_architecture.py` passed with no edit, which is the load-bearing result: its
`_top_level()` maps the new package directory to `strategy_manifest`, so the layer
assignment, the acyclicity check and `test_public_module_paths_stay_importable` all still
apply to it. Had those tests been written against module *files*, the split would have made
them silently vacuous instead of green.

## Risks and recovery

- **Silent behavior change during a move.** Mitigation: move verbatim, and treat any test
  diff as a defect in the move rather than something to fix in the test.
- **Import cycle discovered late.** Mitigation: file order M1 to M3 follows the dependency
  direction, so each milestone imports only from files that already exist.
- Recovery: the split is one commit on `exp/one-shot` after `f029253`; `git revert` restores
  the single module.

## Next action

None for this plan. The follow-up it exists to enable is the capability-protocol
generalization: `strategy_manifest/capability.py`, `profiles.py` and `alpha/exposure.py`
each hand-write declare/evidence/evaluate/plan, and `capability.py` is now a 186-line file
holding exactly that cycle for one capability. Move this plan to
`.agent/plans/completed/` when that work starts.
