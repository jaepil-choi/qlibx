# 059 -- a materialization holds every row and every access record in memory until the end, writes a lineage file that repeats each instrument per evaluation, and prints nothing while it runs

**Status:** closed 2026-09-03 by record `148` (Step 7 of the deletion campaign): a datamodel is a
registered run; each session's rows leave as one parquet chunk under
`.vqapr/materialized/<dataset_id>/` as the session completes, the record holds one line per
session and no per-instrument lineage, and `.lineage.json`, `materialize()` and the spec file are
gone. The progress line on stderr (third finding) is not in `148`; the loop's `on_progress`
heartbeat exists and a CLI progress line is a separate, small decision. Found 2026-09-03 by the
scenario testbed run 2
(`kaist-thesis/vqapr-scenario-testbed/`, FINDINGS **F-009**), against `vqapr-0.3.0`. Confirmed
against source the same day. **This is the one entry of the run that would have stopped it on the
machine the scenario was meant for:** the user had already dropped the paper's PCA arm because a
rolling PCA exhausted memory on another box.

**Touches:** `src/vqapr/flow/materialize.py:1197-1249` (`stamped_rows` and
`invocation_records` accumulate across `times`); `:486-495` (`_access_payload`, the per-evaluation
`actual_rows` block); `:707` and `:542` (`.lineage.json`, *"still written for one release"*);
`src/vqapr/cli/run.py` (one JSON line at the end, nothing before it).

## What was measured

DataModel `ff6-resid`, 2,145 instruments, 2,378 `evaluate_at`:

| | |
|---|---|
| wall clock | 19m53s (as the 13-evaluation timing run predicted; throughput is not the finding) |
| python RSS at 17 minutes | ~3 GB |
| parquet output | 205 MB, 3.8 M rows |
| `ff6-resid-values.lineage.json` | **478 MB** |
| `ff5-resid-values.lineage.json` (same model minus MOM) | **477 MB** |
| lineage for the 45-evaluation dev run | 9 MB |
| stdout during the 20 minutes | nothing |

Both lineage files are on disk in the testbed's `.vqapr/materialized/`.

## Why

- `materialize()` appends every stamped row and every `MaterializationInvocation` -- which carries
  `window.accesses`, and each access carries `actual_rows` for every instrument -- to two lists
  and writes both after the loop. Rows and lineage are held for the whole run.
- `_access_payload` serialises `actual_rows` per evaluation, so the lineage repeats
  2,145 instrument entries 2,378 times. That is where the 478 MB goes.
- The CLI envelope is one JSON line at the end, by design (skill: *"Every vqapr command returns
  exactly one line of JSON"*), and nothing goes to stderr, so for 20 minutes the only way to tell
  "running" from "hung" was the process list. Issue `047` removed duckdb's progress bar from
  stdout for a good reason; it did not put anything in its place.

## What to do

- Stream rows to the parquet as each evaluation completes (a `ParquetWriter`, the shape Step 5
  of the deletion campaign gives run records), and keep only the current evaluation's rows.
- Record access counts once per instrument per distinct value, or per evaluation as a total,
  not the full per-instrument map per evaluation. `materialize.py:542` already says
  `.lineage.json` survives one release because `run.json` is the authority (record `139`); the
  cheapest fix may be to stop writing it, and this issue is the measurement that decides whether
  the release has arrived.
- A heartbeat on stderr every N evaluations, or `--progress`. stderr keeps the stdout envelope
  contract of `047`.
