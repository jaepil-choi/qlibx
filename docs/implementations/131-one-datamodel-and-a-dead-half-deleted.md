# 131 — one DataModel, and a dead half deleted

**Advances:** `docs/issues/036` (the DataModel third; `StrategyModel` remains).
**Step:** M1.2 of `docs/refactoring/2026-09-02-the-convergence-campaign.md`.
**Authority:** `docs/vqapr-architecture.md` §4.4 · `docs/design/agent-first-surface.md` Principle 5.

## Why this exists

`vqapr.public.DataModel` and `vqapr.authoring.DataModel` were two classes. An author who followed
the strategy scaffold's import line and subclassed `va.DataModel` wrote a model **nothing could
run**: `load_data_model` refused it, and the adapter that would have invoked it —
`prepare_data_model_invocation` in `_internal/models/agent_first.py` — had **no caller anywhere in
`src/`**. Only its own tests reached it. The datamodel scaffold sidestepped this by emitting the
engine class in the older declaration shape, so the package shipped two authoring idioms for one
job and taught both (`docs/issues/036`, R5 and R6 of the post-Step-07 review).

So, unlike M1.1, this was not a live-path rewrite. The authoring DataModel path was dead code
wearing a public name, and the engine path was the only one that had ever run. The work was to put
the engine's behaviour behind the author's name, and to delete the half that had never done
anything.

## What changed

### `Model` lives on the author's surface

The common base — `memory`, `inputs()`, `requirements()` — moved from `models/model.py` into
`vqapr.authoring`, and `models/model.py` re-exports it. It is the author's base class, so it lives
where the author looks. `DataModel(Model)` is now one class with one abstract member, `compute`,
exported under both names as the same object.

`Constraint` does **not** inherit it. `Model` carries `memory`, and a constraint is a stateless
predicate that must not have any. The two share the read fan-out — `requirements_for`, one
implementation in `authoring` — and nothing else.

### The output schema stays a declaration

The design sketch had put `output()` on the model. It is not added. The materialization spec
already declares `value_fields` in YAML and `materialize` validates every row against it; a model
that restated the schema would make one fact have two sources, which is the pattern M1.1 rejected
three times. Of the two, the YAML is right: what a materialization *produces* is a registered
dataset, and a dataset's shape is declared where datasets are declared — *YAML declares, Python
authors*. What the model does is compute. The sketch's line is corrected where it stands, with this
reasoning beside it.

**The cost, stated.** A model returning the wrong fields is caught at its first `compute`, not at
`check`. The testbed reported exactly that as B2. It is a gap in `check`, and moving the schema
onto the model would not have closed it; it stays open.

### A row is a dict

`{"instrument": name, "score": value}` — the simplest thing an author can write, what
`materialize` validates and publishes, and what architecture §4.4 shows. `DerivedRow` and `Output`
went with the adapter. Reads are typed records the framework built (`Observation`, record `128`);
outputs are what the author assembles. Each is the natural shape for its direction.

### The third role reads like the other two

`DataModelContext` is now the one implementation of `authoring.DataCall`, the way
`ConstraintContext` is of `ConstraintCall`. The scaffold, both showcases with a DataModel and the
`materialize` test doubles all declare with `inputs()` and read with `context.read(alias)`. The
emitted template is 59 lines and its import line is the same one the strategy and constraint
scaffolds emit: `from vqapr import authoring as va`.

### The loader stops contradicting the contract it loads

`load_data_model` refused an empty `requirements()`, while `Model.inputs()`'s own docstring says
declaring nothing is legitimate — a model may derive its values from memory alone. Same defect
shape as the constraint loader fixed in M1.1. A DataModel that reads nothing now loads, and the
identity suite asserts it.

## Trade-offs

**Ten tests went with the dead half.** `tests/models/test_agent_first_invocation.py` lost its
DataModel sections; the fast suite went from 1295 to 1285 passed. They tested an adapter nothing
called, so what they proved was already unreachable.

**`Model` on the surface carries `memory`.** A guard test forbade any exported type from
annotating `memory`; `Model` is exempted by name, with the reason. What that test protects — no
value type smuggling framework state through an annotation — is unchanged.

## Validation

```
uv run ruff check src/                           All checks passed
PYTHONUTF8=1 uv run pytest tests/ -q -rs         1285 passed, 14 deselected
PYTHONUTF8=1 uv run pytest tests/ -q -m slow -rs  14 passed
```

Branch parent `develop @ d5e2ebab`, measured: **1295 passed / 14 deselected** fast; **1309** full.

**Showcases: 6 of 9, up from 4.** `show_002` and `show_004` were two of the five in
`docs/issues/052`, broken because their DataModels declared reads in a shape the current requirement
contract no longer accepted. Converging the contract brought them back without a showcase-specific
fix. The three that remain (`show_005`, `show_006`, `show_008`) construct the shipped cap without
the benchmark dataset it now requires, which is neither this milestone's nor this contract's.

Directed checks:

- `public.<X> is authoring.<X>` for `DataModel`, `Constraint`, `ConstraintBounds`,
  `ConstraintFinding`: all `True`. `StrategyModel`: `False`, and M1.3's.
- `tests/cli/test_commands.py::test_a_registered_datamodel_is_runnable_through_run` drives the
  emitted datamodel scaffold through `new -> register -> check -> run` unedited, and passes.
- The deferred-import ceiling lowered 36 → 35, as that test instructs when a change removes one.
