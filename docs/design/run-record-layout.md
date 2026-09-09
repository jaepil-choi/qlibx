# Run record on-disk layout

A reviewable decision, written before the code, because it constrains Step 6's `store.root` and
because getting it wrong is expensive to undo once records exist on disk.

## The problem

`recorder_rows` lives in memory for the whole run (`flow/run_state.py:65`). A run that crashes
leaves nothing; a run that finishes leaves nothing a later process can read. That makes two things
impossible rather than merely inconvenient:

- **Parallel execution.** Five processes running five factors cannot each keep their results in
  their own memory and have anyone read all five afterwards.
- **`show run <id>`.** There is nothing to show. The only way to answer a question about a finished
  run is to run it again.

## The layout

```
<store.root>/runs/
  <run-id>/
    record.json            the run's own facts: account, contract report, source digest, period
    tables/
      vqapr.account/       one directory per recorded table, one parquet file per table,
        all.parquet        written when the run ends (record `164`; one file per chunk, `146`)
      vqapr.weight/
      vqapr.monitoring/    when the run declared constraints: one row per rule per occurrence
      factor.membership/
```

One directory per run id. One directory per table. One complete file per table when the run
ends; spill parts (`000000.parquet`, ...) only while a very large run is still executing.

## Why a directory scan, not an index file

The obvious design is `runs/index.json` listing every run. It is wrong here, and the reason is the
same one `WORKSPACE_LOCK_FILENAME` exists for.

`workspace.py:53-55` documents the failure precisely: atomic replacement stops a reader seeing half
a file, but it does not stop two processes each reading the state, each adding their own entry, and
the second write erasing the first. Nothing fails. An entry is simply gone.

An index file puts all five concurrent writers on exactly that target. Every run would have to take
the workspace lock to record its own existence, serialising the one thing AC-R4 asks to be
parallel. A directory scan has no shared mutable target at all: each run creates its own directory
and writes only inside it, so `list runs` is `iterdir()` and two runs cannot collide by
construction.

The cost is that listing is O(runs) rather than O(1). At the scale this serves — one directory per
research run — that is not a cost worth buying a lost-update bug to avoid.

## Why the writer takes chunks and writes once (record `164`; per chunk before it)

`append` takes a chunk at a time -- one accepted occurrence's rows -- types it into an Arrow
table on the spot, and holds it. Nothing reaches the disk per chunk. When the run ends the
writer writes each table as one file, `all.parquet`; a run that ends by raising or by an
interrupt ends the same way, because `flow/orchestration.py` calls the writer's `release` on the
failure path and `release` writes before it unlocks. Only a hard kill -- `terminate`, an OOM
kill, a power cut -- runs no code, and then what survives is what the spill valve had already
written: above `SPILL_BYTES` (256 MB of buffered Arrow) the buffer is written as one spill part
per table, and the end folds every part and the remainder into the compact file.

**Why not per chunk.** Record `135` streamed so that a killed run kept every chunk that landed,
and record `146` made each chunk a complete parquet file because parquet is readable only once
its footer is written. Measured (`docs/issues/archive/087`): 1.5 ms of file cost per append before any
row conversion, a physical write per occurrence per table, about a fifth of a real strategy's
wall clock, and a finished table of six hundred 8 KB files whose framing outweighed their data a
hundredfold. The owner ruled (2026-09-07) that a run should not write per loop, that what it
recorded should be saved when it dies, and accepted that no code can answer a hard kill. The
sample journey went from 7.8 s and 1,465 files to 5.4 s and 3.

**The product streams into memory (record `135`, kept).** `RunStateRepository` hands each
accepted occurrence's rows to the writer at the swap that accepts it, and no root retains them;
the writer's columnar buffer is a fraction of the rows as Python objects (measured in
`tests/flow/test_the_run_record_streams.py`). `freeze_strategy_record` writes the record at the
end, after the tables, from counts the writer kept as chunks passed. A flow assembled without a
store keeps rows in its roots as before.

**Watching a run.** With no parts to count, a running member says how far it got in
`progress.json` -- accepted occurrences, rows per table, the last `event_time` -- rewritten by
the heartbeat at most every `PROGRESS_EVERY` seconds and removed when the tables land.
`member_progress` reads it; `vqapr list strategies --run` shows it.

## Why parquet (record `146`; JSONL before it)

The rows were JSONL from record `135` to record `146`: append-only, one row per line, and a
`.types.json` sidecar beside each table saying which Python type every column had been
stringified from, because JSON cannot carry a type and a reader that guessed from the text
shifted every instant by its offset -- the testbed's A5. That was a hand-written type system on
top of a format that has none, and the deletion campaign (D3: do not reinvent the wheel)
replaced it with the format that carries types: parquet, through pyarrow, which the tree already
depended on.

**One complete file per table, written when the run ends** (record `164`; one per chunk from
`146` to `164`, see the section above). `tables/<table>/all.parquet`, staged beside the target
and moved into place. Spill parts `tables/<table>/<n>.parquet` exist only while a large run is
still executing, or after a hard kill; the end writes the compact file first and removes the
parts after, and a reader (`record._table_files`) takes the compact file alone when it is there,
so a crash between the two repeats nothing. duckdb reads the directory as
`read_parquet('tables/<table>/*.parquet')`; inside that one window it would see both.

**Types travel in the file.** An instant is a `timestamp[us, tz]` in the zone the first value
carried, and comes back as that instant in that zone through pyarrow and through duckdb alike.
A `Decimal` is the one value stored as text -- exact and unbounded, where a parquet decimal
would need a fixed scale and a weight of one third has twenty-eight places -- and the column's
field metadata (`vqapr.type: decimal`) says so, so `read_table` (exported as
`vqapr.public.read_strategy_table`) restores it and a reader outside the package casts it
knowingly. A column's type is fixed the first time a non-null value is seen and every later
chunk is cast to it; a column seen under two kinds is refused at the write rather than
downgraded, because the recorder wrote both and the run's own table is what is wrong.

**One clock (issue `058`).** Every table's `event_time` is stamped in the strategy agenda's
zone, the fill table included; the execution table normalises its target to UTC and the fill
row used to carry that, so one run recorded two clocks.

The published *dataset* a run produces is also parquet -- that is `store.tables`, a different
artifact with a different reader.

## What `record.json` holds

AC-R3 names five things, and they are the five a later reader cannot reconstruct:

- **account** — the committed final snapshot.
- **tables** — row counts and formation counts per table, so `show run` answers without reading
  every row.
- **contract report** — `held`/`checked` per declaration (AC-R6).
- **source digest** — including the import closure, so two runs that claim the same code can be
  compared.
- **derived period** — what the run actually covered, which is not always what was declared.

## Two records (record `139`)

```
<store.root>/runs/
  <run-id>/
    run.json                       configuration: what every strategy shared, written FIRST
    strategies/
      <strategy-id>@<fp8>/
        strategy.json              one strategy's facts, written LAST -- the completion mark
        .running                   that strategy's liveness lock while it writes
        tables/<table>/<n>.parquet its rows, one complete file per chunk
```

A run holds several strategies (design §4), so the unit of writing -- and of the lock, the
crash survival and the `--force` replacement argued above -- is the strategy directory. The
run directory holds `run.json`, which every process running a strategy of that run writes
identically before it starts; two writers writing the same bytes need no lock, and a run whose
configuration changed under an old id is refused naming both digests. Nothing above changes:
no index file, chunked appends, parquet chunks carrying their types. `record.json` remains the
shape of a run written before `139`, and is still read.

The directory name `<strategy-id>@<fp8>` is the first eight hex characters of the strategy's
registered fingerprint, which folds the file bytes and the config: a tweak is a new directory
beside the old one, and counting them is architecture §17.4's answer.

## A datamodel run's records (record `148`)

```
<store.root>/runs/
  <run-id>/
    run.json                       configuration, as above; `datamodels` lists the members
    datamodels/
      <datamodel-id>@<fp8>/
        datamodel.json             one datamodel's facts, written LAST -- the completion mark
        .running                   its liveness lock while it computes
<project>/.vqapr/materialized/
  <dataset-id>/
    all.parquet                    every session, written once when the run registers (record `164`)
```

A datamodel run holds datamodels the way a strategy run holds strategies (design §4; a run holds
one kind, never both). The member directory is the same unit of writing, lock and `--force`
replacement; what differs is where the rows go. A datamodel's rows ARE a dataset -- the one its
run declared under `datamodels.<id>.dataset_id` -- so they land under `.vqapr/materialized/`,
as one parquet file once the last session has completed (`164`; a file per session before it),
and the directory registers as the dataset's source right after, through the registration path
every other dataset takes. There are no `tables/` under a datamodel's record directory, and
`datamodel.json` carries one line per session (evaluation time, output `available_at`, row
count) rather than the per-instrument lineage `docs/issues/archive/059` measured at 478 MB. A run that
fails first leaves no output and no registration; a re-run starts the directory clean.

`materialize()`, the spec file it read and the `materialization` record kind are gone: a
datamodel is a registered run, judged, frozen and executed by the same verbs.

## What this constrains in Step 6

`store.root` becomes the parent of `runs/`. That is the whole coupling, and it is why this document
exists before Step 6 rather than during it: a layout chosen inside the `store.root` change would be
chosen to fit that change rather than to survive concurrent writers.
