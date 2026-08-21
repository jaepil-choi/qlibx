# 041 — The fill path borrows the run's connection

## Why this exists

The request was to make execution vectorised, on the grounds that filling one instrument at a time
is slow. **Measured first, and the premise did not hold.** On 3,000 instruments:

```text
plan_orders    0.020s
snapshot       0.001s
execute        0.013s
total          0.034s   -> x2096 sessions = 1.2 min
```

Against the reproduction's own recorded costs — `step2b` factors 3,575s, `step3` six alpha lanes
~5,400s — the entire per-instrument fill loop is under 2% of one materialisation step. Vectorising
it would have replaced clear code with array code and bought roughly nothing. The worst path was
checked too: with cash short enough to clip 149 of 3,000 buys, the step-decrement loop still ran in
0.022s.

Profiling a real end-to-end run said where the time actually goes:

```text
14.348s  total callback path
12.580s  scan.py:214(close)          <- 1,465 calls, one per fill snapshot
12.562s  exact_execution_snapshot
```

**87% of it was opening and closing a duckdb connection per fill.** The run already opens one
handle for observations, with a comment saying exactly why:

> One physical handle for the whole run. duckdb caches parquet metadata for a connection's
> lifetime, and closing per query threw that away on every observation.

`exact_execution_snapshot` took no `session` parameter, so the execution table never got that
handle. The fix that had already been made for observations had never reached the fill path.

## What changed

`exact_execution_snapshot` accepts a `ScanSession` and forwards it to `scan.exact_snapshot_rows`,
which already supported one. `SimulationFlow` holds the session and passes it at both snapshot
sites; `public.run()` hands over the session it already creates and already closes.

Nothing else moved. Same query, same rows, same fills.

## Measured

Sample journey, 2,940 occurrences, execute-only wall time, A/B against the committed state:

```text
without session reuse   91.72s
with session reuse      66.63s      -27%
```

Identical results on both sides (2,940 occurrences, account version 2,929). The saving scales with
the number of fills, which is the axis a 2,096-session backtest grows along — unlike the loop that
was proposed for vectorisation, which is already flat.

## Why not vectorise anyway

Two reasons, and the second is the durable one.

**It is not where the time is.** 0.034s per session against 3,575s for one factor build.

**`Decimal` does not vectorise.** Every quantity, price and cost in this package is `Decimal`
because a float weight sum of `1.0000000004` is rejected by the constraint layer, and because a
charged cost has to be exact money. numpy has no `Decimal` kernel, so an "array" version would be
an object-dtype array — a Python loop with worse locality and no type checking. The canon note
about vectorising (§6.3) is about the *matching algorithm's* cumulative-sum step, which is already
a single pass, not about constructing `Fill` objects.

If fills ever do become the bottleneck, the honest lever is fewer of them (netting, or skipping
zero-delta requests earlier), not the same count expressed as arrays.

## Trade-offs

**`SimulationFlow` now holds a session it does not own.** It never closes it; `public.run()` owns
the lifetime and closes it in a `finally`. A caller constructing `SimulationFlow` directly and
passing a session is responsible for closing it — the parameter is optional and defaults to the
previous per-call behaviour, so the direct-construction path in tests is unchanged.

## Validation

- `uv run pytest -q` — **639 passed**; `uv run ruff check src tests` clean.
- A/B measured above, on the same panel, with identical occurrence and account-version results.
- `tests/flow/test_hot_path_costs.py` pins both halves: a session hands back one physical handle,
  and `exact_execution_snapshot` accepts one at all.
- `tests/test_workspace_concurrency.py` flaked once on a Windows file lock and passes 3/3 on
  rerun; unrelated.
