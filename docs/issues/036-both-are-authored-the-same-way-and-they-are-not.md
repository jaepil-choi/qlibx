# 036 — "Both are authored the same way" — a DataModel and a StrategyModel share no import, no declaration shape, no entry point and no row type

**Status:** **owner-decided 2026-08-31 CONVERGE. Constraint DONE, two roles remain, as of 2026-09-02.** The ruling:
**a DataModel and a StrategyModel should be substantially similar to use, and the size of the
current difference is itself the defect.** So the answer to "What to settle" is CONVERGE - the
sentence at `SKILL.md:73` is what the product should be made to mean, rather than what should be
edited to match the product.

The table below is therefore a work list, not an explanation. The timestamp row leads, because it is
the one with a correctness consequence (`docs/issues/033`).

> **Status update 2026-09-02 — which rows of that table are closed.** The header above read *"not
> yet implemented"* for a day longer than it was true; this replaces it.
>
> **Closed.** Rows 5-9 by record `128` (`Model.inputs()` is the one declaration, `context.read(alias)`
> is the one read verb, both contexts share one `_DeclaredReads`, a row is an `Observation` carrying
> `instrument_id`, `available_at` and `values` on **both** sides). The lookback pair by record `126`
> — `public.CalendarLookback is authoring.CalendarLookback` is now `True`, and so is `RowsLookback`.
> `_internal/pit_bridge.py` is deleted.
>
> **Still open — rows 1-4 and 10, verified in the installed tree on 2026-09-02.**
>
> ```
> vqapr.public.DataModel     -> vqapr.models.data_model.DataModel
> vqapr.authoring.DataModel  -> vqapr.authoring.DataModel          same object? False
> vqapr.public.StrategyModel / vqapr.authoring.StrategyModel        same object? False
> vqapr.public.Constraint    / vqapr.authoring.Constraint           same object? False
> ConstraintBounds, ConstraintFinding                               same object? False
> ```
>
> **Update, record `130`: `Constraint`, `ConstraintBounds` and `ConstraintFinding` are now one
> object each, and `load_constraint` accepts the authoring contract.** Two pairs remain --
> `DataModel` and `StrategyModel` -- and they are M1.2 and M1.3. The paragraph below is the state
> before that, kept because the three consequences it names are the shape the remaining two still
> have.
>
> Five same-name-different-class pairs remain. Three consequences follow, and each is a separate
> user-visible defect rather than an internal duplication:
>
> 1. **The loader accepts the authoring contract for exactly one of the three extension points.**
>    `load_strategy_model` adapts an `authoring.StrategyModel` through
>    `_internal/strategy_bridge.py`; `load_data_model` and `load_constraint` have no counterpart and
>    refuse with *"make the registered object a subclass of `vqapr.constraints.constraint.Constraint`"*
>    — i.e. the framework refuses the module it just told the author to import. This is R5 of
>    `docs/diagnostics/2026-08-31-post-step-07-review.md` and it is still exactly true.
> 2. **The three scaffolds emit two surfaces.** `vqapr new strategy` emits
>    `from vqapr import authoring as va` / `va.StrategyModel` / `decide(self, call)` /
>    `call.read("prices")`. `vqapr new datamodel` emits `from vqapr.public import DataModel,
>    DataRequirement` / `requirements()` / `context.window.observations(...)` — **the older shape,
>    which record `128` kept working but did not make canonical.** So the scaffold still teaches the
>    difference this issue is about, one release after half of it was removed. R6, still true.
> 3. **`SKILL.md` still says it.** The sentence this issue is named after is unchanged at
>    `src/vqapr/agent/skill/SKILL.md:99`.
>
> `_internal/strategy_bridge.py` (287 lines) states its own deletion condition in its docstring:
> *"Two capability surfaces over the same data. That is the next convergence, and when it lands this
> file has nothing left to do."* Closing rows 1-4 and 10 is what deletes it, together with
> `_internal/models/agent_first.py` (499 lines). The target shape is
> `docs/design/the-panel-the-surface-and-the-run.md` §3, and the owner put it **first** in that
> document's §6 order.

**Status when filed:** open. Found 2026-08-30 by the first-time-user journey in
`kaist-thesis/vqapr-final-testbed/`, against `vqapr-0.2.0a1`. Recorded there as **F-012**,
`slowed` / `docs`.
**Touches:** `src/vqapr/agent/skill/SKILL.md:73`; the `vqapr new datamodel` and
`vqapr new strategy` scaffolds; `vqapr.public` vs `vqapr.authoring`.

## The sentence

`SKILL.md:73`, verbatim:

> *"A DataModel derives a column, and `run` executes it. A StrategyModel decides what to hold; a
> DataModel computes a new dataset from the ones you registered. **Both are authored the same way**
> and both are described by `vqapr show model <id>`."*

The second half is true, and `vqapr show model <id>` is excellent — it reports `reads`, `decides`,
`forms`, `weights` and `records` in one envelope. The first half is false at every layer.

## The table the reporter had to build

| | DataModel | StrategyModel |
|---|---|---|
| import | `from vqapr.public import DataModel, DataRequirement, RowsLookback` | `from vqapr import authoring as va` |
| declaration method | `requirements()` -> **tuple** | `inputs()` -> **dict**, keyed by a name you invent |
| requirement type | `DataRequirement.of(consumer, dataset, fields=, lookback=)` | `va.DatasetInput(dataset_id=, fields=, lookback=)` |
| entry point | `compute(self, context)` | `decide(self, call)` |
| getting rows | `context.window.observations(req).rows` | `call.read("<your key>")` |
| a row is | `dict` | an **object** |
| the instrument | `row["instrument"]` | `row.instrument_id` |
| a field | `row["excess_return"]` | `row.values["excess_return"]` |
| the timestamp | `row["available_at"]`, present | not visibly present |
| returning | `list[dict]` with `instrument`/`value` | `va.StrategyResult(decision=...)` |

## Two module paths for the same job

`vqapr.public` exports `StrategyModel`, `DatasetInput` and `CalendarLookback`, so a strategy *can*
be written against it. But the scaffold the package emits for a strategy uses `vqapr.authoring`, and
the scaffold it emits for a datamodel uses `vqapr.public`. **Nothing says which is canonical**, and
the skill's own four-line strategy sketch uses bare names with no import line at all, so it endorses
neither.

## Why the timestamp row is the one that costs

Issue 033 establishes that a cross-sectional model must pivot on each row's own timestamp rather
than trusting arrival order, and that the pivot is the difference between a correct residual and a
silently wrong one.

In a DataModel that is easy: the timestamp is a row key. In a StrategyModel the reporter could not
tell from the scaffold, the skill, or the type whether a row carries one at all — the scaffold reads
`row.values[...]` and `row.instrument_id` and touches nothing else. They shipped a `_stamp_getter`
that probes five plausible attribute names (`available_at`, `observed_at`, `as_of`, `timestamp`,
`event_time`) and raises with a `dir()` dump if none is there, plus a one-shot dump of the row's real
shape to a file.

That is defensive scaffolding around a question a row key answered for free one component kind ago.

**Cost:** ~12 minutes, most of it re-deriving for `decide()` what had already been established for
`compute()` and what the skill had said would transfer.

## What to settle

Either the two contracts converge, or the sentence is corrected and the differences are tabulated.
The reporter's note is the fair summary: *"this table took me longer to build than it would take to
ship."*

Converging them is the larger change and may not be wanted. Correcting one sentence and shipping the
table is not.
