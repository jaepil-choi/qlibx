# 076 — A DataModel you can run

`vqapr new datamodel` emitted one. `register` accepted it. `show model` described what it reads and
what it forms. And no command ever ran it.

`flow/materialize.py` is 1,100 lines holding a real entry point — `materialize()` — that the CLI
never called. So the package could scaffold, register and describe a DataModel, and the only way to
execute one was to write Python against an import the agent-facing surface does not document.

## Through `run`, not a verb of its own

The owner's ruling: a DataModel must be runnable the way a StrategyModel is. Not a `materialize`
verb, and not by removing the front door.

Registration is already symmetric — `register.py` maps `datamodel` beside `strategy` — so a second
top-level verb would have *added* an asymmetry rather than removed one. `run` dispatches instead on
the component section the spec already names:

```yaml
datamodel: derived                     # instead of `strategy:`
instruments: [A005930]
output:
  dataset_id: derived-values
  value_fields: [value]
evaluate_at:
  - "2024-03-06T04:00:00+09:00"
```

**Dispatch on the component key, not a new `kind:` key.** Every existing spec already says
`strategy:`, so none needs an edit — and a spec cannot disagree with itself about what it is, which
a separate `kind:` would permit. Declaring both, or neither, is refused as
`check.spec.kind_ambiguous` rather than resolved by a precedence rule the reader would have to know
before they could predict what their own file does.

That code is raised as an `InputError` and is deliberately **not** in `check`'s `CODES`: the
inventory is the judgments the verb settles about a spec it could read, and this is the question of
which spec it is holding.

## Six of the eight required keys do not apply

`_REQUIRED` became `_REQUIRED_BY_KIND`. Of the simulation's eight keys, `instruments` is shared and
`strategy` is what `datamodel` replaces, so six do not apply: `valuation`, `start`, `end`,
`exchange`, `execution_input`, `initial_account`. A materialization has no venue, no execution
table, no account, no valuation and no trading period; `materialize()` takes evaluation instants
and instruments and nothing else. Forcing one required set on both would have made an author
declare six keys that mean nothing for their run — the exact failure that tuple's own docstring
already warns about in the other direction.

Both this sentence and the docstring it describes first said *five*, and named only four of the six.
The boundary gate's cleaner lane caught it on the fifth pass through this record, by measuring the
claim the sentence actually makes rather than the nearest countable proxy — the tuple length is
eight and always was, but *how many of those eight do not apply* is a comparison across two tuples
that no single count reaches. They are enumerated in both places now.

## The half that would have re-committed the defect

Extending `run` without extending `check` would have produced, in the task meant to close a door,
the thing this whole slice opened with: **a verb that certifies a spec the next command refuses.**

`_PHASES` runs `declaration` and `preflight`, both of which build and freeze a `RunDefinition`. A
materialization has none. This is not a near miss — `_judge_period` returns
`check.period.uncovered` for any spec without `start`/`end`, and `ok` is
`not failures and not blocked`, so `check` would have refused **every valid materialization spec
ever written**.

So the fork is at the phase tuple, not at the readers:

```
simulation:      spec, workspace, judgments, declaration, preflight
materialization: spec, workspace, judgments
```

The document is now read once above the loop to choose the tuple, and `checked` is projected from
the tuple that was selected rather than from the module-level constant.

`MATERIALIZATION_CODES` held eight judgments of its own — nine after the boundary gate, below —
each a refusal `materialize()` raises later, hoisted to where it costs nothing: the component is registered, it is a DataModel and not
something else, it loads, the output `dataset_id` is not already registered, there is at least one
evaluation instant and one instrument, every dataset it declares it reads is registered, and the
declared lookback reaches back past the earliest evaluation.

**A ninth materialization judgment, added deliberately after the gate found the divergence it
prevents.** `_instant` returns `None` for anything it cannot read, including a naive datetime, and
the judgments simply skipped those — so a spec whose `evaluate_at` carried
`2024-03-06T04:00:00` with no offset passed `check` with `ok: true` and was then refused by `run`.
That is the check-certifies-what-run-refuses divergence this whole slice exists to close, and it had
opened inside the task meant to close it. `check.materialize.evaluation_instant_invalid` names every
unreadable entry and says a naive datetime is refused rather than assumed to be in any particular
zone. The pinned count moved from eight to nine, which is what its own message says such a change
has to be: a decision, not a detail.

**`CODES` is now two counted sets**, and `tests/cli/test_check.py` counts them separately. Merging
them would have let a materialization judgment silently take the place of a simulation one, and the
pinned message — *"adding a ninth is a decision, not a detail"* — would have stopped meaning what it
says. A reader counting the judgments a simulation settles still gets eight.

## What `check` cannot prove, and what happens instead

A `DatasetRegistration` records a `span` and not a row count. So `check` can prove that a dataset's
history reaches back past the earliest evaluation, and cannot prove it holds *enough rows* — a
lookback of six against three sessions passes every metadata judgment and then produces nothing.

That case surfaces at `materialize.output.empty`, which is a structured refusal and not a crash.
But its `fix` named only "widen the requested instruments/evaluation_times, or fix
DataModel.compute" — the two things that are usually already right. It now names the declared
lookbacks and says plainly that a lookback longer than the available history makes every window
short and every evaluation empty.

Stating the boundary rather than pretending it is not there: `check` proves what registered
metadata can prove, and the refusal that catches the rest is actionable.

## Flags that name a run record are refused, not ignored

`--run-id` and `--force` are defined entirely in terms of a run record, and a materialization
writes none — it registers a dataset. Accepting a flag that cannot do what its name says is how a
reader learns the wrong model of a command, and `--force` in particular names a destructive act it
would not perform. Both refuse, naming the flag.

## Zero new module imports

`public.py` already re-exports `materialize` and `MaterializationSpec`, and `cli/run.py` already
imports from `vqapr.public`. Nothing here imports `flow/materialize.py`, `project.py` or
`vqapr.open` — the facade ruling in `docs/design/agent-first-surface.md` holds unchanged.

The envelope reports `dataset_id`, `output_path`, `lineage_path`, `evaluations` and `rows_total`.
Named from what `MaterializationResult` actually carries: it has no row count, because rows are
per-evaluation on `MaterializationInvocation`, so the total is a sum and is reported under a name
that says so.

`list datasets` is the readback. The output is a registered dataset like any other, which is what
makes it readable by the next model.

## Two defects the boundary gate found in this task

**A relative component path resolved against the process CWD.** Both the new check judgment and
`materialize()` itself called `load_data_model(ref)` with no `project_root`, and `_load` resolves a
relative `ref.path` against the CWD when none is given. Every other loader on the run path passes
it — `preflight_run` for each kind, `check`'s dataset judgment — and these two did not, so a run
depended on where it was invoked from. `check` and `run` were wrong in the *same* direction, so
this was never a divergence, which is why the architect lane rated it MEDIUM rather than blocking;
but agreement does not make either correct, and the symptom was misattributed — the refusal said
"fix the component so it loads" when the component was fine and the path resolution was not.
Invisible whenever the CWD equals the project root, which is every test and the common interactive
case.

**An `except Exception` that claimed more than it guarded.** The handler labelled
`component_unloadable` wrapped the load, the requirements walk, the `evaluate_at` parsing and the
whole lookback loop — so a malformed `evaluate_at` entry was reported as a component that would not
load, and a spec could carry `lookback_uncovered` alongside a contradictory `component_unloadable`.
It is scoped to the two calls its message describes now. `_judgments` avoids the same shape
deliberately, and this had not followed it.

## Validation

```
uv run pytest tests/ -q      # 1315 passed, 14 deselected
```

- `test_a_registered_datamodel_is_runnable_through_run` — the whole path through the CLI:
  `new datamodel`, `register`, `check` (asserting `checked == [spec, workspace, judgments]`, no
  `check.period.*` / `check.weights.*` / `check.execution_ordering.*` anywhere in the envelope, and
  `blocked: []`), `run` (two evaluations, non-zero `rows_total`, both files on disk), and
  `list datasets` showing the output.
- `test_a_materialization_spec_refuses_what_it_cannot_honour` — eight refusals, including both
  ambiguity directions, a registered component of the *wrong kind* named as that rather than as
  missing, and the naive `evaluate_at` the boundary gate found.
- `test_a_materialization_refuses_the_flags_that_belong_to_a_run_record` — both flags, each named
  in its own refusal, neither reaching `stage: "unhandled"`.

The refusal-code baseline gains the nine `check.materialize.*` codes in `coverage_gap` — declared
and not provoked by the characterization harness, which is accurate: the harness builds no
materialization specs. Nothing was removed.
