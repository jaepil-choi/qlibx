# 068 -- a session costs a quarter second of package time, most of it two execution snapshots fetched as Python rows, and nothing in the run result says where the time went

**Status:** open. Found 2026-09-03 by the scenario testbed run 2, phase 2
(`kaist-thesis/vqapr-scenario-testbed/`, FINDINGS **F-016**, recorded by the agent *"for the
maintainer, not a defect"*), against `vqapr-0.3.0`. Filed because the profile is the first
per-session cost breakdown of a full strategy run on this wheel, and because two of its lines
are the shape `054`, `061` and `143` closed on other paths: per-cell Python work on a hot path
duckdb or Arrow could do once.

**Measured on `0.3.0`, before records `143` (lazy window columns, Arrow `counts()`) and `146`
(parquet record tables).** Those two remove the `counts` and part of the `run_records.append`
lines below; the snapshot lines are untouched.

**Touches:** `src/vqapr/data/scan.py:630-663` (`exact_snapshot_rows`: one SQL, then
`cursor.fetchall()` into a tuple of dicts); `src/vqapr/flow/execution.py:62-75`
(`select_snapshot`, one snapshot per fill) and the valuation mark (`_standalone_marks`, one more
per session); `src/vqapr/cli/run.py` (the result payload).

## What was measured

Strategy `ou-k0` in run `arb-k0k5`, 1,349 sessions, 2,151 names, cProfile of the whole process
after the F-015 fix (`work/prof_arb-k0k5_ou-k0.prof`, summary by `work/prof_summary.py`):

| | |
|---|---|
| wall | 356 s (2,270 s before the F-015 fix) |
| own time, total | 408 s |
| of which vqapr | 244 s (60%) |
| builtins / stdlib | 35 s |
| numpy | 24 s |
| the strategy's own code | 22 s |

Inside the package's 244 s:

| where | s | note |
|---|---|---|
| `scan.exact_snapshot_rows` | 91 | 2,698 calls, ~34 ms each: two execution-table snapshots per session, one to fill and one to mark |
| `scan.observation_rows` | 74 | the two panel builds, once per run; expected |
| `simulation._due_boundary` | 68 | cumulative; the wrapper around the snapshot and planning calls |
| `execution.select_snapshot` | 48 | the fill-side half of the first line |
| valuation `_standalone_marks` | 45 | the mark-side half |
| `panel.counts` | 36 | 153 M cell visits for the access record's per-name non-null counts on every read -- **closed by `143`** |
| `run_records.append` | 22 | JSONL; **changed by `146`** |
| `datetime.replace` x 27.8 M + `pytz.timezone(...)` x 18.4 M | ~40 | one timezone resolution per cell, inside the snapshot fetch |

So roughly 0.25 s of package time per session, about six minutes over this run, and more than
half of it is the two snapshots: a full-universe `SELECT ... WHERE trade_at = ? AND instrument IN
(2,151 placeholders)` whose result duckdb converts row by row into Python `datetime`s carrying
`pytz` zones (the reason `pytz` is still a dependency, record `129`), then into a dict per row.

## What to do

- Fetch the snapshot as Arrow (`fetch_arrow_table`) and keep it columnar until a row is needed;
  the `trade_at` column is one value for every row and does not need converting at all. This is
  the `143` move on the execution path.
- Take one snapshot per session where the fill instant and the mark instant coincide on the
  same table, which for a same-close convention (`064`) they do.
- Put a per-phase timing block in `vqapr run`'s result -- read, snapshot, decide, plan, commit,
  record -- so the next user does not need cProfile to learn that their strategy is 5% of the
  wall clock. The agent asked for `--profile`; a timing block in the payload is cheaper and is
  always there.
