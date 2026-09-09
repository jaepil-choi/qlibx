# A DataModel is a run

Not a script and not a build step. It is declared, registered, checked and executed exactly like a
strategy run.

```yaml
runs:
  my-derived-run:
    instruments: [A005930, A000660]  # the universe every session computes over
    start: "2024-01-02T00:00:00+09:00"
    end:   "2024-12-31T23:00:00+09:00"
    sessions_from: prices            # every session that registered dataset has (or `sessions:`)
    timezone: Asia/Seoul
    at: "16:00"                      # when compute() is called, each session
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

Running the same run again is refused while its output dataset is registered
(`datamodel.output_registered`, 409).

```bash
vqapr rm dataset <id>
```

withdraws the registration **and deletes the files** under `.vqapr/materialized/<id>/`. That is the
way to retry a datamodel run, or to drop a throw-away output.

It refuses while a registered run takes its sessions from that dataset (`sessions_from`), naming
the run — so a dataset that other runs are pinned to cannot be removed out from under them.

A dataset registered from the user's **own path** is withdrawn without touching their file. Only a
materialized one has files vqapr may delete.

## Counting runs

Records, not directories. `vqapr list datamodels --run <run-id>` with `status: completed` is how
many times it ran to completion; a killed run leaves a directory with rows and no record, shown as
`status: unfinished`, which `vqapr rm datamodel <run-id>/<ref>` removes.
