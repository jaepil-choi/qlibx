# A datamodel run's memory tracks its instrument count, not its declared lookback or its period

**Status: UNTRIAGED — reported by testbed, not yet judged by the owner.**

| | |
|---|---|
| vqapr version | `0.11.0` |
| installed from | `../../vqapr/dist/vqapr-0.11.0-py3-none-any.whl` |
| reported | 2026-09-10 |
| reporter | `kwam-enhanced-index/vqapr-enhanced-index-3`, agent session |
| python / OS | 3.12 / Windows 11, 32 logical cores, 15.7 GB RAM |

## What I was doing

Running 671 alpha datamodel runs concurrently. Each declares 309 instruments and a
`CalendarLookback` of a few hundred days over `equity-daily` (430 MB, 8,676,023 rows, 4,975
instruments, 2015-2026). At eight concurrent runs the machine sat at 10% free; at twelve it
reached 96% used, the throughput decayed from 3.6 s to 21.5 s per run as it swapped, and the build
died. So I measured where the memory goes.

## What I expected

Peak memory to track **what a callback reads** — the declared window times the declared
instruments — and therefore to be roughly flat in the run's period, since a 160-day window is a
160-day window whether the run covers one year or seven.

The first half holds. The second does not, and it is the shape of the miss that is the report.

## What happened

Peak RSS of the `vqapr run` process tree, sampled every 150 ms. One component
(`alpha-liquidity-003`: one field, a 160-day `CalendarLookback` on `equity-daily`), one machine,
nothing else running, each configuration run to completion.

**Period — 7x the sessions, 12% the memory.** Only `start` moves:

```
       start  sessions   wall s  peak GB
  2025-07-01       263     18.3     0.49
  2024-01-02       625     12.3     0.48
  2022-01-03      1116     14.9     0.48
  2019-01-02      1858     19.1     0.55
```

**Instruments — linear.** Only the declared list moves, same period, same component. 309 was run
first and last to rule out file-cache warming:

```
 declared   wall s  peak GB
      309     22.3     0.55
      100     10.6     0.35
       40      6.1     0.28
        5      3.6     0.23
      309     21.1     0.55
```

**Fields and cadence, for scale.** Three components that read `equity-daily` and nothing else, all
at 309 instruments:

```
alpha-liquidity-003   1 field x 160d   1d cadence, 1858 firings   0.55 GB   20.5 s
alpha-liquidity-002   2 fields x 200d  1d cadence, 1858 firings   0.68 GB   35.1 s
alpha-holder-044      2 fields x 220d  3M cadence,   30 firings   0.52 GB    9.7 s
```

## The arithmetic that made me look further

The marginal cost of going from 5 declared instruments to 309 is **0.32 GB**, and it does not
change when the period grows sevenfold.

- The declared window is 160 days x 1 field x 309 names = 49,440 values — about 0.4 MB as float64.
- The whole SOURCE history for those names is 2,839 sessions x 1 field x 309 names = 877,000
  values — about 7 MB as float64, and about **300 MB** as boxed Python objects in per-name
  containers.

0.32 GB measured against 300 MB predicted is the only one of those three that is the right size,
and it is the one that is also flat in the run's period and linear in the instrument count. I have
not read the package's source, so I am not naming a cause — but those are the numbers, and the two
shapes they are consistent with are (a) the read materialising each declared instrument's entire
source history rather than the declared window, and (b) values arriving as Python objects rather
than as arrays. They are independent, and either alone would show this signature.

## Reproduction

Reproduced every time, three separate probes, with the timing script parameterised only by the key
under test. Any project with a source much longer than the run and a lookback much shorter than
either should show it:

1. Register a datamodel component with a short `CalendarLookback` on a long source.
2. Run it with N instruments for several N; peak RSS is linear in N.
3. Run it with the same N over a short period and a long one; peak RSS barely moves.

## Impact

Worked around by lowering concurrency, which costs wall-clock: eight workers instead of the twelve
the 32 cores would carry, because 15.7 GB will not hold twelve. Whatever the cause, the ratio is
the point — a callback that needs 0.4 MB of window is costing 320 MB — so a project this size fits
in memory about 20 times over if the read holds the window rather than the history.

The cost is not only concurrency. It is also what a user can express: a seven-year daily backtest
and a one-year one cost the same memory, so there is no way to trade period for memory, which is
the first thing anyone reaches for when a run will not fit.

## What would have prevented it

Nothing to prevent — no refusal was wrong and no number came out wrong. What would help is the
read holding the declared window, and columns rather than boxed values. Failing either, a line in
`make-datamodel` saying memory scales with the instrument count and not with the lookback, so a
reader sizing a sweep knows which knob is the one that matters. I sized mine by cores and was
wrong by a factor of three.
