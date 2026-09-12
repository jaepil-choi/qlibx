# 165 — the kill test waits for evidence, not a clock

**Closes:** the trap noted in `docs/handoff/2026-09-04-one-shape-campaign-handoff.md` on
2026-09-07 ("the kill test kills its worker on a timer"). **Branch:** `claude/infallible-wing-ad4066`,
off `develop @ 6deef6c3` (after record `164`). **Campaign:** none. **Scope:** one test file;
no production source changed. An implementation record is written because the task asked for one.

## Why this exists

`tests/qa/test_run_records_survive_and_race.py` drives a separate interpreter that appends rows
to a run record, then signals or kills it and asserts what survived. Two versions of the wait
between "start" and "kill" have both been clocks:

- Before record `164` the test was `test_a_process_killed_mid_write_leaves_rows_and_no_record`
  and slept 0.6 s after `Popen`. On Windows the child spends one to three seconds importing
  `vqapr`, so the kill landed before the first parquet part and the assertion "at least one
  `*.parquet` under `tables/`" failed. Measured: 1 failure in 6 isolated runs on
  `step-07-fold-packages`; a first-run failure on a `develop` worktree the same day.
- Record `164` split it into an interrupted test and a hard-killed test and added
  `_wait_until_writing`, which polls for the child's `.running` lock -- and then sleeps 1.0 s.
  The lock is written by `open()`, before the first `append`. On a fresh `.venv` in this
  worktree the first `append` (Arrow conversion, pyarrow's parquet writer and the zstd codec
  loading cold) took longer than that second: the very first run of the file here failed BOTH
  process tests with `FileNotFoundError` from `table.iterdir()`, because the kill arrived before
  the child had created the table directory. The same file passed on its second run, once the
  imports were warm.

A clock only encodes how fast the author's machine was that day. The assertion needs a
precondition -- rows on disk, or rows in memory -- and the precondition is observable.

## What changed

- **`_wait_for(proc, evidence, what)`** replaces `_wait_until_writing`. It polls a predicate
  every 50 ms, fails by name if the child exits first ("the child ended before its first spill
  part") and fails by name after a 120 s budget that exists only so a hung child is reported by
  the test rather than by the harness. The polling cadence is the only sleep left, and it is a
  cadence, not a delay: the loop exits the moment the evidence exists.
- **Hard-killed test** (`spill_bytes=1`, so every `append` spills one part). Evidence: the first
  `[0-9]*.parquet` under `tables/vqapr.account`. `_write_parquet` stages each part as
  `.000000.parquet.tmp` and `os.replace`s it into its final name, so a part that matches the
  glob is a complete file with its footer written; the kill lands with at least one readable
  spill part on disk, which is exactly the fact the assertions below rely on. The lock wait is
  subsumed: a part on disk implies `open()` succeeded.
- **Interrupted test** (`_NO_SPILL`). Nothing reaches the disk before the end since `087`, so
  there is no product artifact to observe for "rows are in memory" -- `progress.json` is
  rewritten only every `PROGRESS_EVERY` (5 s), which would have tied the test's duration to a
  product constant. The probe script takes a fourth argument and touches it after its tenth
  `append` returns; the test waits for that marker. The handler is installed before `open()`, so
  a signal sent after the tenth append is an interrupt and not the other test's hard kill. This
  is the same gate-file idiom the `--force` race test in the file already uses. The
  `len(rows) >= 10` assertion is now guaranteed by the wait rather than by "one second at 20 ms
  per row is about fifty".
- Both tests lost the fixed second: 1.41 s -> 0.67 s and 1.43 s -> 1.01 s in the same file run.

## The five-process race test, assessed

`test_five_processes_racing_the_same_run_id_refuse_rather_than_interleave` is in the same file
and is documented (handoff "함정 하나", and its own comment) as a ~1/12 flake. It does NOT admit
the same treatment, for a different reason: it has no clock to replace. Nothing in it kills or
signals anything on a timer; five children start and each calls `open()` once, and the only
timeout is `communicate(timeout=180)`, a budget rather than a trigger. Its flake is the product
window documented at the recovery branch of `RunRecordWriter._open` in `src/vqapr/flow/record.py`:
a peer can read a dead-looking directory between another process's `mkdir` and its `_claim`, and
two winners result. That window is in the code under test, not in the test's timing, and the
file's own comment records that two attempts to close it made it more frequent. An evidence-based
gate (release the five together, as the `--force` test does) would make them contend HARDER and
raise the flake rate; it would not make the test more correct. Left as it is, on purpose. Observed
here: 0 two-winner outcomes in 7 whole-file runs, consistent with the documented rate.

## Trade-offs

- The interrupted test's evidence is manufactured by the probe (a marker file), not observed from
  the product. The alternative -- `progress.json` reporting ten rows -- is product evidence but
  arrives on `PROGRESS_EVERY`, making a 1 s test a 5 s test that slows whenever that constant
  grows. The marker is the direct precondition of the assertion and costs nothing.
- The hard-killed test now also passes a marker path it never reads, because the two tests share
  one probe script. Two scripts would be more code than one unused argument.

## Validation

- `uv run ruff check` and `ruff format --check` on the test file: clean.
- Hard-killed test, 20 isolated runs (`for i in $(seq 20); do uv run pytest -q "<id>" -p
  no:cacheprovider | tail -1; done`): **20 passed, 0 failed**, 0.89-1.02 s each.
- Interrupted test, 20 isolated runs, executed CONCURRENTLY with the loop above so both were
  under load: **20 passed, 0 failed**, 1.11-1.20 s each.
- Whole file: 1 run at 6 passed after the edit, then 5 more at **6 passed** each (5.2-5.4 s),
  plus 1 baseline run before the edit at 6 passed and 1 baseline run at **2 failed** (the cold
  start described above), which is the failure this record closes.
- No production source changed, so `test_all` was not run; the change cannot reach run assembly,
  the record shape or the scaffolds.
