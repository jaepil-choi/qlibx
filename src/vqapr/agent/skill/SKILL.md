---
name: vqapr
description: Quantitative strategy backtesting framework — registration, materialization, simulation, and measurement
---

# vqapr agent skill

**Use this skill when the task involves registering financial datasets, building and testing
quantitative strategy models, materializing evaluation data, or running backtesting simulations
with the vqapr framework.**

## What vqapr is

vqapr is a deterministic backtesting framework for quantitative portfolio strategies. It takes
registered datasets and strategy components, materializes evaluation data, runs simulations
against a declared venue, and produces measurement results. The framework validates every input
before executing and refuses with structured diagnostics when something is wrong.

## What this skill does and does not do

**The CLI owns usage; this skill owns remedy.** When vqapr refuses an input, the CLI tells you
*what* failed (structured JSON with stage, code, requirement, observed, and examples). This skill
tells you *how to fix it* — what the failure means in context, what your options are, and what
trade-offs each option carries.

This skill **never**:
- Bypasses package validation
- Guesses missing semantics
- Confirms a binding before evidence exists

## The mission path — three rungs

Work with vqapr follows three rungs. Each rung depends on the previous one succeeding.

### Rung 1 — Registration

**Goal:** a workspace where every dataset, source, component, execution input, and agenda is
registered and passes validation.

1. `vqapr list datasets` — see what exists (returns empty on a fresh workspace, that is fine)
2. `vqapr new datamodel <id> --dataset <d>` or `vqapr new strategy <id> --dataset <d>` —
   scaffold a component and its declaration
3. Write a declaration YAML for datasets, sources, agendas, and other workspace elements
4. `vqapr register <declaration.yaml>` — validate and add to the workspace
5. `vqapr list <kind>` — confirm what was registered

**Stop condition:** `vqapr list` shows all required elements and `register` accepted every
declaration without failures.

#### Before registering: settle what `available_at` means

**This is the decision to raise before the first `register`, not after it fails.** The framework
validates schema, keys and duplicates. It cannot detect a look-ahead, because a timestamp that is
wrong in meaning is still perfectly well-formed.

`available_at` is **when the row could first have been known**, not when the event it describes
happened. Those differ, and the gap is where look-ahead enters:

- A daily close observed at the session close is available at that close, not at midnight of the
  same date.
- An accounting fact for a fiscal quarter is available when it was *published*, which is weeks or
  months after the period it covers. A fixed lag applied to a period end is an approximation, and
  whether it is a safe one is a judgement about the data, not about vqapr.
- A revised or restated value is available at the revision, not at the original observation.

Ask, and do not answer on the user's behalf:

1. Is this column an observation, a publication, or a revision?
2. What timezone is the timestamp in, and is it the event instant or a date?
3. If it is a date, what instant within that date is defensible?

If the answer is not in the data or its documentation, say that it is unknown and let the user
decide. **Do not infer a convention from a column name.** A column called `date` proves nothing
about availability, and a registration built on that guess produces results that look correct.

The same care applies to query patterns written at registration time. Moving averages, cumulative
sums and ranks can each reach across rows in a way that pulls future information into a past row;
flag them and explain what would have to be true for the pattern to be safe.

### Rung 2 — Materialization and run

**Goal:** a completed simulation run that produces a result.

1. `vqapr new run-spec --out spec.yaml` — get a template with every required key explained
2. Fill in the template with registered component IDs, agenda IDs, instruments, and dates
3. `vqapr run spec.yaml` — preflight, freeze, and execute the simulation

**Stop condition:** `vqapr run` returns `ok:true` with an `occurrences` count and
`account_version`.

### Rung 3 — Measurement

**Goal:** verify that the simulation produced the expected results and that measurements are
reproducible.

This rung depends on what the specific task requires. Common steps:
- Compare output against known baselines
- Verify that account state matches expectations
- Check that the simulation result is deterministic across runs with identical inputs

## Reading vqapr's output

Every vqapr command returns exactly one line of JSON to stdout. The shape is always:

```json
{"ok": true, "stage": "...", ...}
```
or
```json
{"ok": false, "stage": "...", "family": "...", "failures": [...], "error": "..."}
```

**`ok`** — did the command succeed?
**`stage`** — which processing stage produced this result (e.g. `workspace.register`,
`run.complete`, `cli.input`)
**`failures`** — an array of structured diagnostics. Every entry carries `code`, `requirement`
and `observed`; `examples` and `example_total` are present but **may be empty**
**`error`** — the Python exception as a string, for traceability

When `ok` is false, read the `failures` array first. `requirement` says what was needed and
`observed` says what was found; those two are always populated and are usually enough to act on.

**`examples` is empty for structural checks, and that is not a bug.** A check on a column's
*type* has no offending row to quote, so it reports `"examples": [], "example_total": 0`. A check
on row *contents* — a duplicated key, a null in a key field — quotes up to five offending values
and `example_total` says how many there were before truncation. An empty `examples` next to a
non-zero `example_total` never happens; if you see one, that is worth reporting.

Fix the inputs and retry.

## CLI reference

Run `vqapr --help` for the full verb list, and `vqapr <command> --help` for each command's
arguments and options. The CLI help text is the authoritative usage reference; this skill does
not duplicate it.

## Friction logging

When something is harder than it should be, write it down **before** resolving it. Record:
- What you were doing
- What you expected
- What actually happened
- How long it took and how you resolved it
- What would have prevented it

This log is the deliverable. The framework improves from honest friction, not from workarounds.
