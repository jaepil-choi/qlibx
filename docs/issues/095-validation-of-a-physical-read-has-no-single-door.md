# 095 — Validation of a physical read has no single door: three modules, one file scanned three times

**Status: OPEN 2026-09-10 -- owner-filed, from the 0.11.0 spine trace
(`experiments/exp_230_the_spine_trace/`). Plan: `.agent/plans/active/one-door-campaign.md`, milestone V.**

| | |
|---|---|
| vqapr version | `0.11.0` (develop `05dbc1f5`) |
| reported | 2026-09-10 |
| reporter | owner, reading the sample-project traces |
| evidence | traces `01_register`, `05_check_short`, `06_run_short`, `07_run_features` |

## What the trace shows

Every parquet the framework opens is validated, which is right. What is wrong is **where**: the
validation lives in three modules with three shapes, and the same file is scanned more than once
for the same facts.

| physical read | validated by | called from (trace) |
|---|---|---|
| a dataset's parquet | `data/datasets.py::validate` -- four stages (schema, key, span, values) plus `execution_role_failures` | register `#133`, `#321`; datamodel output `07 #19746`; strategy allocation `06 #45045` |
| the execution table | `exchange/execution_table.py::validate_execution_table` -- `_schema_diagnosis`, `_key_diagnosis`, `_price_diagnosis`, each a scan | check `05 #7490`; run preflight `06 #4149` (inside); run `06 #8138` |
| the instrument roster parquet | `domain/instruments.py::read_roster_table` + `build_roster` -- raises, returns no `Diagnosis` | register `01 #43`; run `06 #8190`; `flow/roster.py`; `cli/list_.py` |
| a component's source | `extension/conformance.py::conformance` -- a `Diagnosis` | register `01 #524`, `04 #568` |

The execution table `sample-execution` is one dataset. At registration it passes the four-stage
`validate` (`#321`, key proved unique on `(available_at, instrument)`). Then `check` scans it again
for schema, key and positive price (`#7490`, 43.5 ms), `run`'s preflight scans it a third time
(inside `#4149`) and `orchestration.run` a fourth (`#8138`, 44 ms). The key scan at preflight
proves what registration proved; the price scan asks a question registration could have answered
for every candidate price at once.

`read_roster_table` is a different shape altogether: a bare function that raises, so a bad roster
is not a `Diagnosis` and cannot be collected beside the other refusals of a declaration.

## Why it matters

- **The principle is not stated anywhere.** "A file is measured once, at the door where it enters
  the workspace; every later reader verifies identity, not content" is what the design wants
  (`docs/issues/archive/023` for the identity half) and nothing in the tree says it. A new
  physical read (the roster, a benchmark, an execution table) invents its own checks.
- **The scans are the cost.** The `check` trace is 11.8 s, of which the execution-table scans are
  the whole of it; `run` re-does two of them. On a minute-grained table these are not 44 ms.
- **The declaration facts and the measured facts are mixed in `datasets.py`.** The module that
  says what a registration *means* (`DatasetRegistration`, `parse_grain`, `parse_field_types`)
  also holds 400 lines of scanning and refusal text. `data/datasets.py` is 1,090 lines.

## Proposed fix (milestone V of the plan)

One module owns validation of physical reads -- `data/validation.py` -- with one door:

    verify_source(registration, spec) -> Verified | Diagnosis

`Verified` is the measured facts registration stores: span, projection types, `aggregated`,
row count, the key proved, the physical digest, and for an execution-role table which numeric
fields are finite-and-positive-when-tradable. Stages are small callables with one shape,
`(registration, spec, facts) -> Diagnosis`, run in the order they depend on each other (schema
before key before span before values before role). The roster read becomes a stage of the same
door and returns a `Diagnosis`.

Preflight and run stop scanning: `require_verified(registration)` compares the stored digest to
the file and refuses `dataset.source_changed` when it differs, and reads the price facts from
`Verified` instead of scanning for them. `validate_execution_table` and the three `_*_diagnosis`
functions are deleted. `datasets.py` keeps the declaration and loses the checks.

A boundary test holds the door: no module outside `data/validation.py` may call
`scan.describe`, `scan.key_check`, `scan.span_check`, `scan.finite_check` or
`scan.positive_finite_when_true`; and the hot-path cost test counts zero content scans of the
execution table during `check` and `run`.
