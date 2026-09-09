# exp_221 -- what one market-clock instant costs, per instrument

The measurement the one-loop campaign (`docs/refactoring/2026-09-10-the-one-loop-campaign.md`)
gates its performance work on. The two-clocks campaign (records `201`-`214`) made every
instant of the execution table a point where the book is valued, the `vqapr.account` rows are
written and the Compliance rules observe. On a daily table that is 252 points a year; on a
minute table it is 98,280, and everything done at a point is done once per held instrument.

```bash
uv run python experiments/exp_221_the_market_clock_cost/bench.py --names 3000 --days 1
uv run python experiments/exp_221_the_market_clock_cost/bench.py --names 300 --days 3
uv run python experiments/exp_221_the_market_clock_cost/bench.py --names 300 --days 1 --no-positions
```

`bench.py` builds a project under `data/exp_221/` (gitignored): NAMES instruments, a daily
observation table, a minute execution table over DAYS trading days (390 instants a day), a
strategy that rebalances equal-weight every 30 minutes, the shipped `no-short` rule, and a run
record store. It profiles `run()` alone and prints the run's own `timing`, the top of the
profile, and how many mark objects the finished result still holds.

## Baseline -- develop `9ce50725`, 2026-09-10

| configuration | run | what it says |
|---|---|---|
| 300 names x 1 day (390 instants) | 15.7 s | |
| 3,000 names x 1 day | 117.4 s | 10x names, 7.5x time: linear in names |
| 300 names x 3 days | 43.8 s | 3x instants, 2.8x time: linear in instants |
| 300 names x 1 day, `--no-positions` | 8.7 s | the per-position `vqapr.account` rows are 45% |

About 100 µs per (instant, instrument). 3,000 names on a minute table: two minutes a day,
eight hours a year. 3,000 names on a daily table: 76 s a year -- not the problem.

Where the 117 s of the 3,000-name day go (cumulative, from the profile):

| where | s | doing what |
|---|---|---|
| `shapes.normalize_rows` via `InvocationRecorder.append` | 42 | re-checking the field names of 1.2 M framework-written rows for whitespace, a check `TableSpec` already made once |
| `RunRecordWriter.append` -> `schema._arrow_type` | 21 | re-inferring each column's Arrow type from every value of every chunk, when the first chunk fixed it |
| `scan.exact_snapshot_rows` + `_exact_row` | 17 | one duckdb query per instant (`IN` with 3,000 placeholders), then `Decimal(str(price))` per row |
| `compliance.build_account_view` + `ModelWindow.__init__` | 13 | re-validating 3,000 instrument ids twice per instant; the ids came out of a validated `AccountSnapshot` and a frozen run |
| `marking.mark`, `_marks_from_execution_snapshot` | 10 | Decimal arithmetic per name; the intrinsic cost |

Memory: `Mark` objects retained by the finished result equal instants x names (116,700 for
one day, 350,700 for three). Every instant's mark batch hangs off `lifecycle_trace` and
`occurrences`, and the only reader at the end is `contract_report`'s three counters.

## After each milestone

Re-run the 3,000 x 1 configuration and append the number to the implementation record of the
milestone; the campaign document §1 keeps the baseline.
