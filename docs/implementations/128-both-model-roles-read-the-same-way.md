# 128 — both Model roles read the same way

## Why this exists

`docs/issues/036` is a table a first-time user had to build before they could get through the
package. It lists ten ways that authoring a DataModel differs from authoring a StrategyModel —
different import, different declaration method, different requirement type, different entry point,
different way to get rows, different row type, different name for the instrument, different name
for a field. The owner ruled on 2026-08-31:

> **a DataModel and a StrategyModel should be substantially similar to use, and the size of the
> current difference is itself the defect.** The answer is CONVERGE — `SKILL.md:73`'s *"Both are
> authored the same way"* is what the product should be made to mean.

The direction was settled on 2026-09-01: converge onto the authoring shape.

This record closes the read half — rows 5 through 8 of that table. It does not close the
declaration half, and it does not yet make the two classes one.

## What changed

**`models/calls.py` is the one read path.** `requirements_for` (one requirement per declared
field), `declared_rows` (join the per-field batches back on `(instant, instrument)`) and the row
projection move here from `_internal/pit_bridge.py`, **unchanged**, and that module is deleted.

They lived under `_internal` because two capability surfaces sat over one `ModelWindow`:
`strategy_bridge` served an authored `call.read(alias)` while the engine served
`context.window.observations(requirement).rows`, and something had to translate. With both
contexts reading through this code there is no boundary left for it to sit on.

**Both contexts have `read(alias)`.** `DataModelContext` and `StrategyModelContext` share one
`_DeclaredReads` implementation, so the two roles differ by what a StrategyModel additionally
receives — account, previous state, constraint bounds — and by nothing else.

**`Model.inputs()` is the declaration, and `requirements()` is derived from it.** A Model can no
longer declare one thing to preflight and read another at the callback. A Model that overrides
`requirements()` by hand still works and reads through the window directly; both paths resolve
against the same window, so a tree part-way through the migration behaves identically either way.

## What lane C settled first, and what that removed from this record

Lane C landed `docs/issues/049` while this was in flight, and two of its rulings changed the work:

- **`DataRequirement` names `(dataset_id, field_id, lookback)`.** An alias declaring three fields
  is three requirements, so the fan-out and the join are needed rather than optional —
  `requirements_for` and `declared_rows` are exactly that pair, already written and already
  tested, so this record moves them rather than inventing them.
- **`consumer_id` moved off `DataRequirement` and onto `ModelWindow`.** An earlier commit on this
  branch had the loader stamp `component_id` onto the instance so a requirement could carry it.
  That is now a second answer to a question the framework already answers, so it was removed
  before this record landed rather than left as a harmless duplicate.

The uniqueness half of 049 — a field id unique across the workspace — was **overturned by the
owner** after this session measured it against the research workspace: 27 datasets there share 21
field ids, and most of the sharing is ordinary domain vocabulary rather than parallel families
(`fiscal_yyyymm` appears in six datasets because that is the column's name). `DatasetInput` keeps
its `dataset_id` as a result; removing it had been on the table only while a field id was going to
be an id on its own.

## Validation

- `uv run pytest tests/ -q` — 1292 passed, 0 failed, on `develop@04ffed20`.
- `uv run pytest tests/ -q -m ""` — the slow journeys included.
- `uv run ruff check src/` — clean.

**Thirty-eight tests failed part-way through and the cause was one line.**
`AdaptedStrategy.requirements()` still imported from the module this record deletes. Recorded
because the count read as structural and was not: eighteen CLI tests, six valuation-clock tests
and three `check` tests all traced back to a single stale import, and reading the count rather
than the first traceback would have sent the repair in the wrong direction.

`tests/internal/test_pit_bridge.py` moved to `tests/models/test_calls.py` with the code it covers.
`tests/models/test_data_model.py` was pinning `DataModelContext`'s field list as a proxy for
capability absence; it now asserts the absence itself, because `reads` is a narrowing of the
window the context already carried and not a new capability.

## What is next, and what this deliberately did not do

The characterization suite adopted here (`tests/extension/test_one_authoring_surface.py`, from
`qlibx-wt-038-049-9e`) still passes, and every assertion in it is a statement that the package is
still wrong. Three names remain exported by both `vqapr.public` and `vqapr.authoring` as different
objects — `DataModel`, `StrategyModel`, `Constraint` — and `load_data_model` and `load_constraint`
still refuse an authored one outright (`docs/diagnostics/2026-08-31-post-step-07-review.md` R5).
Each test names the milestone that deletes it.

Remaining, in order: one class per contract (which closes R5), deleting the adapter
(`_internal/strategy_bridge.py` and the StrategyModel half of `_internal/models/agent_first.py`),
one scaffold protocol (R6) with the placeholder models as the templates themselves rather than as
template strings, and migrating the six DataModels in the research workspace.
