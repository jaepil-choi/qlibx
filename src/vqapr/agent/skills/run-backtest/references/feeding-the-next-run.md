# One run's decisions as the next run's input

A strategy's record streams every table it writes — `vqapr.weight`, `vqapr.account`, `vqapr.fill`,
`vqapr.monitoring`, and any table the strategy declared with `tables()` — as a parquet directory:

```
.vqapr/runs/<run-id>/strategies/<strategy-id>@<fp8>/tables/<table>/
```

That directory registers like any other source. So a member run can feed an ensemble with **no
publishing step in between**.

```yaml
datasets:
  reversal_allocation:
    source_id: reversal-weights
    path: .vqapr/runs/reversal/strategies/reversal@1a2b3c4d/tables/vqapr.weight
    instrument_field: instrument
    available_at: event_time        # the decision instant the row was written at
    grain: instrument_instant
    key_fields: [event_time, instrument]
    fields:
      weight: "CAST(weight AS DOUBLE)"   # a record stores Decimals as text
    field_types:
      weight: DOUBLE
```

## The three things to get right

**The fingerprint.** `vqapr list strategies --run <run-id>` gives the `<strategy-id>@<fp8>`. It is
part of the path, and it is what pins the registration to the exact code that produced the rows.

**`available_at: event_time`** for every package table. A valuation writes `observed_at` and
`event_time` at the same instant, so either would do numerically — but `event_time` is the one
every table has, and mixing the two across registrations makes two datasets that read as the same
thing and are not.

**The `CAST`.** A `Decimal` column is stored as text with `vqapr.type: decimal` metadata, so a
numeric field must be cast in the registration — to `DOUBLE`, the one non-integer numeric type a
dataset may declare. A weight on the optimiser's `1e-12` grid is at most twelve significant digits
and a float64 carries fifteen, so nothing is lost here; that is a fact about this column, not a
general licence to cast a Decimal to a float.

## Provenance

The run's own `run.json` carries the sha256 of every source it read. When a later reader asks what
went into the ensemble, that is the answer — and it is why registering the directory rather than
copying rows out of it matters.
