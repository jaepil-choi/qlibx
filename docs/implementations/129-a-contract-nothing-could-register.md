# 129 — a contract nothing could register

## Why this exists

`vqapr/authoring.py` defined a complete DataModel contract — `Output`, `DerivedRow`, `DataCall`,
`DataModel` — and **no component written against it could be registered.**

`extension/loading.load_data_model` requires `models.data_model.DataModel`, and
`issubclass(authoring.DataModel, that)` is `False`. A user following the authoring surface for a
DataModel got `component.load.wrong_type` at registration, with no path to a run.
`docs/refactoring/2026-08-31-post-step-07-review.md` R5 measured it and ran the check:

```
issubclass(va.Constraint, EngineConstraint), issubclass(va.DataModel, EngineDataModel)
# False False
```

Only `load_strategy_model` had an adapter. `_adapt_authored_strategy`'s docstring explains why one
exists — *"Refusing the authoring one here would mean a model that runs perfectly through
`Project.simulate` cannot be registered by the CLI that exists to register it"* — and the same
argument was never applied to the other two doors. (`Project.simulate` was itself deleted in record
`124`, so even that justification now needs rewriting.)

So this was a contract, an invocation boundary under `_internal`, and their tests, reachable only
from the tests written for them.

## What changed

Deleted, with nothing put in their place:

| | |
|---|---|
| `authoring.Output` · `DerivedRow` · `DataCall` · `DataModel` | the contract |
| `_internal/models/agent_first`'s `_PrivateDataCall` · `PreparedDataInvocation` · `_validated_rows` · `prepare_data_model_invocation` | the invocation boundary that served it |
| 19 test definitions across `tests/models/test_agent_first_{authoring,invocation}.py` | their coverage |

144 lines out of `src/`, and the two files that held them keep their StrategyModel halves, which
are live.

**The surviving contract is `vqapr.models.data_model.DataModel`**, exported as
`vqapr.public.DataModel`. It is the one every DataModel in this tree and in the research workspace
already implements, so nothing that ever ran had to move.

## Why it is a deletion and not a re-export

Record `126` merged the two lookback pairs by having `authoring` re-export the engine's class. The
same move is not available here: `models/` imports `authoring` — `models/calls.py` needs
`DatasetInput` and `Observation`, `models/strategy_model.py` needs `Hold` and `Rebalance` — so
`authoring` importing `models.data_model` would close a cycle.

Giving both roles **one import path** therefore means moving the shared value types down to a leaf
first, and leaving `authoring.py` as a re-export surface rather than a definition site. That is the
next step and it is a restructuring, not a rename. Deleting an unreachable contract does not depend
on it, so it is not bundled with it.

## The characterization suite fired, and three of its assertions retired

`tests/extension/test_one_authoring_surface.py` (adopted from `qlibx-wt-038-049-9e` in record
`128`) states today's divergence and says in its own docstring:

> A test here that starts failing is not a regression — it is the milestone landing, and the test
> goes with it. Do not "fix" one of these by making the assertion true again; that would be
> re-opening 036.

Three failed and three were retired rather than repaired:

- `test_the_facade_and_the_authoring_module_are_two_objects[DataModel]` — there is no second
  object.
- `test_the_two_authored_kinds_share_no_base` — it cannot be asked when one of the two kinds is
  gone from that module.
- `test_load_data_model_refuses_an_authored_data_model` — an authored DataModel can no longer be
  constructed, so the refusal it pinned has no subject.

`DIVERGENT_NAMES` is down to `StrategyModel` and `Constraint` from an original five.

## Validation

- `uv run pytest tests/ -q` — 1274 passed, 0 failed.
- `uv run ruff check src/` — clean.

## What is left, and why the two remaining names are not the same case

`Constraint` is the DataModel case again: `authoring.Constraint` and `ConstraintCall` have no
execution path either, because `load_constraint` refuses them exactly as `load_data_model` did.
`test_load_constraint_refuses_an_authored_constraint` still passes, and closing it is the same
deletion.

**`StrategyModel` is not.** Two contracts exist and *both run* — `authoring.StrategyModel` through
`_adapt_authored_strategy`, and `models.strategy_model.StrategyModel` directly. All 33 strategy
files in the research workspace use the first; the showcases use the second. Closing that one is a
merge with a migration behind it, not a deletion, and it is what deletes
`_internal/strategy_bridge.py` and the rest of `agent_first`.
