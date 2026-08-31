# 046 — A factor book's cost is a fixed charge per callback before it is a charge per name, and each declared `RowsLookback` input costs two round trips to answer with one row

**Status when filed:** open. Found 2026-08-31 by a profiling pass in
`kwam-enhanced-index/vqapr-performance-testbed/`, against `vqapr-0.2.0a2` (built wheel).
**Touches:** `src/vqapr/data/scan.py:640` (`_rows_lower_bound`); `src/vqapr/data/scan.py:707`
(`observation_rows`); `src/vqapr/data/store.py:59` (`DuckDbObservationStore.query`);
`src/vqapr/flow/simulation.py:1386` (`_dispatch_callback`, one `ModelWindow` per occurrence).

[035](035-the-only-data-accessor-is-ninety-times-slower-than-the-file.md) measured the accessor on
the **materialization** path, where one call returns half a million rows. This is the same accessor
on the **simulation** path, where it is called thousands of times and returns a few hundred rows
each time — a different regime, with a different dominant term.

## The curve

Six Fama-French legs are run as StrategyModels, each rebalanced every session. One leg (`Hml`,
signed, three declared inputs), 60 sessions, universe varied:

| instruments | wall | per session |
|---|---|---|
| 50 | 11.90 s | **0.198 s** |
| 150 | 13.25 s | 0.221 s |
| 300 | 13.32 s | 0.222 s |
| 1,200 | 18.27 s | 0.305 s |
| 2,795 | 41.34 s | 0.689 s |

**A 6x universe (50 to 300) costs 12% more. A 56x universe costs 3.5x.** There is a floor of about
0.19 s per session that a book pays for existing, and it dominates up to roughly 300 names. Session
count is clean: `t ~ sessions^1.02` at every universe size.

The floor is where a small book's time goes, and it is the finding. `window.sql` is **80-82%** of a
factor book at every point on this ladder; the strategy's own arithmetic — a two-by-three sort over
a dict — is 2-4%.

## Where the floor comes from

cProfile, `Hml`, 200 instruments x 40 sessions, 10.016 s:

```
ncalls   tottime  function
 119/2    6.015   scan.py:707(observation_rows)      <- 60% of the run
 119/2    0.601   scan.py:640(_rows_lower_bound)     <- an extra query before each of those
    80    0.505   scan.py:436(exact_snapshot_rows)   <- fills and marks
    40    0.346   scan.py:223(instant_grid)
```

119 calls is 40 sessions x 3 declared inputs. **About 50 ms per query, to return one row per name.**

`ff_factors` declares `characteristics`, `prices` and `master`, all `RowsLookback(rows=1)` — the
ordinary shape for a strategy that wants each name's latest value. Each of those is two statements,
not one:

1. `_rows_lower_bound` runs `SELECT instrument, count(col), ... GROUP BY instrument` to decide a
   safe lower bound;
2. `observation_rows` then runs the windowed query with that bound applied.

**The two-statement design is correct and should stay.** Its docstring is right: an unbounded
`RowsLookback` evaluates a window function over the whole source on every callback, and a naive
bound silently drops a halted or delisted name whose last observation predates it — "no error is
raised; the number just changes". Guessing and then proving the guess is the right answer to that.

What is not right is *when* it re-proves. Extrapolated to a full book — 1,731 rebalanced sessions x
3 inputs x 2 statements — that is **10,386 round trips**, and about 1,731 of the probe queries
answer a question whose answer has not changed.

## Three things the run already knows and does not use

1. **The probe's answer is stable across consecutive evaluations.** `_rows_lower_bound` returns
   `(lower, unbounded_instruments)`, a function of `(source, instruments, fields, rows,
   evaluation_time)`. Within one run the first four are frozen by construction — `FrozenRun` fixes
   the instrument list, the requirement fixes the fields — and `instant_grid` is already cached for
   the session. Only `cut = bisect_right(grid, evaluation_time)` moves, and it moves by one grid
   position per session. The `GROUP BY` can be re-derived incrementally, or cached and re-run only
   when the grid position moves past what the previous answer covered. This is the cheapest item
   here and it removes half the round trips.

2. **A dataset that does not change cannot give a new answer.** `firm-characteristics-values` is
   materialised once a June; `security-master` is effectively static. Both are re-queried on all
   1,731 callbacks. The source is frozen for the run — `DuckDbObservationStore` caches its digest
   for exactly that reason — so when a `RowsLookback` read returns rows whose newest `available_at`
   is strictly older than this evaluation time, **the same read at the next evaluation time returns
   the same rows**, and that is provable from the frozen source rather than assumed. A read-through
   cache keyed on `(requirement, newest available_at seen)` is sound under exactly that condition
   and does nothing when it does not hold.

3. **A callback's requirements are known together.** `_dispatch_callback` builds one `ModelWindow`
   per occurrence holding every allowed requirement, and the model then reads them one at a time.
   Three sources means three round trips at the same instant for the same instruments; one cursor
   could carry them together.

## What a fix is worth, and what it is not

Item 1 alone halves the statements per callback. Items 1 and 2 together leave a three-input strategy
paying one round trip per session instead of six.

**It does not make the 2,795-name book cheap.** Above ~1,200 names the universe-dependent term takes
over — a `WHERE instrument IN (...)` list of 2,795 literals, and correspondingly more rows through
the same accessor that [044](044-the-read-path-revalidates-eight-column-names-once-per-row.md) and
[045](045-a-requirement-cannot-say-which-rows-so-a-long-table-delivers-a-hundred-and-fifty-times-what-is-kept.md)
describe. The two halves are separable and both are real: the floor is what a 300-name book pays,
the slope is what a 2,795-name book adds.

## The run record is 15%, and it is not written where it was thought to be

Same book, same 60 sessions, 2,795 names, run twice with `store_root` set and unset:

```
store_root=None    41.34 s
store_root=...     47.71 s   (+15%),  record 86.7 MB,  of which _freeze_record 3.29 s
```

The research environment's `VQAPR-ISSUES.md` A4 reports "nothing is written until the calculation
ends" and infers from that a large terminal write. **The size is right and the timing is not**: at
60 sessions the terminal freeze is 3.3 s of the 6.4 s difference, and the rest is spent during the
run. 86.7 MB over 60 sessions extrapolates to ~2.5 GB over 1,731, which matches the ~3 GB per broad
book observed there.

So the record is worth fixing for **disk and for the missing progress signal**, which is what A4
actually argues, and it is not where a book's time goes. It ranks below items 1 and 2 above.

## One caveat on comparing these numbers to a real build

The research environment measures 2,369-3,148 s for a broad book of 1,731 sessions (1.37-1.82 s per
session) against 0.795 s per session measured here with the record on. The gap is not a
contradiction: those twelve books ran six-at-a-time on one machine, and a book that runs beside five
others contends for cores and for the page cache holding a 450 MB panel. The ladder here ran alone.
Anything measured against it should be measured alone too.
