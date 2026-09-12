# 093 — `show dataset` returns the source file's rows, not the projection the dataset declares

**Status: CLOSED 2026-09-10 -- record `219`.** Owner ruling: the reporter's first option. `items`
is the declared projection, read through the same `projection_relation` the read path uses;
`items_are` says `"projection"` or `"source"`; `rows_total` counts what `items` pages over and
`source_rows_total` is always the file's; `--source` asks for the file's rows. The cost the report
anticipated is real and is stated in `--help` and two skills: an aggregated registration's head
evaluates the whole grouping. `register-dataset` step 7 now confirms what it claims to.

Filed as `report-2026-09-09-show-dataset-returns-source-rows-not-the-declared-projection.md`;
numbered on triage.

| | |
|---|---|
| vqapr version | `0.9.0.dev1` |
| installed from | `../../vqapr/dist/vqapr-0.9.0.dev1-py3-none-any.whl` |
| reported | 2026-09-09 |
| reporter | `kwam-enhanced-index/vqapr-enhanced-index-3`, agent session |
| python / OS | 3.12 / Windows 11 |

## What I was doing

Registering 21 warehouse datasets for a KOSPI200 enhanced-index study. One of them,
`statement-facts-annual`, is the same parquet as `statement-facts` registered a second time as a
`grain: instrument_instant` panel whose ten fields are duckdb aggregate expressions
(`arg_max(numeric_value, dump_last_modified) FILTER (WHERE ... account_code = '4001110000')` and
similar) over a long EAV table whose physical columns are `account_code` and `numeric_value`.

The `register-dataset` skill's step 7, "Confirm, and record what the package could not check",
names this as the confirmation step for a registration:

```
vqapr list datasets
vqapr show dataset <id> --limit 20
```

## What I expected

That `show dataset` shows me the dataset — the fields I declared, holding the values a model
reading this dataset would receive. The skill names this command as the way to confirm a
registration, and the response's own `fields`, `field_types`, `grain` and `aggregated` keys all
describe the projection.

## What happened

`items` carries rows of the underlying **source file**, with the source's columns. Nine of the ten
declared fields do not appear at all, and nine columns that are not in the declaration do.

    $ uv run --no-sync vqapr show dataset statement-facts-annual --limit 2
    {"aggregated": true, "available_at": "available_at", "dataset_id": "statement-facts-annual", "field_types": {"amortization": "DOUBLE", "controlling_equity": "DOUBLE", "depreciation": "DOUBLE", "fiscal_yyyymm": "INTEGER", "interest_expense": "DOUBLE", "noncontrolling_interest": "DOUBLE", "operating_income": "DOUBLE", "total_assets": "DOUBLE", "total_equity": "DOUBLE", "total_liabilities": "DOUBLE"}, "fields": {"amortization": "coalesce(arg_max(numeric_value, dump_last_modified) FILTER (WHERE statement_scope = 'consolidated' AND settlement_type = 'D' AND account_code = '4001410600'), arg_max(numeric_value, dump_last_modified) FILTER (WHERE statement_scope = 'consolidated' AND settlement_type = 'D' AND account_code = '4001226300'))", "controlling_equity": "coalesce(arg_max(numeric_value, dump_last_modified) FILTER (WHERE statement_scope = 'consolidated' AND settlement_type = 'D' AND account_code = '4001160050'))", "depreciation": "coalesce(arg_max(numeric_value, dump_last_modified) FILTER (WHERE statement_scope = 'consolidated' AND settlement_type = 'D' AND account_code = '4001410500'))", "fiscal_yyyymm": "max(fiscal_yyyymm) FILTER (WHERE statement_scope = 'consolidated' AND settlement_type = 'D')", "interest_expense": "coalesce(arg_max(numeric_value, dump_last_modified) FILTER (WHERE statement_scope = 'consolidated' AND settlement_type = 'D' AND account_code = '4001250100'))", "noncontrolling_interest": "coalesce(arg_max(numeric_value, dump_last_modified) FILTER (WHERE statement_scope = 'consolidated' AND settlement_type = 'D' AND account_code = '4001167500'), arg_max(numeric_value, dump_last_modified) FILTER (WHERE statement_scope = 'consolidated' AND settlement_type = 'D' AND account_code = '4001550000'))", "operating_income": "coalesce(arg_max(numeric_value, dump_last_modified) FILTER (WHERE statement_scope = 'consolidated' AND settlement_type = 'D' AND account_code = '4001230000'))", "total_assets": "coalesce(arg_max(numeric_value, dump_last_modified) FILTER (WHERE statement_scope = 'consolidated' AND settlement_type = 'D' AND account_code = '4001110000'))", "total_equity": "coalesce(arg_max(numeric_value, dump_last_modified) FILTER (WHERE statement_scope = 'consolidated' AND settlement_type = 'D' AND account_code = '4001160000'), arg_max(numeric_value, dump_last_modified) FILTER (WHERE statement_scope = 'consolidated' AND settlement_type = 'D' AND account_code = '4001570000'))", "total_liabilities": "coalesce(arg_max(numeric_value, dump_last_modified) FILTER (WHERE statement_scope = 'consolidated' AND settlement_type = 'D' AND account_code = '4001140000'))"}, "grain": "instrument_instant", "instrument_field": "instrument", "items": [{"account_code": "4001225000", "available_at": "2017-06-30 15:30:00+09:00", "dump_last_modified": "2026-07-23 09:44:54+09:00", "dump_source_label": "income_statement consolidated facts", "fiscal_year": 2017, "fiscal_yyyymm": 201703, "instrument": "A004980", "numeric_value": 32138.0, "settlement_type": "A", "statement_scope": "consolidated"}, {"account_code": "4001226200", "available_at": "2017-06-30 15:30:00+09:00", "dump_last_modified": "2026-07-23 09:44:54+09:00", "dump_source_label": "income_statement consolidated facts", "fiscal_year": 2017, "fiscal_yyyymm": 201703, "instrument": "A004980", "numeric_value": 375393.0, "settlement_type": "A", "statement_scope": "consolidated"}], "ok": true, "path": "declarations\\..\\workspace\\prepared\\statement_facts.parquet", "produced_by": null, "returned": 2, "rows_total": 39307271, "source_id": "statement-facts-source", "span": ["2016-05-31 15:30:00+09:00", "2026-06-30 15:30:00+09:00"], "stage": "dataset.show", "workspace_root": "D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\vqapr-enhanced-index-3"}

Reading that response programmatically:

    declared fields                : amortization, controlling_equity, depreciation, fiscal_yyyymm,
                                     interest_expense, noncontrolling_interest, operating_income,
                                     total_assets, total_equity, total_liabilities
    keys present in items[0]       : account_code, available_at, dump_last_modified,
                                     dump_source_label, fiscal_year, fiscal_yyyymm, instrument,
                                     numeric_value, settlement_type, statement_scope
    declared but ABSENT from items : 9 of 10
    in items but NOT declared      : 9

Three things make this more than a cosmetic mismatch:

- `aggregated: true` is in the same response, so the response knows this dataset is a projection
  while its `items` are not one.
- `rows_total: 39307271` is the source's row count. The dataset's own grain is
  `instrument_instant`, one row per (available_at, instrument) — a different and much smaller
  number.
- Every declared field filters on `settlement_type = 'D'`. Both rows returned carry
  `settlement_type: "A"`, so `items` shows rows the projection explicitly excludes.

## Reproduction

Reproduced every time (4 of 4). It needs a dataset whose `fields` are expressions rather than
column names, which is any `aggregated` registration:

1. Register a long table twice — once at `grain: rows`, once at `grain: instrument_instant` whose
   `fields` are aggregate expressions over it.
2. `vqapr show dataset <the aggregated id> --limit 2`
3. Compare `items[0]` keys with `fields` keys.

The other 20 datasets in this workspace do not show it, because their projections happen to be
identity maps onto the file's columns. **The one dataset where the two differ is the one carrying
the entire reduction rule**, so the failure is invisible exactly where confirmation matters most.

## Impact

Worked around, and it cost considerably more than the confirmation step it broke.

There is no other public way to see what an aggregated dataset yields — `show dataset` is the only
read accessor outside a run — so when it returns source rows, nothing answers "did my expressions
do what I meant". I verified the reduction by running the declared expressions myself in duckdb
against the same parquet, outside vqapr, and checking one instrument against a published annual
report (A005930 at 2025-03-31: `fiscal_yyyymm=202412`, `total_assets=514,531,948` thousand KRW,
`operating_income=32,725,961` thousand KRW — both match the filing).

The larger cost was downstream. I wrote a small offline harness so that alpha authors could test
model code in parallel without taking the workspace lock, and it read the declared field names off
the parquet — which raises `ArrowInvalid: No match for FieldRef.Name(total_assets)` for this
dataset. One author lost four planned hypotheses to that before I taught the harness to evaluate
the expressions instead. Had `show dataset` shown the projection, the shape of the fix would have
been obvious in seconds rather than after a blocked agent reported it.

## What would have prevented it

Either apply the declared projection to the rows `items` carries (and report `rows_total` for the
projected grain), or — if returning the source head is deliberate, for cost reasons on a 39M-row
file — say so in the response and in `--help`, e.g. an `items_are: "source_rows"` key, so a reader
knows the confirmation they just performed did not confirm the projection.
