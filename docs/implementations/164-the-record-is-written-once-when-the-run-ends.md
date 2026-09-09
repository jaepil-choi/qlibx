# 164 — the record is written once, when the run ends: no physical write per loop

**Closes:** `docs/issues/archive/087`. **Branch:** `fix/087-write-once-flush-on-exit`, off
`develop @ 22f3e271` (after record `163`). **Campaign:** none. **Authority:** the owner,
2026-09-07, two rulings: first "compact on `release()`", then -- on asking why a run had to write
per loop at all -- "write once at the end, and save what was recorded when the run dies",
accepting that a hard kill cannot be answered by code. **Design:**
`docs/design/run-record-layout.md`, the two rewritten sections.

## Why this exists

Record `146` wrote one complete parquet file per accepted occurrence per table, so that a killed
run kept every chunk that landed (record `135`'s promise; parquet is readable only once its
footer is written). Measured for `087`: 1.5 ms of file cost per append before any row
conversion, 8.8 ms for a 201-row account chunk; on `ensemble-k200`'s strategy about 14 s of a
79 s wall clock had no named phase and matched the recording; a finished 607-session table was
607 files of 8 KB whose framing outweighed their data a hundredfold, and one run held 19,452
files. The owner's question -- why write per loop -- had no answer that survived the numbers.

## What changed

- **`flow/record.py`, `RunRecordWriter`.** `append` types the chunk into an Arrow table at once
  (a column of two kinds is still refused at the occurrence that wrote it, by name) and holds
  it in a `_Buffer`; nothing reaches the disk. `release()` now seals -- every table as
  `tables/<table>/all.parquet`, folding any spill parts in first -- and then unlocks; `finish()`
  seals before writing the record, so a record on disk means every row is beside it. A seal
  that cannot write raises, on the failure path too, chained on the failure that ended the run.
  `spill_bytes` (default `SPILL_BYTES`, 256 MB) is the safety valve: above it the buffer is
  written as one spill part per table. `heartbeat()` still touches the lock and now rewrites
  `progress.json` every `PROGRESS_EVERY` (5 s); `checkpoint()` writes it now.
- **Readers.** `_table_files` (behind `_parts`, `table_types`, `table_ids`, `member_progress`)
  takes `all.parquet` alone when it exists, else the numbered spill parts -- so a crash between
  the compact write and the parts' removal repeats nothing. `member_progress` reads
  `progress.json` and falls back to files; `chunks` keeps its name and now means accepted
  occurrences.
- **`flow/datamodel.py`, `DataModelOutput`.** The same shape: sessions buffered as Arrow,
  spill above the valve, `_seal()` into `all.parquet` at `register()` -- and only there, since a
  dataset that failed to register has nothing readable to leave. `COMPACT_FILENAME` and
  `SPILL_BYTES` live here (record imports datamodel, not the reverse).
- **`flow/orchestration.py`: no change.** Its failure path already called `writer.release()`;
  that call is what saves an interrupted run's rows now.
- **Docs.** `run-record-layout.md` (the chunk section rewritten, the parquet section retitled,
  the datamodel layout); `SKILL.md` (four passages: one file per table, what an interrupt and a
  hard kill leave, `chunks` and `last_event_time` from a progress file); the `PART_SUFFIX`,
  `MATERIALIZED_DIRECTORY` and module docstrings.

## The promise, restated

A run that ends -- normally, by an exception, by Ctrl+C -- leaves every row it recorded, as one
file per table, and a record only when it finished. A run that is hard-killed leaves the spill
parts written before the kill and nothing after; `list strategies --run` shows it `unfinished`
with the progress it last reported. Record `135`'s "a killed run keeps everything up to its last
chunk" is narrowed to that, by the owner's ruling, in exchange for zero physical writes per loop.

## Validation

- `tests/flow/test_the_record_reads_back_typed.py`: nothing on disk before `release`, one file
  after; a spill (`spill_bytes=1`) lands parts that the end folds into one file, in order, with a
  null-first column typed by its first value; a compact file beside leftover parts is read alone.
- `tests/flow/test_the_run_record_streams.py`: the roots keep no rows, the disk sees nothing
  during the run, the table lands at `release`; the heap ratio still holds.
- `tests/qa/test_run_records_survive_and_race.py`: a separate process INTERRUPTED (CTRL_BREAK on
  Windows, SIGTERM elsewhere, after it holds its lock) leaves every row and no record; one
  hard-KILLED with the valve at 1 byte keeps only its spill parts, no compact file, no record.
- `tests/flow/test_a_datamodel_is_a_run.py`: both sessions see an empty output directory, the
  finished dataset is one `all.parquet`, a compute failure leaves no output, `--jobs` workers
  each leave one file. `tests/cli/test_list_shows_a_strategy_still_being_written.py`:
  `chunks`/`last_event_time` from `progress.json` (`checkpoint()`).
- Measured: the sample journey 7.8 s → 5.4 s, 1,465 parquet files / 9.6 MB → 3 files / 120 KB.
- Fast suite on the branch: **1,416 passed, 4 skipped** (878 s); slow set **23 passed** (562 s).
