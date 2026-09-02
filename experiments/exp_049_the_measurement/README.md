# exp_049 -- the measurement `docs/issues/049` exists for

`049` measured one model twice and found 806.61 s against 1.31 s: a statement warehouse read
at the vendor's long grain, and the same facts pivoted wide, same reduction, identical output.
The harness that took it lived in a consumer repo and no longer exists (record `136`). This one
lives here, generates its own data, and is what the number in `049` now refers to.

## What it runs

```bash
uv run python experiments/exp_049_the_measurement/bench.py --instruments 1600 --evaluations 4
```

- `bench.py` generates a long statement-facts table (two scopes, quarterly and annual rows,
  thirty account codes, two dump bundles) and its pivot, registers **three** datasets, registers
  three DataModels, materializes each over the same evaluations and instruments, and reads the
  bidirectional anti-join of every pair **before** it reports a timing.
- `exp049_models.py` is the enhanced-index `annual-fundamentals` reduction, rule for rule.
  Three classes differ only in where steps 1-3 (scope/settlement filter, latest bundle wins,
  ordered code fallback) happen: in Python per evaluation (`rows`), in the registration's
  aggregate expressions (`expr`), or before registration (`wide`). Steps 4-5 are one shared
  function.

| side | registration | what the tree does on a read |
|---|---|---|
| `rows` | the long file, `grain: rows` | one scan per evaluation, ranked per name; `rows(alias)` hands back `Observation`s |
| `expr` | the **same long file**, `grain: instrument_instant`, each item an `arg_max(...) FILTER (...)` inside `coalesce` | one grouped scan per run builds the panel; every read is a slice |
| `wide` | a parquet pivoted by exactly `expr`'s expressions | one scan per run builds the panel; every read is a slice |

`expr` is the ruling `049` asked for -- the author keeps the vendor's table and declares the
pivot -- and `wide` is `049`'s own second measurement, unchanged.

## What is and is not comparable to `049`

- **Within-process ratios are the result**, as in `049`. Absolute seconds depend on the machine
  and on the generated size, which is smaller than the 37.8M-row warehouse.
- The `rows` side cannot declare the calendar window the original model did: a `rows` grain
  admits only `InstantsLookback`, and that count ranks **source rows**, not instants, on a long
  table (see the constant's docstring in `exp049_models.py`). The harness gives it enough rows
  to reach three fiscal years for every name; the reduction keeps two, so the output is the
  same, and the anti-join is what proves it.
- Every output value is an integer stored as `DOUBLE`, so the three sides see the same
  `Decimal` and the anti-join compares values, not formatting.

Outputs land in `outputs/` beside this file (gitignored): the parquet files, the workspace, the
three published datasets, `compute_timings.jsonl`, `result.json` and `RESULT.md`.
