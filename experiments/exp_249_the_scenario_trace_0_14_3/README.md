# exp_249 -- the seven scenarios traced on 0.14.3, written to be read through

`docs/walkthroughs/2026-09-11-scenario-stepper-0.14.3.html` is built from `sys.setprofile` traces
of real commands on the sample door (`vqapr new sample`: ten names, 2022-01-03 ~ 2024-12-30),
never from a reading of the code. The tools are `exp_230`'s (`trace.py`, `summarize.py`,
`render.py`) plus `exp_238`'s `trace_worker.py`; the declarations are `exp_235`'s. This directory
holds the curated scenes and the commands.

What is different about this page: it is written for a reader who opens it and walks through it.
Every frame's upper text says in plain words what is happening and why (a door, a ledger, a lunch
box, a conductor and its workers); the function names, call indices and milliseconds are folded
beneath under "함수 이름과 호출 번호로 보면". The frames where 0.14.3 changed something (records
`246`-`248`) are marked `[0.14.3]`.

| # | scenario | command(s) |
|---|---|---|
| 1 | data registration | `register sample.yaml` |
| 2 | registration errors | `register bad.yaml` (exit 1) . `check sample-run` (`dataset.source_changed`) . `register sample.yaml` again |
| 3 | DataModel -> firm characteristics | `register` . `run sample-features-run` |
| 4 | factor strategy | `register` . `run sample-factor-run` |
| 5 | stop-loss with memory | `register` . `run sample-stoploss-run` |
| 6 | enhanced index from the saved alpha | `register` . `run sample-enhanced-run` . `list datasets` . `show run` |
| 7 | `--jobs` batch | `run sample-factor-run sample-stoploss-run --jobs 2 --force`; one worker traced in-process |

## The tree the traces were taken on

`develop` at `ab699614` (0.14.3 stamped), clean, on a local disk with a cold file cache (the
registration's first duckdb scan, `check_span`, took 2,100 ms; the second table's 17 ms).
Compare pages by call counts and by which calls exist, never by milliseconds.

## Regenerating the traces

The same sixteen commands as `exp_246/README.md`, with a fresh project directory and
`PYTHONUTF8=1`; the traces are not committed. Every frame's index was cross-checked against the
trace's qualname and milliseconds before the page was rendered (a one-off printing trace / idx /
qualname / ms beside each frame's title; all 53 agree).

```bash
uv run python experiments/exp_230_the_spine_trace/render.py \
    experiments/exp_249_the_scenario_trace_0_14_3/scenes_0_14_3.py "$T" \
    docs/walkthroughs/2026-09-11-scenario-stepper-0.14.3.html
```

## What the traces showed (numbers the page quotes)

| command | calls | 0.14.2 calls | what 0.14.3 changed on it |
| --- | ---: | ---: | --- |
| register sample.yaml | 973 | 973 | nothing |
| register bad.yaml | 427 | 427 | nothing |
| check sample-run (file rewritten) | 48,329 | 48,326 | the sessions read for the run period -- the run is the whole table, so 734 as before |
| register sample.yaml again | 1,294 | 1,294 | nothing |
| run sample-features-run | 8,158 | 10,336 | `_local_date` x18 (was x735): the datamodel's `days_from` table read for the period |
| run sample-factor-run | 24,374 | 27,853 | `_actual_source_refs` x10 (was x20), `inputs()` x7 (was x15), `_local_date` x12 (was x734) |
| run sample-stoploss-run | 61,659 | 68,066 | `_actual_source_refs` x37 (was x71), `inputs()` x7 (was x42), `_local_date` x38 |
| run sample-enhanced-run | 27,311 | 31,594 | the same three |
| list datasets / show run | 1,081 / 32 | 1,081 / 32 | nothing |
| run a b --jobs 2 --force (driver) | 3,492 | 3,492 | nothing in the driver |
| worker (sample-factor-run, cubes baked) | 23,353 | 26,832 | the same three; `verify_run` #16 still first |

`heartbeat` is called as often as before (once per record chunk); what changed is inside it -- the
lock is touched at most once a second -- and the profiler records only vqapr frames, so the page
says so in the closing table and points at the unit test that counts the touches.
