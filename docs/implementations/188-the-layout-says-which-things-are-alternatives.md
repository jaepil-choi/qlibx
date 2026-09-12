# 188 — The layout says which things are alternatives to each other

**Date:** 2026-09-08. **Branch:** `redesign/component-eventloop` (campaign M6; plan
`.agent/plans/active/component-eventloop-redesign.md`). **Reviews:**
`docs/code-review/2026-09-08-flow-and-evidence-structure.md`,
`docs/code-review/2026-09-08-four-readers-one-loop-and-the-missing-shapes.md` §8-1, order 5.

## Why

Four defects, all of them about placement rather than behaviour:

- **`flow/` laid two split axes flat at one level.** `simulation.py` was the strategy loop and
  `datamodel.py` the datamodel loop -- alternatives to each other -- and they sat as siblings of
  the phase files (`callback`, `execution`, `valuation`) and of the declaration files (`run`,
  `preflight`, `frozen`, `judgments`). Nothing about the directory said which of the seventeen
  files were alternatives, which were stages of one of them, and which served both.
- **`flow/record.py` was 1,950 lines of persistence inside the layer that runs a run.**
- **`evidence/` grouped three files by who reads them**, and its own modules disagreed:
  `record.py` imported it nowhere.
- **`flow/marking.py` was a domain rule filed next to its consumer.** Record `162` moved it there
  on the grounds of consumer adjacency; generalised, that argument puts `exchange/` and `orders/`
  inside `flow/` too, so it cannot be the basis for a layer assignment.

And one naming rule that had outlived its purpose. §10 said *"base · protocol · service ·
manager는 패턴이다"*, written to stop a premature pattern being forced onto a young design and
then read as a ban. The cost was measurable: the four extension points share one concept -- an
object called back on an event with that event's time -- and the concept had no name until
record `181`.

## What

Five commits, each with its own gate.

**1. `flow/marking.py` -> `account/marking.py`.** `ValuationService` picks a mark per held
position. It reads neither `FlowContext` nor `FrozenRun`, and imports only `account/snapshot.py`
and `domain/values.py`, so the move is downward and no cycle appears. This reverses that half of
record `162`.

**2. `evidence/` dissolved.** `TableSpec` and `InvocationRecorder` are a declaration and the
buffer that enforces it, one importing the other, so they are one module: `authoring_records.py`,
beside `authoring.py` and `authoring_lookback.py`. The failure envelope and the evidence values
are the engine's, so `artifacts.py` moved into `flow/`. `vqapr.authoring` already re-exported both
names, so no author import broke. The leaf boundary list names `vqapr.authoring_records` where it
named `vqapr.evidence`.

**3. `record/` promoted, and the edge that blocked it reversed.** The split follows the
dependency rather than the file. `record/` (schema, reader, writer) imports nothing from `flow`;
`freeze_run_record`, `freeze_strategy_record`, `freeze_datamodel_record` and `contract_report`
stay in the engine as `flow/freeze.py`, because they turn engine values into record payloads.
Promoting the file whole would have made `flow -> record -> flow`.

`COMPACT_FILENAME` and `SPILL_BYTES` moved with the machinery. They were declared in
`flow/datamodel.py` and read by the writer, so record `164`'s note that "record imports datamodel,
not the reverse" described the one edge that made the promotion impossible. They are storage
facts; that edge is now reversed.

Inside the package the layering is one way -- **schema <- reader <- writer** -- because
`write_run_record` reads the existing record to detect a conflict. The path helpers are in
`schema.py` (pure layout, both halves need them) and the lock is in `reader.py` (asking who holds
a lock is a read).

**4. The kind axis became a directory.**

```text
flow/  loop.py artifacts.py run_state.py roster.py freeze.py orchestration.py
       declaration/  run preflight frozen judgments
       strategy/     loop <- simulation, callback, execution, valuation, context
       datamodel/    loop, compute, output   <- the split of datamodel.py
```

`strategy/` and `datamodel/` now stand side by side, and that both implement the hooks of
`loop.py` is visible from the tree. What stayed at the top is what serves both kinds --
`run_state.py` in particular, whose consumers are four layers rather than one kind
(`prepare_model_state` in the declaration, `LifecycleKind` in freeze, `RunStateRepository` in
orchestration, `FILL_TABLE` in the CLI). `DataModelTrace` went to `compute.py` rather than
`loop.py` as sketched, because the compute handler both builds and reads it and the other
placement is an import cycle. `tests/flow/` mirrors the new shape.

**5. §10 rewritten.** The naming rule states the principle it was reaching for: requirements are
written as intent and behavior, a pattern is how the current implementation meets them, recorded
with its reason and expected to change when the PRD does. A pattern name is adopted when it is the
shortest true description (`Component`, `EventLoop`, `Handler`) and refused when it dresses a place
that has no such structure. The §10 tree now describes the package that exists, measured, with a
line count per file; the old one still listed `models/`, `valuation/`, `runtime/` and `evidence/`,
none of which have existed for several records. The test-layout paragraph named a `tests/spine/`
that was never created.

## Trade-offs

- **`flow/` is not renamed to `engine/`.** The owner's ruling left that as "a small decision
  attached to" the naming ruling, and the naming rule it attaches to asks whether a name says what
  it does. "Flow" is a named concept of this architecture (§8, `FlowContext`, "one Flow"), so the
  rename would spend the document's vocabulary and leave the structure exactly as it is. The defect
  the review named was the flat axes, and directories are what fix it. This is the one place where
  the campaign's own acceptance criterion was not met as written, and it is deliberate.
- **The move exposed a blind spot in the refusal-code gate, which was fixed rather than
  re-baselined.** The static scanner folded constants per file, so `datamodel.compute_failed` --
  forwarded through a `refusal()` helper that now sits one module away from its caller -- dropped
  out of the inventory without even being reported as unresolved. `_FileIndex` became
  `_SourceIndex` over every module in the package. `module_constants` deliberately does **not**
  merge: a name that is a module constant in one file is often a parameter in another, so merging
  would fold a code to a stranger's value and also stop the resolver following a parameter that was
  forwarding one -- two silent wrong answers instead of one honest non-answer. A new test pins the
  reach with two probe modules that bind the same constant name to different strings. The committed
  baseline is byte-for-byte unchanged, which is the evidence that the vocabulary never drifted:
  nothing was gained or lost elsewhere, so the per-file scanner had exactly one blind spot.
- **Package `__init__.py` files stay empty.** A consumer names the module it means. Re-exporting
  from `strategy/__init__.py` would have made the directory a façade and hidden the very structure
  the move exists to show; the one façade this package has is `public.py`, and it is enough.
- **Records that now name old paths are left alone.** `docs/implementations/*` is history and must
  keep saying what was true when it was written -- including record `164`'s note about the two
  constants, which this record supersedes rather than edits.
- **One test had no module to follow.** `tests/flow/test_simulation_timing.py` imports nothing from
  `flow/`; its two tests belong to `portfolio/` and `constraints/` and its name describes neither.
  Splitting it needs its shared fixture divided, so it is left where it is and raised separately
  rather than folded into a move.

## Validation

- `uv run pytest tests/ -q` (fast set): 1573 passed, 5 skipped (1572 + the scanner probe).
- `uv run pyright src`: 0 errors. `uv run ruff check src`: clean.
- `uv run pytest tests/boundaries/test_a_deferred_import_states_its_reason.py`: passes, the
  function-local import count still exactly 12.
- `uv run --no-sync python showcases/show_001_execution_input_registration/run.py`: runs.
- `tests/characterization/refusal_codes.baseline.json`: unchanged.
