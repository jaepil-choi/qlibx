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
      vqapr.account/       one directory per recorded table, one parquet file per chunk
        000000.parquet     as the run proceeds (record `146`)
        000001.parquet
      vqapr.weight/
      vqapr.monitoring/    when the run declared constraints: one row per rule per occurrence
      factor.membership/
```

One directory per run id. One directory per table. One complete file per chunk as it arrives.

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

## Why the writer appends in chunks

`append` takes a chunk at a time and never rewrites what it already wrote, so a caller that streams
rows as it produces them gets crash survival and bounded memory for free: a killed run keeps
everything up to its last chunk, and peak memory is one chunk rather than a whole run.

**The product streams (record `135`).** `RunStateRepository` hands each accepted occurrence's
rows to the writer at the swap that accepts it, and no root retains them; `freeze_record` writes
only `record.json` at the end, from counts the writer kept as chunks passed. A killed run keeps
every accepted occurrence's rows and no record, and a streamed run's peak heap is a fraction of
the same run kept in memory -- both measured in `tests/flow/test_the_run_record_streams.py`. A
flow assembled without a store keeps rows in its roots as before.

## Why parquet, one file per chunk (record `146`; JSONL before it)

The rows were JSONL from record `135` to record `146`: append-only, one row per line, and a
`.types.json` sidecar beside each table saying which Python type every column had been
stringified from, because JSON cannot carry a type and a reader that guessed from the text
shifted every instant by its offset -- the testbed's A5. That was a hand-written type system on
top of a format that has none, and the deletion campaign (D3: do not reinvent the wheel)
replaced it with the format that carries types: parquet, through pyarrow, which the tree already
depended on.

**One complete file per chunk, not one open writer per table.** A parquet file is readable
only once its footer is written, so a writer held open for the run would leave nothing if the
run were killed -- and a killed run leaving every chunk that landed is the property the whole
layout exists for. So each `append` writes one file, `tables/<table>/<n>.parquet`, staged beside
the target and moved into place; a chunk is one accepted occurrence's rows, so the files number
the run's occurrences. A reader lists the directory in order; duckdb reads it as
`read_parquet('tables/<table>/*.parquet')`.

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
materialization record and the shape of a run written before `139`; both are still read.

The directory name `<strategy-id>@<fp8>` is the first eight hex characters of the strategy's
registered fingerprint, which folds the file bytes and the config: a tweak is a new directory
beside the old one, and counting them is architecture §17.4's answer.

## What this constrains in Step 6

`store.root` becomes the parent of `runs/`. That is the whole coupling, and it is why this document
exists before Step 6 rather than during it: a layout chosen inside the `store.root` change would be
chosen to fit that change rather than to survive concurrent writers.
