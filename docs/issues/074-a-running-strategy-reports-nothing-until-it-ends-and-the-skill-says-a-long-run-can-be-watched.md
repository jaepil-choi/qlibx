# 074 -- a running strategy reports nothing until it ends, and the skill says a long run can be watched

**Status:** open. Found 2026-09-04 by the scenario testbed run 4
(`kaist-thesis/vqapr-scenario-testbed/`, FINDINGS **F-007**), against `vqapr-0.4.0`. Confirmed
against source 2026-09-04. Papercut on its own; it is what turned the refusal in `073` into ten
minutes of not knowing whether a strategy was dead.

**Touches:** `src/vqapr/agent/skill/SKILL.md:202-203` ("Rows reach the disk as each occurrence is
accepted, so a long run can be watched"); `src/vqapr/flow/run_records.py:936-949`
(`strategy_refs` omits a directory without `strategy.json`, so `list strategies --run` lists
finished records only); `src/vqapr/cli/run.py` (one JSON line at the end; no `--progress`);
`src/vqapr/flow/orchestration.py` (no output during the loop; nothing writes to stderr).

## What happens

`vqapr run ff-arm --jobs 4`: eight strategies, about 600 sessions each, eleven minutes. During
those eleven minutes:

- `vqapr run` prints nothing.
- `vqapr list strategies --run ff-arm` shows a record only once its `strategy.json` is written,
  which is at the end; an in-flight strategy is absent from the listing.
- `vqapr show strategy` refuses a record that is still being written.

The author watched the run the only way left: counting parquet files under each
`<id>@<fp8>/tables/vqapr.weight/`, one per session. That count is how they noticed one strategy
had stopped advancing at session 307 while the other seven kept going -- and it could not say
whether that strategy had failed, been refused, or was merely slow, because a failed flow and a
paused one leave the same directory (`037` is the same observation about the lock).

The skill promises the opposite: "a long run can be watched". The rows are on disk, so the
sentence is true, but nothing on the surface reads them back for a run that has not finished, and
the skill does not say what "watched" means in practice.

## Why

The record is the unit of reporting: `run` renders the envelope from `strategy.json`, `list` and
`show` read the same file, and a directory without it is by design "killed before it finished" and
omitted. Nothing was built for the interval between the first accepted occurrence and `finish()`.
The parquet chunks are there because the writer is chunked, not because anyone meant them as a
progress signal.

## What to do

- The cheapest honest fix is in the skill: say that an in-flight strategy is not listed, and that
  its progress is the count of chunk files under `tables/vqapr.weight/` (or the last
  `event_time` in the newest one), until a verb exists.
- The verb: `vqapr list strategies --run <id>` listing in-flight directories with a `status:
  running` and the last accepted `event_time`, read from the newest chunk. That is one directory
  scan and one parquet footer per strategy, and it turns "is it stuck?" into a command.
- Optionally, `vqapr run --progress` writing one line per strategy per N sessions to **stderr**,
  never stdout (`047`: stdout is the envelope's).
- With `073`'s per-strategy outcome in the envelope, a run that ends with one strategy stopped at
  session 307 says so; this issue is the same information while the run is still alive.

Related: `073`, `037`, `047`.
