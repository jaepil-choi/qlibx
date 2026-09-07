# 087 — a finished run keeps one parquet file per occurrence, so a table is six hundred 8 KB files

**Status:** **CLOSED 2026-09-07 -- record `164`.** The writer holds each table as Arrow
batches and writes one `all.parquet` per table when the run ends -- normally, or on the failure
path (an exception, an interrupt) -- with a 256 MB spill valve for very large runs; the
datamodel's output does the same at registration. A hard kill keeps only what had spilled: the
owner accepted that narrowing of record `135`'s promise (2026-09-07, second ruling below), in
exchange for zero physical writes per loop. Sample journey: 7.8 s to 5.4 s, 1,465 files to 3.
Filed 2026-09-07 from two 0.4.1 workspaces (`kaist-thesis/vqapr-scenario-testbed`,
`kwam-enhanced-index/vqapr-enhanced-index-3`).

**Second ruling 2026-09-07, which replaced the first.** The first ruling below (compaction on
`release()`, keep writing a file per occurrence) left the write per loop in place -- measured at
1.5 ms of file cost per append plus the row conversion, roughly a fifth of a real strategy's wall
clock. The owner asked why a run had to write per loop at all, and ruled: write once at the end,
save what was recorded when the run dies -- and accepted that a hard kill cannot be answered by
any code, so it keeps only what the spill valve had written.

**First ruling 2026-09-07 (superseded):** fix on its own branch, after the reporting API --
compaction on `release()`, not a change to the chunk the flow hands the writer.

## What was observed

A strategy that ran 607 sessions holds 607 files in `tables/vqapr.account/`, 607 in
`tables/vqapr.weight/`, and 607 in each table it declared itself — including `daily`, which has
**one row per session**. Every file is ~8 KB, and for `daily` almost all of that is parquet
framing (schema, row-group index, footer), not data:

| table (ffn_k0, run `ff-arm`) | parts | total | per file |
|---|---|---|---|
| `vqapr.account` | 607 | 5.0 MB | 8 KB |
| `vqapr.weight` | 607 | 5.0 MB | 8 KB |
| `daily` (one row per session) | 607 | 5.0 MB | 8 KB |
| `vqapr.fill` | 1 | 3.3 MB | 3.3 MB |

The eight-strategy run is **19,452 parquet files, 155 MB**. The three-book ensemble run in the
other workspace is 6,921 files. A duckdb `read_parquet('*.parquet')` opens every footer, so read
time scales with the session count rather than the row count.

## Why it is this way

Record `146` (`docs/design/run-record-layout.md`, "Why parquet, one file per chunk"): a parquet
file is readable only once its footer is written, so a writer held open for the run would leave
nothing if the run were killed, and a killed run leaving every chunk that landed is the property
record `135` promised. `append` therefore writes one complete file per chunk — and the flow hands
the writer **one accepted occurrence** per chunk (`RunStateRepository`), so the files number the
occurrences. Both halves are deliberate; the cost they buy is the one above.

## What to do

**Compact on `release()`.** When a strategy finishes normally, merge each table's parts into one
file and remove the parts. A killed run never reaches `release()`, so it keeps its parts and
loses nothing; a finished run has one file per table. Readers already glob the directory
(`record._parts`) and union schemas by name, so no reader changes. The strategy record's
`tables` counts do not change.

Not chosen: batching N occurrences per chunk (loses the last batch on a kill; may still be added
on top later), and a per-strategy duckdb file (real append and WAL survival, but breaks "a run's
table is a parquet directory and registers as a dataset", Step 4 / record `159`).

**Test:** a run written through `RunRecordWriter` and released reads back the same rows with one
part per table; a writer that is never released keeps every part.
