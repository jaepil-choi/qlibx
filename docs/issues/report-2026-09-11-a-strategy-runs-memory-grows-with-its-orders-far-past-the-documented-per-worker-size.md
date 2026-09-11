# A daily strategy run's memory grows with the orders it places — to 3.7 GB, where the documented sizing rule gives about 0.2 GB

**Status: CLOSED 2026-09-11 — records `254`–`257`** (fixed on the owner's instruction, unnumbered). Measured on a synthetic 300-name daily book, the peak came after the run (every fill row read back as a dict, `254`); the loop's growth was each fill's evidence held three times over (`256`); the spill raised the peak it was meant to bound (`255`); and numpy's BLAS reserved ~0.8 GB per process on a 32-core machine (`257`: one thread per `--jobs` worker). 300k fills: 1.95 → 1.43 GB peak private.

| | |
|---|---|
| vqapr version | `0.14.2` (`vqapr skill list` → `package_version`) |
| installed from | `../../vqapr/dist/vqapr-0.14.2-py3-none-any.whl` |
| reported | 2026-09-11 |
| reporter | `kwam-enhanced-index/vqapr-enhanced-index-3`, agent session |
| python / OS | 3.12.13 / Windows 11 (10.0.26200), 15.7 GB RAM |

## What I was doing

Running 905 strategy runs, one per alpha: each is a factor-hedged signed book over 309 KOSPI 200
names on the academic venue, deciding every session at 15:29 and filling at the 15:30 close,
2019-01-02 → 2026-07-28 (about 1,860 sessions). Each run reads 13 numeric fields: one alpha score,
six residual betas and six factor-leg weights, every one through a 10-day `CalendarLookback`. I sized
`--jobs` by the documented rule. The machine ran out of memory, so I measured one run on its own.

## What I expected

Two statements in the shipped skills:

- `run-backtest/SKILL.md` §5: *"Memory per worker is therefore its own period × lookback ×
  instruments (once, shared, for a whole-universe run) on top of about 130 MB of interpreter; size
  `--jobs` by that, not by core count."* For this run: 13 fields × ~1,870 instants × 309 names ×
  8 bytes ≈ 60 MB, plus 130 MB — **about 0.2 GB**.
- `run-backtest/references/watching-and-failures.md`: *"Rows stay in memory while the run executes
  and land once, when it ends … a part is written whenever the buffer passes 256 MB."* From that I
  expected the recorded rows to cost at most a few hundred MB at any moment.

## What happened

I measured the **same registered component** (`gate-beta-001`) in runs that differ only in `end`,
and a second component, `probe-hold`, which has the identical `inputs()` and returns `Hold` at every
decision, over the full horizon. Each run ran alone, as `uv run vqapr run <id> --force`. I sampled
the process tree's private bytes and working set every 0.5 s with `psutil`. The row counts are from
the run's own `vqapr.weight`, `vqapr.fill` and `vqapr.account` tables.

| run | `end` | weight rows | fill rows | account rows | peak private | peak working set | wall |
|---|---|---:|---:|---:|---:|---:|---:|
| `probe-hold` (never trades) | 2026-07-28 | 0 | 0 | 1,858 | **1.08 GB** | 0.37 GB | 25 s |
| `probe-gate-2020` | 2020-12-31 | 76,477 | 76,527 | 76,969 | **1.54 GB** | 0.79 GB | 12 s |
| `probe-gate-2021` | 2021-12-31 | 142,442 | 142,533 | 143,182 | **1.90 GB** | 1.17 GB | 18 s |
| `probe-gate-2022` | 2022-12-31 | 210,650 | 210,892 | (see below) | **2.35 GB** | 1.54 GB | 26 s |
| `probe-gate-2022` `--no-account-positions` | 2022-12-31 | 210,650 | 210,892 | 988 | **2.40 GB** | 1.57 GB | 30 s |
| `probe-gate-2023` | 2023-12-31 | 278,221 | 279,139 | 280,169 | **2.66 GB** | 1.83 GB | 89 s |
| `gate-beta-001` (full) | 2026-07-28 | 455,607 | 460,192 | 1,858 † | **≥ 3.73 GB** | — | ~48 s |

† Measured with `--no-account-positions`. My harness killed the process at 1.2 GB available, 48 s
in. Its `vqapr.weight` and `vqapr.fill` tables already ran to 2026-07-28 and its `writes` dataset had
been published, so the kill came at or after the end, and 3.73 GB is a floor. The same run without
the flag reached 3.70 GB at 44 s and was also killed. Row counts are from its record.

Read the table in three ways:

- **Against the hold run.** Minus the never-trading run's 1.08 GB, the increment grows in step with
  the rows: 0.46 GB at 77k fills, 0.82 at 143k, 1.27 at 211k, 1.58 at 279k, ≥ 2.65 at 460k. That is
  about **5.7–6.0 KB per fill** (with one weight row beside each), and it is roughly linear.
- **Against the flag.** `--no-account-positions` drops the account table from ~211k rows to 988.
  Peak private did not fall (2.35 → 2.40 GB). Whatever grows is not the account-position rows.
- **Over time.** In `probe-gate-2023` private sat at about 1.0 GB for its first ~57 s, then climbed
  from 1.06 to 2.45 GB in the next ~28 s. Samples as (seconds, private GB, working set GB, available
  GB):
  `[57.0, 1.062, 0.342, 3.22], [64.1, 1.388, 0.672, 2.86], [71.2, 1.845, 1.126, 2.46], [78.4, 2.283, 1.56, 1.99], [85.5, 2.446, 1.692, 1.89]`.
  `probe-hold` stayed at 1.01–1.08 GB throughout.

The envelope of `probe-gate-2022` (no flag), verbatim:

```
{"ok": true, "roster": {"by_kind": {"etf": 2, "stock": 309}, "digest": "33ec5827e98e07a17113df74be60baa734f6a2cefa2266bc9b6bac399f520b22", "instruments": 311, "known": true, "tables": ["etf", "stock"]}, "run_id": "probe-gate-2022", "stage": "run.complete", "store_root": "D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\vqapr-enhanced-index-3\\.vqapr", "strategies": {"gate-beta-001": {"account_version": 785, "contract": {"accepted_intents": 785}, "fills": {"dealt": 210349, "never_filled": [], "orders": 210892, "partial": 0, "reasons": {"absent": 112, "nontradable": 431}, "zero_dealt": 543}, "fingerprint": "68a78237ea8c3fe567dc9fd2a7cbb59e9537a4fc131256160f45fac0e938ba9a", "occurrences": 1976, "record": "gate-beta-001@68a78237", "status": "completed", "tables": ["vqapr.account", "vqapr.fill", "vqapr.weight"], "timing": {"callback": 7.627131, "due": 8.004143, "simulation.due.account_commit": 0.649892, "simulation.due.account_mark": 1.355441, "simulation.due.account_preparation": 1.830385, "simulation.due.exchange_execution": 0.956223, "simulation.due.feedback_candidate": 0.005057, "simulation.due.feedback_publication": 0.208719, "simulation.due.instrument_declaration": 0.040558, "simulation.due.order_planning": 1.850482, "simulation.due.snapshot": 0.389779, "simulation.due.valuation_mark": 0.33657, "simulation.due.valuation_selection": 0.169651, "total": 15.937081}}}, "workspace_root": "D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\vqapr-enhanced-index-3", "writes": "probe-gate-2022-weights"}
```

Every run above returned `ok: true` except the full run, which I killed. None of them was refused.

## Reproduction

The runs read this project's datasets, which come from a private warehouse, so a maintainer cannot
rerun them as they are. The shape should not need this data: any daily signed book that trades most
of ~300 names every session places ~300 orders a session. I did **not** try a synthetic
reproduction.

1. Register a strategy that returns `Rebalance.signed(...)` over ~300 names every session, and a
   twin with the same `inputs()` that returns `Hold`.
2. Declare runs of the first with `end` one, two, three and four years after `start`, and one run
   of the twin over the longest span.
3. `vqapr run <id> --force` each alone and watch the process's private bytes.

Each run was measured once. The full-horizon run was measured twice, with and without
`--no-account-positions`: 3.73 GB and 3.70 GB when killed. A third attempt, inside a
`vqapr run ... --jobs 1` batch, was killed at 3.5 GB by my own memory watchdog.

## Impact

Worked around, at a large cost in time:

- **The documented `--jobs` rule overcommits by more than an order of magnitude** for a book like
  this. At 0.2 GB a worker it says a dozen workers fit on this machine. One does. Two workers were
  refused room by my own watchdog, which kills its batch when the machine falls below 1.5 GB
  available. That watchdog exists only because the first sizing, by the rule, took the machine to
  1.1 GB.
- **The 905 runs are serialised**, about 50 s each (≈ 12.5 h). Each needs ~3.7 GB of headroom, so
  the batch also waits whenever the other programs on a 15.7 GB machine hold more than ~10 GB.
- **`--no-account-positions` looked like the lever and is not.** It removed ~210k account rows and
  saved nothing measurable.

No number in any result is affected; every completed run is `ok: true` and its record is complete.

## What would have prevented it

- A sizing sentence for **strategy** runs that names what they grow with. From here the observation
  is ~6 KB per order/fill once a run starts trading, plus a ~1 GB floor for this set of inputs, not
  "period × lookback × instruments + 130 MB". The quoted rule reads as if it covers both kinds of run.
- If the 256 MB spill in `watching-and-failures.md` is meant to bound a run's memory, a
  measurement that shows it holding on a run of this size. Or, if it bounds only one buffer, a
  sentence saying what else grows.
