# Records, tweaks, and removing things

## A tweak is a record, not a directory

A strategy's record is named by its registered fingerprint, which folds the file bytes and the
config. Edit the strategy, re-register it under the same id, run again — and the new record lands
**beside** the old one.

**Count records, not directories.** The rows `vqapr list strategies --run <run-id>` reports with
`status: completed` are how many times it was tweaked. Counting directories over-counts by the
crashes: a run killed or refused inside a callback leaves a directory with rows and no record,
which `list` shows as `status: unfinished`.

Same for `vqapr list datamodels --run <run-id>`.

## Running the same fingerprint again

Refused, unless `--force` replaces that one record. Unchanged bytes plus unchanged config is the
same run, and letting it silently write a second identical record would make the tweak count
meaningless.

## Removing

| verb | removes |
|---|---|
| `vqapr rm strategy <run-id>/<id>@<fp8>` | one strategy record |
| `vqapr rm datamodel <run-id>/<id>@<fp8>` | one datamodel record |
| `vqapr rm run <run-id> [--keep-latest]` | a run's records |
| `vqapr rm run-definition <run-id>` | the registered declaration, leaving records |
| `vqapr rm dataset <id>` | a registration, and the files under `.vqapr/materialized/<id>/` |

All of them refuse while a writer may still hold the record.

`rm run-definition` reports the records it left and names the verb that removes them.

## Removing a run entirely

```bash
vqapr rm run <run-id> --cascade
```

One gesture: the run's records, its registered definition, the materialized datasets its
datamodels wrote, and the components it named — **keeping, and naming as `kept`, any dataset or
component another registered run still names**.

The single-kind verbs above still exist for the step-by-step case. Use them when the user wants to
see each removal, and `--cascade` when they want the run gone.

`--cascade` is destructive and crosses several kinds. Show the user what it will take before
running it, and let them say yes.

## Retrying a datamodel run

Running one again is refused while its output dataset is registered (`run.output_registered`,
409), and — once the dataset is withdrawn — while a record of the same fingerprint still stands
(`record.exists`, 409). **`vqapr run <run-id> --force` is the retry**: it replaces the record and
rewrites the dataset in one command. `vqapr rm dataset <id>` withdraws the registration and deletes
the materialized files, which is how a throw-away output is dropped, not how a run is retried — and
it refuses while a registered run takes its trading days from that dataset (`agenda.days_from`),
naming the run.

A dataset registered from the user's own path is withdrawn **without touching their file**.
