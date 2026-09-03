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
      vqapr.account.jsonl  one file per recorded table, appended in chunks as the run proceeds
      vqapr.weight.jsonl
      vqapr.monitoring.jsonl  when the run declared constraints: one row per rule per occurrence
      factor.membership.jsonl
```

One directory per run id. One file per table. Rows appended as chunks arrive.

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

## Why JSONL

Append-only, one row per line, no framing to rewrite. A parquet file would have to be rewritten or
partitioned per append; a JSON array would need its closing bracket moved. Both make an append a
read-modify-write, which is what this layout exists to avoid.

The published *dataset* a run produces is still parquet — that is Step 6's `store.tables`. This is
the run's own record, which is a different artifact with a different reader.

**Types travel beside the rows (record `135`).** JSON has no `Decimal` and no offset-aware
instant; the writer encodes both as strings, and a reader that guesses from the text shifts every
instant by its offset -- the testbed's A5. So the writer, which sees the Python types at the
moment it stringifies them, records them per table and per column in `tables/<id>.types.json`,
rewritten only when a column's type is first seen or changes. `read_typed_table` -- exported as
`vqapr.public.read_run_table` -- decodes by that sidecar; a table with no sidecar predates it and
reads back as strings. A column seen under two types is recorded as a string, because reading the
strings that were written is the one answer that loses nothing.

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
        tables/<table>.jsonl       its rows, plus <table>.types.json beside each
```

A run holds several strategies (design §4), so the unit of writing -- and of the lock, the
crash survival and the `--force` replacement argued above -- is the strategy directory. The
run directory holds `run.json`, which every process running a strategy of that run writes
identically before it starts; two writers writing the same bytes need no lock, and a run whose
configuration changed under an old id is refused naming both digests. Nothing above changes:
no index file, chunked appends, JSONL, types beside the rows. `record.json` remains the
materialization record and the shape of a run written before `139`; both are still read.

The directory name `<strategy-id>@<fp8>` is the first eight hex characters of the strategy's
registered fingerprint, which folds the file bytes and the config: a tweak is a new directory
beside the old one, and counting them is architecture §17.4's answer.

## What this constrains in Step 6

`store.root` becomes the parent of `runs/`. That is the whole coupling, and it is why this document
exists before Step 6 rather than during it: a layout chosen inside the `store.root` change would be
chosen to fit that change rather than to survive concurrent writers.
