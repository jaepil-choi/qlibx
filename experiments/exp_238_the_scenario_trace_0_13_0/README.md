# exp_238 -- the seven scenarios behind the 0.13.0 scenario stepper

`docs/walkthroughs/2026-09-10-scenario-stepper-0.13.0.html` is built from `sys.setprofile` traces
of real commands on the sample door (`vqapr new sample`: ten names, 2022-01-03 ~ 2024-12-30),
never from a reading of the code. The tools are `exp_230`'s (`trace.py`, `summarize.py`,
`render.py`) plus `trace_worker.py` here; the declarations are `exp_235`'s (unchanged since the
0.12.0 page, referenced by path from the scenes); this directory holds the curated scenes, the
commands, and two probes that measure what a trace cannot show.

The first six scenarios are the owner's (2026-09-10), the same as the 0.12.0 page; the seventh is
what 0.13.0 changed (record `236`): a `--jobs` batch bakes each dataset once and its workers map it.

| # | scenario | declaration | command(s) |
|---|---|---|---|
| ① | 데이터 등록 | `sample.yaml` (the sample's own) | `register sample.yaml` |
| ② | 등록 오류 | `bad.yaml`; then the execution table rewritten with other bytes | `register bad.yaml` (exit 1) · `check sample-run` (`dataset.source_changed`) · `register sample.yaml` again |
| ③ | DataModel → firm characteristics | `features.yaml` + `features.py` | `register` · `run sample-features-run` |
| ④ | factor strategy | `factor.yaml` + `factor.py` + `exchange_signed.py` | `register` · `run sample-factor-run` |
| ⑤ | stop-loss with memory | `stoploss.yaml` + `stoploss.py` | `register` · `run sample-stoploss-run` |
| ⑥ | enhanced index from the saved alpha | `enhanced.yaml` + `enhanced.py` | `register` · `run sample-enhanced-run` · `list datasets` · `show run` |
| ⑦ | `--jobs` batch, one cube per dataset | ④ and ⑤ again | `run sample-factor-run sample-stoploss-run --jobs 2 --force`; one worker traced in-process |

## The tree the traces were taken on

`develop` at `9b42b047` (0.13.0 stamped) with record `237`'s change to
`flow/declaration/judgments.py` in the working tree, uncommitted at the time (the ordering
judgment iterates `inclusive_slice(start, end)`). That is why `check sample-run` has 90,168 calls
against the 0.12.0 page's 86,499: `OperationAgenda.inclusive_slice` (#42201, 180.9 ms) is new.
The page says so on the ② scene and in the closing table.

## Regenerating the traces

One command per process, so `#idx` restarts at zero. `PYTHONUTF8=1` throughout.

```bash
S=/path/to/scratch; P=$S/sample; T=$S/traces
uv run vqapr new sample --out "$P"
cp experiments/exp_235_the_scenario_trace/declarations/* "$P"/
X="uv run python experiments/exp_230_the_spine_trace/trace.py"
$X "$T/01_register.json"          --project "$P" -- --project-root "$P" register "$P/sample.yaml"
$X "$T/02_register_bad.json"      --project "$P" -- --project-root "$P" register "$P/bad.yaml"     # exit 1
# rewrite execution.parquet with the last day dropped (duckdb COPY ... WHERE trade_at < max), then:
$X "$T/03_check_changed.json"     --project "$P" -- --project-root "$P" check sample-run           # source_changed
$X "$T/04_register_again.json"    --project "$P" -- --project-root "$P" register "$P/sample.yaml"  # re-measured
# restore the original bytes and register once more (untraced), then:
$X "$T/05_register_features.json" --project "$P" -- --project-root "$P" register "$P/features.yaml"
$X "$T/06_run_features.json"      --project "$P" -- --project-root "$P" run sample-features-run
$X "$T/07_register_factor.json"   --project "$P" -- --project-root "$P" register "$P/factor.yaml"
$X "$T/08_run_factor.json"        --project "$P" -- --project-root "$P" run sample-factor-run
$X "$T/09_register_stoploss.json" --project "$P" -- --project-root "$P" register "$P/stoploss.yaml"
$X "$T/10_run_stoploss.json"      --project "$P" -- --project-root "$P" run sample-stoploss-run
$X "$T/11_register_enhanced.json" --project "$P" -- --project-root "$P" register "$P/enhanced.yaml"
$X "$T/12_run_enhanced.json"      --project "$P" -- --project-root "$P" run sample-enhanced-run
$X "$T/13_list_datasets.json"     --project "$P" -- --project-root "$P" list datasets
$X "$T/14_show_run_enhanced.json" --project "$P" -- --project-root "$P" show run sample-enhanced-run
$X "$T/15_run_batch.json"         --project "$P" -- --project-root "$P" run sample-factor-run sample-stoploss-run --jobs 2 --force
uv run python experiments/exp_238_the_scenario_trace_0_13_0/trace_worker.py "$T/16_worker_factor.json" \
    --project "$P" --run sample-factor-run --with sample-stoploss-run
```

The driver's trace (15) ends at `in_workers`: the pool spawns its workers, and the profiler is
this process's. `trace_worker.py` bakes the batch's cubes the way `batch_cubes` does (untraced,
into a temporary directory under `.vqapr/`, removed afterwards) and runs the same worker function
the pool runs -- `run_registered_strategy(..., cubes=<dir>)` -- under the same profiler, so
`open_cube` and `panel_from_cube` appear with a call index and milliseconds (16). Pass the project
path as the CLI would (unresolved): the materialized datasets are registered under that spelling,
and a resolved UNC path is refused as a different physical declaration.

The traces are not committed (a run trace is several MB). Read one with
`uv run python experiments/exp_230_the_spine_trace/summarize.py TRACE.json [--top N | --grep RE | --around IDX]`.

## Measuring what the trace cannot show

Two numbers on the page are not in any trace and were measured on the same project instead:

- **The panel's block shape and scan bounds** (17 × 10, 11 × 10, 38 × 10, 10 × 10; the
  `_scan_bounds` lower bounds): `probe_panel.py` wraps `_scan_bounds`, `Panel.from_table` and
  `Panel.window` around a real `vqapr run ... --force` and prints what each returned. The runs are
  deterministic; the digests in `workspace.yaml` were the same before and after.
- **The cube files** (`close.npy` (735, 10) float64 58,928 B; `momentum_5d.npy` (12, 9)):
  `probe_cubes.py` runs `_bake_for_batch` for the two runs into a scratch directory and lists it.

```bash
uv run python experiments/exp_238_the_scenario_trace_0_13_0/probe_panel.py --project-root "$P" run sample-features-run --force
uv run python experiments/exp_238_the_scenario_trace_0_13_0/probe_cubes.py "$P" "$S/cubes" sample-factor-run sample-stoploss-run
```

## Rendering the page

```bash
uv run python experiments/exp_230_the_spine_trace/render.py \
    experiments/exp_238_the_scenario_trace_0_13_0/scenes_0_13_0.py "$T" \
    docs/walkthroughs/2026-09-10-scenario-stepper-0.13.0.html
```

Every frame's index was cross-checked against the trace's qualname and milliseconds before the
page was rendered (a one-off printing trace / idx / qualname / ms beside the frame's `fn`).

## What the traces showed (numbers the page quotes)

| command | calls | ms | note |
| --- | ---: | ---: | --- |
| register sample.yaml | 973 | 15,060 | `verify_roster` 14,246 ms: the session's first parquet read, on a CIFS home directory; `verify_source` 350 + 174 ms; `execution_prices: [close]` |
| register bad.yaml | 427 | 96 | `dataset.field_missing` at `check_schema`; nothing written |
| check sample-run (file rewritten) | 90,168 | 4,271 | `dataset.source_changed` from a digest compare, 8.5 ms; `derived_agenda` 2,020 + 1,839 ms (734 sessions, derived twice); `inclusive_slice` 181 ms (record 237) |
| register sample.yaml again | 1,294 | 1,175 | the same declaration re-measured; `_merge_dataset` replaces the measured half |
| register features.yaml / run sample-features-run | 647 / 13,673 | 168 / 2,772 | 16 sessions, 108 rows (12 × 9); panel 17 × 10 over 01-03 15:30 ~ 01-25 23:00; first `compute` 1,395 ms (scan 500, first numpy block 800), then ~2 ms |
| register factor.yaml / run sample-factor-run | 1,058 / 31,759 | 225 / 3,370 | 10 sessions, 20 events; panel 11 × 10; `decide` 42.9 then 6.7 ms; first fill 97 ms (3 long, 3 short); 60 weights published |
| register stoploss.yaml / run sample-stoploss-run | 1,112 / 77,553 | 180 / 8,810 | 37 sessions, 74 events; panel 38 × 10; the last name sold 2022-02-23, cash 84,184,068.92 |
| register enhanced.yaml / run sample-enhanced-run | 1,315 / 35,341 | 226 / 3,394 | 9 sessions, 18 events; two panels 10 × 10; `decide` 110.5 then 9.5 ms |
| list datasets / show run | 1,081 / 32 | 79 / 37 | six datasets, four with `produced_by_record`; the record carries `source_digest` per dataset read |
| run a b --jobs 2 --force (driver) | 3,659 | 3,250 | `bake` 451 ms (sample-features) + 128 ms (sample-prices, 735 × 10); `in_workers` 2,429 ms; the cube directory removed on return |
| worker (sample-factor-run, cubes baked) | 27,442 | 9,960 | `open_cube` 9.0 ms, `panel_from_cube` 21.1 ms; no `observation_table`, no `Panel.from_table`; first `decide` 73 ms |

Stop-loss timeline (from the run's `vqapr.weight` table, names held per session): 9 (01-04) → 8
(01-05, K000005 out) → 7 (01-06, K000004) → 5 (01-11, K000002 · K000006) → 4 (01-19, K000007) →
3 (01-24, K000001) → 2 (01-25, K000009) → 1 (01-26 ~ 02-22, K000008 alone) → all cash from 02-23.
Identical to the 0.12.0 page: the horizon-bounded panel changed no computed number.

Two figures on the 0.12.0 page were wrong and are corrected here: the datamodel's warm-up is four
sessions, not five (rows=[] at #8764 · #8867 · #8970 · #9073, then rows at #9420), and a session
contributes 9 rows, not 10 (K000010 has no six-close window in the period; 108 = 12 × 9).

## What the traces led to

Read for duplicate work rather than for the story, the same traces showed one `vqapr run`
reading the execution table's instant column five times (`distinct_values` x2 for the agenda,
`candidate_instants` x3 for the horizon), `check` hashing a changed file twice, a `--jobs` driver
loading every component twice to ask what it reads (`_reads` x4 for two runs), and one callback
normalizing its memory five times and hashing its envelope twice (`10_run_stoploss` #14668 ..
#14971). Records `238` and `239` close those; the page above still shows the traces as they were
taken, and a re-render on the fixed tree would show different call indices.
