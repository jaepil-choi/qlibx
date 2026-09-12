# 091 — A materialized dataset does not record which component fingerprint produced it

**Status: CLOSED 2026-09-10 -- record `217`.** Owner ruling: add a field rather than change
`produced_by` (three sites compare it to the run id). A dataset a run writes carries
`produced_by_record` -- `<component_id>@<fp8>` -- in `show dataset` and `list datasets`, stamped by
`RunOutput.register` for both kinds; `vqapr check <run-id>` reports `run.output_stale` (412) when
that ref differs from the component registered now, fix `vqapr run <id> --force`. `run` does not
raise it (without `--force` it refuses the standing output anyway; `--force` is the repair). The
reporter's third option -- `run` refusing a differing fingerprint -- was already 0.10.0's
`run.output_registered`; the hazard was in not running, which only a visible field could catch.

Filed as `report-2026-09-09-a-materialized-dataset-does-not-record-its-producing-fingerprint.md`;
numbered on triage.

| | |
|---|---|
| vqapr version | `0.9.0.dev1` |
| installed from | `../../vqapr/dist/vqapr-0.9.0.dev1-py3-none-any.whl` |
| reported | 2026-09-09 |
| reporter | `kwam-enhanced-index/vqapr-enhanced-index-3`, agent session |
| python / OS | 3.12 / Windows 11 |

## What I was doing

Tuning ~190 alpha DataModels by sweeping one module-level constant per alpha. A sweep tries several
values — each a new component fingerprint, each writing the same output dataset id after the
previous one is withdrawn — then restores the file to whichever value measured best in sample and
keeps that alpha's dataset for a later cross-alpha correlation comparison.

This is the workflow `make-datamodel`'s "Counting runs" section describes: records accumulate per
fingerprint under one run id, which is what makes a tuning history readable afterwards.

## What I expected

That I could ask a materialized dataset which version of the component wrote it, so that "the file
on disk" and "the parquet under `.vqapr/materialized/`" can be checked for agreement.
`show dataset` returns `produced_by`, which I expected to identify the producing **record**
(`<id>@<fp8>`) — that is how `list datamodels`, `show datamodel` and `rm datamodel` all address a
datamodel's output, and it is the only identifier that distinguishes two versions of one component.

## What happened

`produced_by` names only the run id, and no other field in the response carries a fingerprint or a
version:

    $ uv run --no-sync vqapr show dataset alpha-resmom-003-values --limit 0
    top-level keys: aggregated, available_at, dataset_id, field_types, fields, grain,
                    instrument_field, items, ok, path, produced_by, returned, rows_total,
                    source_id, span, stage, workspace_root

      dataset_id   alpha-resmom-003-values
      produced_by  alpha-resmom-003
      source_id    materialized-alpha-resmom-003-values
      span         ['2020-10-30 16:00:00+09:00', '2026-07-28 16:00:00+09:00']
      rows_total   11621
      path         ...\.vqapr\materialized\alpha-resmom-003-values

    fields matching /finger|version|record/ in the response: NONE

Meanwhile `vqapr list datamodels --run alpha-resmom-003` lists several completed records, one per
version tried, each with a distinct `fingerprint` and each claiming `dataset_id:
alpha-resmom-003-values`. So the records say N versions wrote this dataset id, exactly one parquet
exists, and the dataset says nothing about which of the N it holds.

## Reproduction

Reproduced every time (8 of 8 alphas swept):

1. Register a datamodel component; `vqapr run <run-id>`.
2. Edit a constant in the component file; `vqapr rm dataset <out>`; `vqapr run <run-id>` again.
3. Restore the file to its original contents.
4. `vqapr show dataset <out>` — nothing in the response distinguishes which of the two versions
   the parquet holds, and `list datamodels --run <run-id>` shows both records pointing at it.

## Impact

Worked around, but only after it had silently produced wrong numbers that looked entirely
plausible.

My sweep restored each alpha's file to its best-measured version and, because the dataset
directory still existed, did not re-run it. The parquet therefore held the **last value tried**,
not the restored one. Five of eight pooled alphas were in that state. Everything downstream stayed
sane-looking: my ledger reported the best version's Sharpe while the correlation gate that decides
pool membership compared a different version's scores. Re-measuring each pool member from the file
actually on disk:

    alpha           ledger Sharpe   on-disk Sharpe
    resmom_003          1.1459          0.7866
    value_001           0.9996          0.9291
    value_008           0.9842          0.7534
    revision_007        0.9133          0.8295
    peer_009            0.8244          0.1745

`peer_009` is the one that shows the size of the hazard: 0.82 versus 0.17 for the same declared
alpha id, with no error anywhere and no field a caller could have consulted to notice.

I found it only because I wrote an ad-hoc check that re-measured every pool member and compared
against my own ledger. Nothing in vqapr flagged it, and nothing in vqapr could have, because the
dataset does not claim a version. The workaround is to re-run unconditionally before trusting any
materialized output — existence of the directory is not identity of its contents.

## What would have prevented it

`produced_by` carrying the record ref (`alpha-resmom-003@1eee8a70`) rather than the bare run id, so
a caller can compare it against the component's current fingerprint before trusting the parquet.
Failing that, any field on the dataset naming the fingerprint that wrote it — or a refusal from
`run` when a dataset exists whose producing fingerprint differs from the one about to execute.
