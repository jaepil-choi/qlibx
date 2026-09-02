# 135 — the run record streams, and its format does not reproduce the tz trap

**Closes:** testbed findings A4 · A5 · A6 (`kwam-enhanced-index/vqapr-enhanced-index-3/VQAPR-ISSUES.md`;
`docs/issues/README.md` §unfiled). **Step:** 3 of
`docs/refactoring/2026-09-02-the-convergence-campaign.md` (M3).
**Authority:** the campaign doc's Step 3 acceptance; `docs/design/run-record-layout.md`.

## Why this exists

Three findings from the largest real session, and the campaign put them before the Panel step
because Step 5 makes the panel resident in the process and the write side had to stop being
resident first.

- **A4.** Every accepted callback and valuation appended its recorder chunk to the run state's
  root, and `freeze_record` walked `final_state.recorder_rows` **after** `flow.run()` returned.
  A 2.6M-row `vqapr.account` was 2.6M dicts on the heap until the end, then a ~3GB JSONL; a run
  killed midway left nothing. The writer had always appended in chunks — the layout design says
  so — and nothing called it during the run. The rows actually read were the `_ACCOUNT` ones:
  0.07% of the table.
- **A5.** The record's JSONL carries a `Decimal` as a string and an instant as ISO-8601 with its
  offset. `read_json_auto` turned `"2019-07-01T15:31:00+09:00"` into a naive instant shifted by
  nine hours, and a factor panel built from it registered cleanly. Nothing on `vqapr.public`
  read a record.
- **A6.** `show run --table --limit 0` streamed 260K–2.6M rows to stdout, so the testbed bypassed
  the surface and met A5.

## Rulings

| question | ruling |
|---|---|
| parquet or JSONL | **JSONL stays.** The layout's reason holds: append-only, a killed run leaves readable rows and no `record.json`. A parquet footer is written at close; a killed run would leave an unreadable file, the opposite of the acceptance. What the campaign requires is that the format not reproduce the trap, and the sidecar plus reader below is what closes it. |
| where streaming hooks in | **the accept funnel.** `RunStateRepository.publish` / `_publish_infallible` are the two places a prepared root becomes current; a `row_sink` given to the repository receives each occurrence's chunks there, before the swap, and the accepted root keeps none. Without a sink the roots keep chunks as before. |
| where the record's counts come from | **the writer,** which counts rows and distinct instants per table as chunks pass through `append` — streamed or handed over at the end — so nothing holds the rows to count them. |
| where the types live | **a sidecar per table, written by the writer** at the moment it stringifies the values, rewritten only when a column's type is first seen or changes. |
| position rows per valuation | **declared in `store:`** — `account_positions: true` (default, today's record) or `false` (the `_ACCOUNT` row alone). |

## What changed

### Rows leave the run as it runs (A4)

`RunStateRepository(row_sink=...)`. The two prepare paths that carry recorder chunks —
callbacks and standalone valuations — fold them into the root when there is no sink, and carry
them on the `PreparedRunState` when there is; `publish` hands them to the sink **before** the
swap, so a sink that cannot take them (a full disk) fails the occurrence rather than accepting a
root whose rows were lost, with everything up to the previous occurrence already on disk.
`orchestration.run` wires the writer's `append` as the sink; `freeze_record` writes only
`record.json` at the end, from the writer's counts.

Measured, in `tests/flow/test_the_run_record_streams.py`: the table file grows between
occurrences while the run executes, the final state retains no rows, and — under `tracemalloc`,
as a ratio rather than a number — a streamed run's peak heap is under half of the same run kept
in memory. The existing kill-mid-run test keeps its meaning with the product path now behind it.

### Types travel beside the rows (A5)

`tables/<id>.types.json`: per column, the Python type the writer encoded from (`decimal`,
`datetime`, `int`, `float`, `bool`, `string`). A column seen under two types is recorded as
`string`, because reading the strings that were written is the one answer that loses nothing.
`read_typed_table` decodes by it and `vqapr.public` exports it as `read_run_table`, beside
`read_run_record` and `run_ids`; a table with no sidecar predates it and reads as strings. The
raw `read_table` — the CLI's page — is unchanged.

The Flow's own `vqapr.account` rows carried `str(cash)`, `str(nav)`, `str(quantity)`,
`str(price)` before they reached the recorder, which would have recorded them as strings. They
carry the `Decimal`s now; every in-memory reader of those rows in tests and showcases already
accepted either.

The exact trap is a test: `15:31+09:00` written, read back with hour 15 and equal to its UTC
instant.

### `show run --table --instrument` (A6)

Filtered row by row while streaming the file, never after loading it. The envelope reports three
numbers — `rows_total`, `matched`, `returned` — so a filtered page cannot read as a short table.

### `store.account_positions` (A4, the 0.07%)

Parsed by `StoreSpec` beside `root` and `tables`, threaded through `public.run` to the Flow, and
honoured at both places the Flow writes account rows. `false` records the `_ACCOUNT` row alone;
fills are recorded either way, so positions stay recoverable. A run-level test asserts it.

## Trade-offs

**Materialization records are untouched.** They go through the same writer with `finish` only
and no sink; their `tables` block was never built from rows.

**`recorder_rows` is empty for a store-backed run.** The one `src/` reader that wanted it,
`publish_run_record`, has no caller in the product (`cli/run.py` says so) and keeps working on
in-memory results. Tests and showcases run without a store and see rows as before.

**Two counts of `instants` moved, and a test that pinned the counting expression by its text
moved with it** — to the writer, where the counting now happens.

**A published account table is now a decimal column, and one showcase compared text.**
`publish_run_record` publishes what the run recorded; with `cash` a `Decimal`, the column is
`DECIMAL(29,19)` where it was `VARCHAR`. `show_006` compared the published values to
`str(recorded)` and failed on the type; it compares as `Decimal` on both sides now, which is what
it meant. The other showcases that publish or read account rows (003, 005, 007, 008) complete
unchanged.

**The sidecar is one more file per table.** Written atomically, at most a few times per run.

## Validation

```
uv run ruff check src/                           All checks passed
PYTHONUTF8=1 uv run pytest tests/ -q -rs         1270 passed, 14 deselected
PYTHONUTF8=1 uv run pytest tests/ -q -m slow -rs  14 passed
```

Branch parent `develop @ 59dd950c` (record `134` merged), measured: **1260 passed / 14
deselected** fast (one subprocess race test flaked once on the re-gate and passed on rerun);
**14** slow. The ten new tests are the difference.

Showcases that publish or read account rows (003, 005, 006, 007, 008) re-run on this branch:
all complete, `show_006` after the comparison change above.
