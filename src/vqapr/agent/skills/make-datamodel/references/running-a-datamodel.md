# A DataModel is a run

Not a script and not a build step. It is declared, registered, checked and executed exactly like a
strategy run.

```yaml
runs:
  my-derived-run:
    instruments: [A005930, A000660]  # the universe every session computes over
    start: "2024-01-02T00:00:00+09:00"
    end:   "2024-12-31T23:00:00+09:00"
    timezone: Asia/Seoul
    agenda:
      every: 1d                      # the strategy clock (design §3.4); `1w`, `1M` also pick days
      at: "16:00"                    # when compute() is called on each selected day
      days_from: prices              # the dataset whose days are the trading days (no venue here)
    writes: my-derived-values        # the dataset it makes; must NOT already be registered
    datamodel:
      component: my-derived          # the registered DataModel component
      value_fields: [value]          # the columns each row carries beside `instrument`
```

`vqapr new datamodel <id> --dataset <d>` emits this block beside the component.

```bash
vqapr register <file.yaml>
vqapr check <run-id>
vqapr run <run-id>
```

A YAML path handed to `run` or `check` is refused by name — both take a registered id.

## What is refused on a datamodel run

`account`, `venue` and `execution`. There is nothing to execute, so those keys are not
merely unnecessary — declaring them is an error, and the refusal says so.

## Where the output lands

The sessions' rows are held and written as **one parquet file** under
`.vqapr/materialized/<dataset_id>/` when the last session completes. The dataset registers right
after.

The run's record lands at
`.vqapr/runs/<run-id>/datamodels/<id>@<fp8>/datamodel.json` — one line per session (evaluation
time, output `available_at`, row count). **No per-instrument lineage**: if you need to know why a
particular name got a particular value, that is a diagnostic table the model records, not something
this record holds.

## Reading it back

```bash
vqapr list datasets                          # the output arrived
vqapr list datamodels --run <run-id>         # the records
vqapr show datamodel <run-id>/<id>@<fp8>     # one record
vqapr show dataset <id>                      # what it computed
```

## Retrying

**The retry is `--force`.** Running the same run again is refused twice over, and one flag answers
both refusals:

- while its output dataset is still registered — `run.output_registered`, **409**;
- once the dataset is gone but the record of the same fingerprint still stands —
  `record.exists`, **409** (the component file is unchanged, so the fingerprint is the same,
  and a record is written once per run and fingerprint).

```bash
vqapr run <run-id> --force
```

replaces the standing record **and** withdraws and rewrites the dataset it published, in one
command. Editing the component instead (a new fingerprint) records beside the old one and needs no
flag, but the dataset still has to be withdrawn or `--force`d.

`vqapr rm dataset <id>` is **not** the retry. It withdraws the registration and deletes the files
under `.vqapr/materialized/<id>/` — the way to drop a throw-away output — and leaves the record
standing, so an unchanged component is then refused with `record.exists` and the alpha has no
dataset at all in between. In a tuning loop that gap is where a restored file and a stale parquet
part ways (see `vqapr check`'s `run.output_stale`).

`rm dataset` refuses while a registered run takes its trading days from that dataset
(`agenda.days_from`), naming the run — so a dataset that other runs are pinned to cannot be removed
out from under them.

A dataset registered from the user's **own path** is withdrawn without touching their file. Only a
materialized one has files vqapr may delete.

## Counting runs

Records, not directories. `vqapr list datamodels --run <run-id>` with `status: completed` is how
many times it ran to completion; a killed run leaves a directory with rows and no record, shown as
`status: unfinished`, which `vqapr rm datamodel <run-id>/<ref>` removes.

Several records, one dataset: each version wrote the same dataset id in turn, and exactly one
parquet exists. **The dataset says which**: `vqapr show dataset <id>` carries `produced_by_record`,
the `<id>@<fp8>` of the record that wrote it. Existence of the directory is not identity of its
contents — after restoring a file to an earlier version, compare `produced_by_record` with the
component's current fingerprint, or let `vqapr check <run-id>` do it (`run.output_stale`, 412,
fix: `vqapr run <run-id> --force`).
