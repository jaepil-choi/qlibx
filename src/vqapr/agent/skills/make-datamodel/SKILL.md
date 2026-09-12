---
name: make-datamodel
description: Writes and validates a project-local vqapr DataModel — reusable per-instrument derived panels such as factor exposures (loadings), betas, rolling statistics, or ML predictions that several strategies subscribe to. Use when the user wants to precompute or share an intermediate value across strategies, mentions a factor-exposure or feature table, or asks whether a calculation belongs in a DataModel or inside the StrategyModel. A factor's return series (SMB, HML, a long-short spread) is not a DataModel — it is the return of a factor-mimicking portfolio, which make-strategy builds.
---

# Write a vqapr DataModel

## Invoke the CLI through the active environment

Installing a console script into a virtual environment does not put it on the global shell PATH.
Use one launcher consistently:

- activated environment: `vqapr --help`
- uv-managed project: `uv run vqapr --help`

If bare `vqapr` is not found but `uv run vqapr` works, the package is installed; the environment
is simply not activated. Apply the same prefix to every command below.

## First: does this belong in a DataModel at all?

A DataModel computes **a new dataset** from registered ones. A StrategyModel decides **how capital
is divided**. The boundary is not about difficulty, and getting it wrong is the most common way
this skill is misused.

**A DataModel is optional.** A direct StrategyModel that reads prices and decides is complete; a
DataModel is what you reach for when a StrategyModel needs a reusable intermediate table — one
several strategies share, or one expensive enough to compute once.

[references/datamodel-or-strategy.md](references/datamodel-or-strategy.md) has the test to apply.
Apply it before writing code: moving logic across this line later means a new id and a new
registration.

## Start from the scaffold

```bash
vqapr new datamodel <id> --dataset <dataset-id>
vqapr new datamodel <id> --dataset <d> --calendar-lookback 60
```

writes a `.py` that **runs as written**, plus the `.yaml` that registers it and the `runs:` block
that executes it. Start there: the scaffold is generated from the contracts the package enforces,
so it cannot drift from them.

The file is loaded by its path and its directory is not on the import path, so a DataModel cannot
`import` a module beside it. Shared code goes in a package installed in the environment (or on
`PYTHONPATH`); make-strategy's "One strategy is one file" has the rule.

The `--lookback` / `--calendar-lookback` choice is not cosmetic. See below.

## The lookback pair, and why it matters more here

`RowsLookback(rows=N)` gives each name **its own** last N observations; `CalendarLookback(days=N,
timezone=...)` gives every name **the same window**.

A DataModel is usually the place a **cross-sectional** quantity is computed — a beta, a covariance,
a factor exposure, a rank. Those need `CalendarLookback`. With `RowsLookback` on an unbalanced
panel, a real universe asking for 313 rows got rows spanning **1,865 sessions, back eight years**,
and a correlation matrix built on it mixes a live name's recent returns with a delisted name's
decade-old ones. Every number is finite and every check passes.

[references/reading-inputs.md](references/reading-inputs.md) has both members, the two read verbs,
and the `current()` / `latest()` trap.

## What `compute()` returns is typed by its first session

This is the rule that surprises people, and it is worth stating before any code is written:

**The output dataset's `field_types` are read off the first non-empty session's rows and registered
as the declaration.** Every later session must fit that schema, and **nothing is cast**.

- Return `float` for a continuous quantity, `int` for a count.
- A `Decimal` value field is refused at the first session (`datamodel.output.field_type`), because
  a dataset carries one numeric type per field and DECIMAL is not one a dataset may declare.
- A later session whose rows do not fit is refused with `datamodel.output.schema_mismatch`, which
  quotes pyarrow and the established schema and does not guess further.

So a model that returns `int` on a quiet first session and `float` afterwards fails on session two,
having passed session one. [references/output-schema.md](references/output-schema.md).

`available_at` is the package's to stamp. A row that carries one is refused.

## A DataModel is a run

Not a script and not a build step. It is declared in `runs:` with `datamodel:` instead of
`strategy:`, names the dataset it makes under `writes:`, and is executed with the same three
commands a strategy run takes:

```bash
vqapr register <file.yaml>
vqapr check <run-id>
vqapr run <run-id>
```

No account, no venue, no execution dataset — those keys are **refused** on a datamodel run.

Where the output lands, how to read it back, and how to retry a run whose output is already
registered are in [references/running-a-datamodel.md](references/running-a-datamodel.md).

## Why a derived table belongs here rather than in the source

A moving average, a cumulative sum, a rank or a resampling makes one row's value depend on another
row's observation. Computed while preparing the source file, that dependency becomes invisible —
the registered table holds a number and nothing says which observations went into it.

In a DataModel it obeys the same point-in-time boundary every other read obeys, declares its
inputs, and lands in the result's lineage.

## Validate before you believe it

```bash
vqapr register datamodel <id> <file.py>
vqapr check <run-id>
```

A component that imports and loads is **not** thereby compatible — being findable is not being
valid.

If a declaration has drifted far from the contract, do not repair it. Generate a fresh one with
`vqapr new` and move your logic in.

## Stop condition

`vqapr run <run-id>` returns `ok: true` with a `datamodels` map carrying `dataset_id`, `rows`,
`sessions` and a `record`; `vqapr list datasets` shows the output; and the user has agreed that
the calculation belongs on this side of the DataModel / StrategyModel line.

---

A refusal carries its own status, stage and cause, plus `fix`, `requirement`, `observed` and
`source` — read it rather than looking for it here. Status **500 is a vqapr defect**: do not work
around it, report it with the envelope. **502 is your own code raising** — `cause.origin` is
`"user"` and `cause.where` is your file and line; fix the component. **503 is the machine** — retry
unchanged.
