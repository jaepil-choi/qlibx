# exp_230 -- the spine trace behind the 0.11.0 stepper

`docs/walkthroughs/2026-09-10-spine-stepper-0.11.0.html` is built from `sys.setprofile` traces of
real commands, never from a reading of the code. Every frame on that page names the trace and
the call index it stands on; `render.py` fills in the definition line, the qualified name and the
milliseconds from the trace and reads the code window from the tree. This directory holds the
three tools, the curated scenes, and the declarations the traced project was given beyond what
`vqapr new sample` emits.

## Regenerating the traces

One command per process, so `#idx` restarts at zero. `PYTHONUTF8=1` throughout (the sample
project lives under a non-ASCII home directory on the machine the traces were taken on).

```bash
P=/path/to/scratch/sample; T=/path/to/scratch/traces
uv run vqapr new sample --out "$P"                                  # the sample door
cp experiments/exp_230_the_spine_trace/declarations/* "$P"/
X="uv run python experiments/exp_230_the_spine_trace/trace.py"
$X "$T/01_register.json"          --project "$P" -- --project-root "$P" register "$P/sample.yaml"
$X "$T/02_check.json"             --project "$P" -- --project-root "$P" check sample-run
$X "$T/03_register_features.json" --project "$P" -- --project-root "$P" register "$P/features.yaml"
$X "$T/04_register_short.json"    --project "$P" -- --project-root "$P" register "$P/short.yaml"
$X "$T/05_check_short.json"       --project "$P" -- --project-root "$P" check sample-run-short
$X "$T/06_run_short.json"         --project "$P" -- --project-root "$P" run sample-run-short
$X "$T/07_run_features.json"      --project "$P" -- --project-root "$P" run sample-features-run
$X "$T/08_list_runs.json"         --project "$P" -- --project-root "$P" list runs
$X "$T/09_show_run.json"          --project "$P" -- --project-root "$P" show run sample-run-short
$X "$T/10b_show_strategy_usage.json" --project "$P" -- --project-root "$P" show strategy sample-run-short
$X "$T/10_show_strategy.json"     --project "$P" -- --project-root "$P" show strategy sample-run-short/sample-reversal-5d@fb2406b9
$X "$T/12_list_strategies.json"   --project "$P" -- --project-root "$P" list strategies --run sample-run-short
$X "$T/11_register_stale.json"    --project "$P" -- --project-root "$P" register "$P/stale.yaml"   # exits 1 on purpose
```

`short.yaml` names the shipped `no_short.py` by an absolute path in the checkout it was traced
from; point it at your own `src/vqapr/compliance/builtin/no_short.py` before registering. The
strategy fingerprint in the `show strategy` command (`@fb2406b9`) is the sample strategy's; read it
from the `run` envelope if the sample's bytes have changed.

The traces are not committed: `06_run_short.json` alone is 8 MB and `02_check.json` 18 MB.

## Reading a trace

```bash
M="uv run python experiments/exp_230_the_spine_trace/summarize.py"
$M "$T/06_run_short.json"                                   # argv, exit, calls, envelope, files
$M "$T/06_run_short.json" --top 40                          # cumulative ms by qualname
$M "$T/06_run_short.json" --grep 'RunLoop|MarketClock' --maxdepth 12 --limit 80
$M "$T/06_run_short.json" --around 22387 --width 12
```

Qualnames are bare (`run`, `apply`, `_apply`); match files with `cli/run` rather than `cli\.run`.
The `ms` column is the profiler's own clock and is inflated by the profiler; compare within one
trace only. The first parquet read of a process dominates the absolute numbers on a cold cache.

## Rendering the page

```bash
uv run python experiments/exp_230_the_spine_trace/render.py \
    experiments/exp_230_the_spine_trace/scenes_0_11_0.py "$T" \
    docs/walkthroughs/2026-09-10-spine-stepper-0.11.0.html
```

`scenes_0_11_0.py` is executed with `REPO` bound to the tree; a frame quotes its code window with
`at(file, needle, n)` (an anchor line, not a line number) or `("def", n)` (from the definition the
profiler recorded). The page's CSS and JS come from the 0.6.0 stepper, with the header, the map,
the scenes and the closing table replaced.

## What the 0.11.0 traces showed (numbers the page quotes)

| command | calls | ms | note |
| --- | ---: | ---: | --- |
| register sample.yaml | 945 | 15,052 | `check_span` 9,463 ms: the first parquet read on this machine |
| check sample-run-short | 8,137 | 11,789 | two cold duckdb scans of the execution table, 11,460 ms |
| run sample-run-short | 45,436 | 5,005 | 32 events, `EventLoop.run` 2,240 ms, `_seal` 789 ms |
| run sample-features-run | 20,128 | 1,724 | 16 sessions, first `compute` 843 ms, then 4-15 ms |
| list runs / show run / show strategy / list strategies | 689 / 30 / 27 / 30 | 59 / 13 / 11 / 12 | readers touch the record files only |
| register stale.yaml | 805 | 334 | `component.signature_invalid` (422), nothing staged |

Inside the strategy run: `observation_rows` 1, `execution_window_table` 1, `exact_execution_snapshot`
0, `append_chunk` 203, `_deliver` 71, `_spill` 0, `heartbeat` 235, `checkpoint` 1, `_write_parquet` 4.
