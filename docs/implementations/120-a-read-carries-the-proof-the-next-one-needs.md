# 120 — A read carries the proof the next one needs, so a declared input costs one round trip

**Closes:** the second half of
[046](../issues/046-a-factor-book-pays-per-callback-and-each-declared-input-costs-two-queries.md) —
each declared `RowsLookback` input costing two statements to answer with one row per name. Lane B
of the read-path campaign (`docs/refactoring/2026-09-01-the-read-path-campaign.md` §2).
**Branch:** `read-046b-one-round-trip`.

The first half of `046` — the per-callback floor, and the fusing that removes it — is lane D and is
untouched here.

Rebased onto lane A (record `119`, issue `044`) as the campaign's merge order says. One thing that
lane changes matters to this one: the rows `observation_rows` returns now go to
`ObservationBatch._trusted` with **no normalization pass in between**, so nothing downstream would
notice a column that leaked out of this change. The proof columns are stripped where they are read,
and the assertion that says so is in the acceptance test below — not in
`tests/data/test_observation_batch_shape.py`, which builds its store without a session and
therefore never reaches the bounded form a proof column could leak from.

## What was true

A `RowsLookback` declares a count, not a span. There is no bound to push down, so without one the
window function below is ranked over the source's entire history on every callback. `scan.py` has
answered that since the bound was introduced: guess a bound from the run's instant grid, then ask
the source which instruments the guess would have changed the answer for, and read those with no
bound at all in the same statement. The result is the one the unbounded query would have produced.

The asking was a statement of its own, and it ran **on every callback**. `ff_factors` declares
`characteristics`, `prices` and `master` — all `RowsLookback(rows=1)`, the ordinary shape for a
strategy that wants each name's latest value — so a session paid six round trips to be told three
things that had not changed since the session before.

## What changed

**The proof is taken once and then carried by the reads themselves.**

Two properties make that sound, and both are about the *pair* `(bound, grid position)` rather than
about the bound alone:

1. **A proof survives forward in time.** It says "these instruments have `rows` non-null values of
   every declared field between `lower` and here". Move the near end forward and the window only
   grows, so what was proved safe stays safe. The exempt list stays a superset of what is unsafe
   now, which is the direction that keeps the answer right — a name that has since become safe is
   merely read unbounded for nothing.
2. **The rows that would prove the *next* bound are already being read.** The next callback's bound
   is at or above this one's, so the window that decides it is inside the window this statement is
   already scanning. Counting it costs a window aggregate, not a round trip.

So each bounded read carries one count per physical field out with it, the count is read off the
answer, and it becomes the proof the next callback applies. The bound trails the tightest one
available by exactly one callback's worth of grid — never more, because every callback re-proves —
and the trailing is what buys the statement.

The invariant the old comment stated is unchanged and moved with the code: it is now the docstring
of `_RowsBound`, next to the exemption it explains, and the reuse argument is on `_rows_bound`.

### The statements, per declared input

| | before | after |
|---|---|---|
| first callback of a run | grid, proof, read | grid, proof, read |
| every callback after it | proof, read | **read** |

### What changed, file by file

| file | change |
|---|---|
| `src/vqapr/data/scan.py` | `_rows_lower_bound` splits into `_rows_bound_guess` (grid arithmetic, no statement), `_prove_rows_bound` (the one probe), and `_rows_bound` (which of the two a callback needs). `_RowsBound` carries `(lower, unbounded, cut)`; `ScanSession` keeps one per declared read for the life of the run; `observation_rows` emits the proof columns and strips them from the answer |
| `tests/flow/test_hot_path_costs.py` | a statement counter at `ScanSession.connection`; the acceptance tests below; `STOPS` added to the `halted_source` panel |

## Acceptance

### 1. Two statements per declared input become one

Counted twice, because a fixture can be made to say anything and a real book cannot.

**In the suite** — `test_a_declared_input_costs_one_statement_per_callback` counts every statement
the session issues, at `ScanSession.connection`, which is the one door the estimate, the grid and
the read all pass through. Walking a ladder of evaluation times: `3, 1, 1, 1, 1` — grid, proof and
read on the first callback, one read on each after it. The test also asserts *which* bound was
kept, because one statement is equally what a bound nobody can use costs.

**On the real panel** — `Hml`, 50 instruments, 20 rebalanced sessions, against the prepared
`vqapr-enhanced-index-3` warehouse, counting calls in the `vqapr-performance-testbed`:

| | `observation_rows` | probe statements |
|---|---|---|
| before | 123 | **120** |
| after | 123 | **2** |

Two, not three, because `security-master` is under `ROWS_BOUND_MIN_BYTES` and is never bounded at
all; the two sources that are bounded pay one probe each for the whole run instead of one per
callback. The same shape at 60 sessions pays the same two.

### 2. A sparse name gets the unbounded answer

`test_a_proof_that_outlives_its_callback_still_returns_the_unbounded_result` walks the same ladder
at `rows` 1, 5 and 60, and compares every callback against the same read taken with no session at
all — the form that has no bound to be wrong about. Equality is over rows, values and order.

Three names carry the test, and each one fails a different way if the reuse is wrong:

| name | shape | what it catches |
|---|---|---|
| `HALTED` | stopped publishing 340 sessions before the ladder starts | an exemption dropped: the classic silent corruption |
| `LATE` | lists partway through the ladder | a name that is unprovable and then becomes provable |
| `STOPS` | falls silent *inside* the ladder | a proof applied with a bound it was not taken against |

`STOPS` is the one that is specific to this change. It is dense when the first proof is taken and
silent later, so it is only correct because each callback proves the bound the *next* one will
apply, rather than the one this one is applying.

### 3. The ladder, and what it can and cannot say

Re-run against the `vqapr-performance-testbed`, `Hml`, 60 sessions, the five universes `046`
measured. **Both arms are the same tree**: the base is `develop` with lane A, the other is that
plus this change, built as wheels and installed into two throwaway venvs.

Three things about the conditions, stated because they decide how much the numbers are worth:

- The machine was **not quiet**. Two, and for part of the time three, research pipelines were
  running in `vqapr-enhanced-index-3`. The testbed's own discipline says such a measurement is
  discarded, and `busy` moved between 2.5 and 5.9 across rungs.
- The two arms therefore run **back to back at each rung, with the order alternating** (50
  base-first, 150 fix-first, and so on), so that drifting load and any second-run advantage cancel
  across the ladder rather than land on one arm. An earlier pass that ran the arms twelve minutes
  apart reported a 20% gain, and it was an artifact: a third pipeline started between them.
- The prepared panel had to be repaired first — see the note at the end.

| instruments | base | with this change | base s/session | s/session |
|---|---|---|---|---|
| 50 | 6.88 s | 6.38 s | 0.115 | 0.106 |
| 150 | 8.10 s | 7.44 s | 0.135 | 0.124 |
| 300 | 10.92 s | 10.92 s | 0.182 | 0.182 |
| 1,200 | 17.90 s | 17.69 s | 0.298 | 0.295 |
| 2,795 | 31.83 s | 33.21 s | 0.531 | 0.554 |

**At book level this says nothing.** The differences run in both directions and are the size of the
noise — the same rungs moved by up to 20% between two passes of the same build. A book's wall time
is not a fine enough instrument for a change worth a few percent of it, on a loaded machine.

So the read this change actually touches was priced on its own: `observation_rows(rows=1,
session=...)` against the real daily panel, over 30 consecutive session instants, which is the
shape `ff_factors` issues. Median per callback, three alternating pairs at each size:

| instruments | base | with this change | |
|---|---|---|---|
| 300 | 88.1 / 92.8 / 92.8 ms | 78.1 / 78.8 / 78.6 ms | **−13.9%** |
| 2,795 | 201.8 / 186.9 / 195.6 ms | 164.1 / 160.9 / 167.8 ms | **−15.7%** |

Six pairs, no overlap between the arms, and both return the same 2,635 rows. Probe statements over
those 30 callbacks: 30 before, 1 after.

### 4. Gates

`uv run ruff check src/` clean. `PYTHONUTF8=1 uv run pytest tests/ -q` → **1514 passed, 5 skipped,
14 deselected**, on this branch rebased onto lane A. The five skips are environment provisioning —
`scripts/prepare_dev_data.py` output and the full `data/DW` warehouse — and are unrelated to this
lane; the campaign's gate of 1497 counts a machine where the dev dataset is provisioned, and the
same suite at this lane's branch point was 1492 passed with the same five skips.

## Where the floor went

**`046`'s floor of ~0.19 s per session is already stale, and mostly not because of this lane.** At
50 names the base measured here is 0.115 s per session. Lane A is the bulk of that: record `119`
took the normalization pass off the read path and measured 8.644 s → 4.877 s on one window.

What this lane removed is the second statement, and it is worth what the profile always said it was
worth — `046`'s own cProfile put `_rows_lower_bound` at 0.601 s of tottime against
`observation_rows`'s 6.015 s. Re-profiled at the same point (200 instruments × 40 sessions, back to
back, ranks only — a profile inflates 2-4x and is never quoted as a duration):

| | base | with this change |
|---|---|---|
| `observation_rows` | 5.164, 119 calls | 4.935, 119 calls |
| `_rows_lower_bound` / `_prove_rows_bound` | 0.513, **119 calls** | absent from the top 45, **2 calls** |
| `exact_snapshot_rows` | 0.443, 80 calls | 0.486, 80 calls |
| `instant_grid` | 0.330, 40 calls | 0.335, 40 calls |

**The floor that remains is `observation_rows` itself** — the window ranking, not the round trips
around it. The next two candidates are the ones `046` named and this profile confirms:
`exact_snapshot_rows` (80 calls, fills and marks) is now second, and `instant_grid` third. Neither
is a lookback question; both are separate reads on the same hot path.

## What this does not do

- **It does not fuse the three declared inputs into one scan.** That is lane D, and it has no
  target until field expressions land in lane C.
- **It does not touch the window predicates** — `available_at <= ?`, the lookback bound, the
  instrument list. Those are the PIT boundary and this lane had no business in them.
- **It does not make the estimate free on a small source.** `ROWS_BOUND_MIN_BYTES` still gates it,
  and the gate's 28% measurement was taken against the old form; the new form is cheaper than what
  that number measured, so the gate is now conservative rather than tight. Re-deriving it is worth
  doing and is not this lane.

## Two things the measurement found that are not this lane's

Both are recorded here because they were found by measuring this lane and would otherwise be lost.

**1. The prepared panel cannot be registered after lane A, and it is the data that is wrong.**
`equity_daily.parquet` carries **82 rows** whose `close`, `open`, `high`, `low` and `base` are all
`+inf` — one instrument (`A065180`), 2015-01-02 to 2015-04-30, out of 8,651,872 rows. The cause is
`adj_factor = 0.0` in the research environment's own preparation: `raw_close / 0`. Lane A's
`check_values` refuses them at registration, correctly — an infinite close values a holding at
infinity, which is exactly what that check exists to stop. Two consequences: the research
environment must fix `prepare.py` before its next rebuild, and any past run that read that name in
those four months carried an infinity through its numbers silently. The measurements above were
taken against a snapshot with those 82 rows dropped — the other 46 files hardlinked, the panel
rewritten with the same ZSTD codec and row-group size (449,864,866 bytes against 449,867,025),
pointed at with `KWAM_PERF_PREPARED` so nothing in the research environment was touched.

**2. The performance testbed had drifted out of sync with `develop` and measured nothing.** Three
probe targets had moved or gone: `public._freeze_record` and `public.load_strategy_model` (records
115-117 moved the run path into `vqapr.flow.orchestration`) and `store.normalize_rows` (deleted by
lane A). The first raised `AttributeError` before any measurement ran. `probes.py` now resolves
those seams against whatever is installed, which is the rule that file already stated for `run()`.
That edit is in `kwam-enhanced-index` and is **uncommitted** — it is a measurement harness, not
this repository's code, but the campaign's remaining lanes need it to measure anything at all.
