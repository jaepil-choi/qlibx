# Reading a record directly

## Two records, two questions

**`vqapr show run <run-id>`** — the **configuration** every strategy of the run shared:
instruments, period, venue, the execution dataset and this run's fill on it, the initial account, the
datasets read and their source digests, and `recorded`, the strategy records the store holds as
`<strategy-id>@<fp8>`.

**`vqapr show strategy <run-id>/<strategy-id>@<fp8>`** — one strategy's **output**: the component
that ran (path, and its fingerprint both as registered and as loaded), the run's compliance rules, the final
account, the contract report, the roster it read, and per-table row counts.

`<run-id>/<strategy-id>` without the fingerprint works when exactly one record of that strategy
exists. `vqapr list strategies --run <run-id>` lists them all, filterable by `--strategy`,
`--fingerprint`, `--failed-contract`, `--since`.

Both read what the run froze to disk, so they answer from any process. **Nothing is recomputed** —
re-running to answer a question about a run would be a different run.

## Rows

```bash
vqapr show strategy <run-id>/<ref> --table vqapr.fill --limit 1000
vqapr show strategy <run-id>/<ref> --table vqapr.account --instrument _ACCOUNT
```

`--limit N` returns at most N rows; `0` returns none. The envelope reports `rows_total`, `matched`
and `returned` **separately**, so a truncated page never reads as a short run. Quote the right
one, and to read a whole table ask for `rows_total` rows.

## From Python

```python
from vqapr.public import read_strategy_table

rows = read_strategy_table(store_root, run_id, "vqapr.fill", strategy_ref)
```

`store_root` is the path the run's result printed under that name — `<project>/.vqapr` unless
`--store-root` moved it — and **not** the project directory. That is the usual mistake.

`strategy_ref` is the `record` the result printed (`<strategy-id>@<fp8>`), or the bare
`<strategy-id>` when one record of it exists, or omitted when the run holds one strategy.

A root, run id or ref that names no record is refused (`RunRecordMissing`) naming what was found
instead — **so an empty frame means an empty table and nothing else.**

`read_strategy_table` decodes by the column types the writer recorded beside the table, so `nav`
comes back a `Decimal` and `observed_at` an aware `datetime`.

## Reading the parquet yourself

The rows are parquet, one directory per table and one file in it:

```
.vqapr/runs/<run-id>/strategies/<strategy-id>@<fp8>/tables/<table>/all.parquet
```

`duckdb.read_parquet` on that directory reads them. An instant is a `TIMESTAMPTZ` and comes back as
the same instant; a `Decimal` is **exact text** with `vqapr.type: decimal` in the column metadata,
which `read_strategy_table` restores and which you cast yourself anywhere else.

## `vqapr show dataset`

```bash
vqapr show dataset <id> [--limit N]
```

Works for any registered dataset, not only a materialized one. It reports the registration's own
facts — source, path, declared fields, span — alongside the rows, and reports `rows_total`
separately from `returned`. `--limit 0` returns the facts and no rows, whatever the file's size.
