# `vqapr run --jobs N` does not parallelise datamodel runs: one process, one model at a time

**Status: CLOSED 2026-09-10 -- record `230`.** Confirmed as reported: from record `201` the CLI put
only strategy runs in the pool and ran datamodel runs one at a time in the parent, because the
datamodel worker raises its refusal and `in_workers` ended the whole batch on the first one.
`in_workers` now returns what each worker raised as that run's entry, both kinds go through the
pool, the batch envelope carries `jobs` (the processes actually used), and a batch in which one
run reads what another in it writes is refused whole before anything is spawned
(`run.batch_dependent`, owner decision). Kept unnumbered: `095`-`097` were taken the same day by
the owner's spine-trace issues, and the owner assigns numbers.

| | |
|---|---|
| vqapr version | `0.11.0` |
| installed from | `../../vqapr/dist/vqapr-0.11.0-py3-none-any.whl` |
| reported | 2026-09-10 |
| reporter | `kwam-enhanced-index/vqapr-enhanced-index-3`, agent session |
| python / OS | 3.12 / Windows 11, 32 logical cores |

## What I was doing

Running 671 alpha datamodel runs — one model each, since 0.10 — over 1,671 trading days. Each is
independent: different component, different output dataset, same inputs.

## What I expected

`--jobs` to run them in parallel. `vqapr run --help`:

> Several run ids run several runs, **in a single process or in parallel under --jobs**.
>
> `--jobs JOBS`  run the given runs in **this many processes**; each builds its own panels

## What happened

One process, one run at a time, whatever `--jobs` says. Timed on this machine, eight datamodel
runs of comparable cost, back to back, nothing else running:

```
$ vqapr run alpha-combo-024 ... alpha-combo-031 --jobs 1     # 8 runs
jobs=1 : 8 runs, 347 s

$ vqapr run alpha-combo-032 ... alpha-combo-039 --jobs 8     # 8 runs
jobs=8 : 8 runs, 318 s
```

8% apart, which is the spread between two batches of these runs. Sampling `tasklist` every four
seconds throughout a `--jobs 8` invocation showed the process count flat — one `vqapr run`
process, ~1.2 GB resident, no workers:

```
14:31:58 procs=10        # 8 unrelated to this run, + `uv run` + `vqapr`
14:32:02 procs=10
...  (15 samples over 60 s, all 10)
```

For the full sweep, `--jobs 16` sustained **1.07 runs a minute** — 43 s per run, which is exactly
one run at a time.

## Reproduction

Reproduced every time (three timings, plus the 671-run sweep):

1. Register several datamodel runs of similar cost.
2. `vqapr run <id> ... --jobs 1`, then a different equal-sized set with `--jobs N`.
3. Wall time is the same, and the process count does not rise.

I have not tested strategy runs, so this report claims nothing about them. A `BrokenProcessPool`
raised by a 12-strategy 0.9.0.dev1 run under `--jobs 4` suggests a pool exists on some path.

## Impact

Worked around. The workaround is what makes the size of it clear: launching several `vqapr run`
invocations concurrently — the shell doing what `--jobs` says it does — takes the same work from
**43 s per run to 3.6 s per run**, a 12x speedup on a 32-core machine:

```
  4/4 ok  [24/576]  3.5s/alpha  32 min left
  4/4 ok  [28/576]  3.1s/alpha  28 min left
```

So the runs parallelise cleanly, and nothing about the workspace prevents it: the exclusive lock
is taken by registration, not by execution, and concurrent runs of already-registered ids do not
contend. For this sweep the difference is 8 hours against 40 minutes.

The cost before I measured it was worse than the time. `--jobs 16` reported the same throughput as
`--jobs 1`, and I read the 20-run probe's 37 s per run as "10 in parallel, 370 s each" rather than
"one at a time, 37 s each" — two readings of one number, and I picked the wrong one because the
flag said the first. I only found it by counting processes.

## What would have prevented it

`--jobs` spreading datamodel runs the way its help says it does. Failing that, saying which kinds
of run it spreads, and — since a caller cannot see a pool that is not there — having the envelope
state the concurrency it actually used, the way `vqapr run` already states the roster it read.
