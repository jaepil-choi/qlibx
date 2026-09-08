# What a run declares

The template from `vqapr new run --out runs.yaml` carries every required key with its meaning, and
it is generated from the contract the package enforces. **Fill the template rather than
hand-writing the YAML** — this file explains the choices, not the key list.

## Sessions and the wall time

A run declares **when it fires**, in two parts:

- `sessions_from: <dataset-id>` — every session that registered dataset has. Or an explicit
  `sessions:` list.
- `timezone` and `at` — the venue-local wall time within each session.

There is no separate agenda to declare and no cadence key. Every strategy is called on **every**
session at `at`, and decides for itself whether to act.

**A monthly rebalance is a rule inside the strategy**, not a declaration here: read
`call.evaluation_time`, keep what you need in `self.memory`, and return no decision on the sessions
you skip. Expressing it as a declaration would put a piece of the strategy's logic somewhere the
strategy's file does not show.

## No valuation or monitoring time

The book is valued at the instant the venue fills, and declared constraints judge it right after
each commit. There is nothing to schedule.

## One run, several strategies

Every strategy under `strategies:` runs with **its own account** from the run's
`initial_account` declaration, and writes **its own record**.

Three factor models on one cadence are one run with three strategies. Splitting them into three
runs gives three declarations to keep in step and no shared basis for comparing them — the
`run_report` correlation and the `relative` block both need the strategies to be in one run.

A strategy's entry may carry a `constraints:` list naming registered components of kind
`constraint`.

## What a datamodel run must not carry

A datamodel is a run too. Its declaration names `datamodels:` instead of `strategies:`, and
`account`, `venue` and `execution` are **refused** on it — there is nothing to execute.

## What a run needs registered before it

Three declaration kinds, each with its own `vqapr new` scaffold: datasets (the venue table a run fills against is a dataset with an `execution:` role, and the run picks its `trade_price`), an
exchange, and at least one component.

**And it wants a fifth: the instrument roster.** Not required — a run without one completes. But
every fill then records `kind: None`, cost by kind collapses into one `unknown` bucket, and on a
costed venue every name is charged as if it were the same thing. `vqapr run` states which roster it
read, or that it read none.

## Editing a run declaration

Refused in place (`run.registered`, 409), unlike every other kind. A run definition is the
provenance of a result, so:

```bash
vqapr rm run-definition <run-id>
vqapr register runs.yaml
```

Its records, if any, stay readable. `vqapr list runs` keeps showing a run whose definition was
withdrawn but whose records remain, as `status: orphaned`.
