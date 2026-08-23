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
**`failures`** — an array of structured diagnostics, each with `code`, `requirement`,
`observed`, `examples`
**`error`** — the Python exception as a string, for traceability

When `ok` is false, read the `failures` array first. Each failure tells you what was required,
what was observed, and gives bounded examples. Fix the inputs and retry.

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
