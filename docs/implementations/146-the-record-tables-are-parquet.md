# 146 — the record's tables are parquet, one complete file per chunk

**Closes:** `docs/issues/058` (one run recorded two clocks). **Step:** 5 of
`docs/refactoring/2026-09-03-the-deletion-campaign.md` (decision D3, the second half: a record
that carries its types is parquet, not JSONL with a hand-written type sidecar).
**Authority:** `docs/design/run-record-layout.md` (updated with this record); record `135` (the
record streams and a killed run leaves its rows), whose two properties this keeps; the
diagnosis's §3.3 (*"parquet으로 내면 tz가 스키마에 실려 함정이 사라진다"*), which record `135`
had chosen not to take.

## Why this exists

Record `135` made the record stream and answered the testbed's A5 -- a reader guessing types
from JSONL text shifted every instant by nine hours and the panel built from it registered
cleanly -- by writing a `.types.json` sidecar beside each table: which Python type every column
had been stringified from, learned row by row (`_type_name`, `_learn_types`), rewritten when a
type was first seen, and decoded back by `read_typed_table`. That is a type system written by
hand on top of a format that has none. pyarrow was already a dependency and parquet carries a
`timestamp[us, tz]`; a reader through duckdb or through pyarrow gets the same instant in the same
zone with nothing to guess.

And the record had two clocks (`058`): the execution table normalises the fill target to UTC and
the fill row carried it, while every other table's `event_time` is the agenda instant in the
agenda's zone. A reader lining a fill up against the valuation that followed it converted by hand.

## What changed

- **`flow/run_records.py`.** `append` writes one complete parquet file per chunk,
  `tables/<table>/<n>.parquet`, staged beside the target and moved into place (zstd). One file per
  chunk rather than one open writer per table because a parquet file is readable only once its
  footer is written: an open writer would leave nothing when a run is killed, and a killed run
  leaving every chunk that landed is what record `135` promised
  (`tests/qa/test_run_records_survive_and_race.py`). A chunk is one accepted occurrence's rows.
  `_type_name`, `_learn_types`, `_decode` and the sidecar are gone; `_encode` stays for the
  three JSON record files.
- **Types.** `_arrow_type` derives each column's Arrow field from its values: `bool`, `int64`,
  `float64` (an `int` beside a `float` is a float), `string`, `timestamp[us, tz=<zone of the
  first value>]`, and -- for `Decimal` -- `string` with field metadata `vqapr.type: decimal`. A
  `Decimal` stays text because a parquet decimal needs a fixed scale and a weight of one third has
  twenty-eight places; the metadata is what lets `read_table` restore it and a duckdb reader cast
  it knowingly. A column's type is fixed the first time a non-null value is seen and later chunks
  are cast to it (a null-first column is `null`-typed in the earlier file, which every reader
  unions); a column seen under two kinds is refused at the write by name, where the sidecar used
  to downgrade it to strings. The recorder wrote both, so the run's own table is what is wrong.
- **Readers.** `read_table` streams every chunk's row batches back as Python values, `Decimal`
  included; `read_typed_table` is the same function under the name `vqapr.public` exported; a
  chunk that does not open is a `ValueError` naming the file, never skipped, and `show … --table`
  turns it into the same refusal as before. `table_types` reads the vocabulary
  (`bool`/`int`/`float`/`decimal`/`datetime`/`string`) off the parquet schema. `table_ids` lists
  the table directories.
- **One clock (`058`).** `SimulationFlow._in_agenda_zone` expresses the fill envelope's
  `event_time` in the strategy agenda's zone, as every other table's already was. Same instant.
- **Docs.** `docs/design/run-record-layout.md`'s layout and "why" sections; the architecture's
  §17.6 listing; `SKILL.md`'s sentence about the on-disk rows.
- **Tests.** `tests/flow/test_the_record_reads_back_typed.py` rewritten: a `Decimal` and an
  instant come back as themselves; the same instant through `duckdb.read_parquet` (the A5 trap,
  in the reader that produced it); a weight of one third keeps every digit; one file per chunk
  and a null-first column typed by its first value; two kinds refused at the write; a damaged
  chunk reported. The streams, survive-a-kill and `show` tests point at the directories.

## What this does not do

- **Materialization (`059`)** still holds every output row and every access record until the
  end and writes `.lineage.json`; that loop is deleted in Step 7, where a DataModel becomes a
  flow and its publication a stage of it, and this record's writer is what that stage will use.
- **`record.json`, `run.json`, `strategy.json`** stay JSON: small, and not tables.
- **A record written by 0.3.0** (JSONL) is not read. Breaking, by the campaign's policy; the
  `.jsonl` files are simply not listed as tables.

## Validation

```
uv run ruff check src/                              All checks passed
PYTHONUTF8=1 uv run pytest tests/ -q -m "" -rfE      1355 passed  (fast + slow + showcase gate; branch point: 1332 fast / 21 slow)
                                                    + tests/cli/test_commands.py::test_one_run_records_one_clock, added after, 1 passed
uv run vulture                                      nothing new in src/
```

Seven tests in `test_the_record_reads_back_typed.py` replace five; the one-clock test is new. No
test count floor: measured.
