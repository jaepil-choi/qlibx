# `show dataset --limit 0` does not return on a large source, and exhausted memory before it did

**Status: CLOSED by record `245` (2026-09-10, 0.14.2) — `--limit 0` returns no rows (a count is a count) for `show dataset` and `--table` alike; on a 4.2M-row source `--limit 0` answers in 0.86 s where it read every row into memory before.**

| | |
|---|---|
| vqapr version | `0.11.0` |
| installed from | `../../vqapr/dist/vqapr-0.11.0-py3-none-any.whl` |
| reported | 2026-09-10 |
| reporter | `kwam-enhanced-index/vqapr-enhanced-index-3`, agent session |
| python / OS | 3.12 / Windows 11, 15.7 GB RAM |

## What I was doing

Asking a registered dataset for its span and row count while sizing a memory investigation.
`--limit 0` because I wanted the metadata and none of the rows.

## What I expected

`--limit 0` to be the cheap form. It asks for zero items, so the cost should be the cost of the
registration plus whatever the header of the file gives — not a function of the file's size.

## What happened

On `equity-daily` — 430 MB, 8,676,023 rows, 4,975 instruments, `grain: instrument_instant`, a
plain (non-aggregated) registration — it does not return.

```
$ uv run --no-sync vqapr show dataset equity-daily --limit 0
# ... 5 minutes, then killed by `timeout 300`
exit=124
stdout bytes: 0
```

Nothing on stdout, nothing on stderr, no partial envelope. The first time I ran it — with less
free memory, because a build was running — it took the machine down instead: the process I was
piping it into died with `MemoryError` while reading its output, and free memory went from 5 GB to
under 1 GB.

The same command on a smaller dataset in the same workspace answers immediately:

```
$ uv run --no-sync vqapr show dataset residual-returns-k200 --limit 0
residual span: ['2019-09-27 16:00:00+09:00', '2026-07-20 16:00:00+09:00'] rows: 407669
```

`residual-returns-k200` is 23 MB. So the difference is the source's size, not anything about the
declaration: both are `instrument_instant`, both plain, both registered by this project.

## Reproduction

Reproduced twice on `equity-daily`, once ending in memory exhaustion and once in a five-minute
timeout with no output. `residual-returns-k200` answers in under a second every time.

1. Register a plain `instrument_instant` dataset over a few hundred megabytes of parquet.
2. `vqapr show dataset <id> --limit 0`.

I did not test where between 23 MB and 430 MB it stops being usable, and I stopped probing because
the machine was near its limit.

## Impact

`show dataset` is the command for "what is in this thing", and on the largest dataset in the
project — the one most worth asking about — it is the one command that cannot be run. I worked
around it by reading the parquet with pandas, which is the thing `show dataset` exists to save a
person from doing.

The memory-exhaustion form is worse than the timeout: it took the machine's free memory with it
while a 671-run build was going, and the build died.

## What would have prevented it

`--limit 0` short-circuiting before whatever pass it is doing. Failing that, `rows_total` coming
from parquet metadata rather than a scan, since row counts are in the footer of every parquet file.

0.11's release notes say that for an **aggregated** registration "the projected head evaluates the
whole grouping — a full pass over a large file, which is the cost of confirming the reduction
rule". That is a stated cost for aggregated registrations and this one is not aggregated, so
either the same pass is happening where it is not needed, or something else is. I have not read
the source and am not naming which.
