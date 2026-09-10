# What a run declares

The template from `vqapr new run --out runs.yaml` carries every required key with its meaning, and
it is generated from the contract the package enforces. **Fill the template rather than
hand-writing the YAML** — this file explains the choices, not the key list.

## The strategy clock: `agenda`

A run declares **when it fires** as one block, a trading-day filter plus a within-day rule:

```yaml
    timezone: Asia/Seoul
    agenda:
      every: 1d          # <count><unit>; d, w, M pick trading days and pair with `at`
      at: "15:29"        #   one wall time or a list
    # agenda:
    #   every: 5m        # <count><unit>; m, h pick instants inside each day and pair with from/to
    #   from: "09:00"
    #   to: "15:20"
```

**The days are not declared.** They come from data: a strategy run's trading days are the days its
execution dataset has rows for, so a denser table adds fill instants and never a decision day. A
datamodel run has no venue and names the dataset whose days count with `agenda.days_from`. There
is no `sessions:` list to type and no calendar to register.

**`every` is a count and a unit, and the count is free.** The units are `d`, `w`, `M` for trading
days and `m`, `h` for instants inside a day; there is no year unit. `1w` fires on the first trading
day of each ISO week, `1M` on the first trading day of each calendar month, `2d` on every second
trading day, `3M` quarterly and `12M` once a year, counted from the run's `start` -- a run that
starts in June forms every June. A strategy called on a day it does not want to act still decides
for itself (`Hold`).

## No valuation or monitoring time

The book is valued at every instant of the market clock, and the run's declared Compliance rules
observe it right after. There is nothing to schedule.

## One run, one model, one `writes`

A run executes **one** model, named under `strategy:` (or `datamodel:`), and puts **one** dataset
in the project under `writes:`. `writes` is required: the project is a graph of datasets and a run
is one arrow of it, and an arrow that makes nothing is not a rule of the graph.

```yaml
runs:
  my-alpha:
    writes: my-alpha-weights       # the allocation, one row per instrument per decision
    strategy:
      component: my-alpha
    # compliance: [no-short]      # the rules that watch the book: the run's, beside the venue
```

Three factor models on one cadence are **three runs** with the same period, venue and account.
That is not three declarations to keep in step: two runs declaring the same inputs freeze
identically, so the comparison is exactly as sound as it was in one run — and now it holds across
runs made on different days, which one run never could. `--jobs` spreads runs, and a strategy that
wants another's allocation reads its `writes` like any other dataset.

`vqapr check` reads the graph: a run whose model reads a dataset that another registered run
`writes` is told to run that one first, rather than to register something.

## What a datamodel run must not carry

A datamodel is a run too. Its declaration names `datamodel:` instead of `strategy:`, and
`account`, `venue` and `execution` are **refused** on it — there is nothing to execute.

## What a run needs registered before it

Three declaration kinds, each with its own `vqapr new` scaffold: datasets (the venue table a run fills against is a dataset with an `execution:` role, and the run picks its `trade_price`), an
exchange, and at least one component.

**And a strategy run requires a fifth: the instrument roster.** The venue must know what every
ordered id *is* before it can size or charge it, so a project that has declared no instrument is
refused at `check` and at `run` (`roster.absent`, 412) — `vqapr new instruments <ids...>` writes the
tables and the declaration, `vqapr register instruments.yaml` registers them. The roster does not
have to cover the whole execution table: only what the strategy orders. An order for an id the
roster never described fails the run at the fill instant (`instrument.undeclared`), naming every
undeclared id at once. `vqapr run` states which roster it read.

## Editing a run declaration

Refused in place (`run.registered`, 409), unlike every other kind. A run definition is the
provenance of a result, so:

```bash
vqapr rm run-definition <run-id>
vqapr register runs.yaml
```

Its records, if any, stay readable. `vqapr list runs` keeps showing a run whose definition was
withdrawn but whose records remain, as `status: orphaned`.
