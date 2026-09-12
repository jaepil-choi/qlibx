# exp_235 -- the six scenarios behind the 0.12.0 scenario stepper

`docs/walkthroughs/2026-09-10-scenario-stepper-0.12.0.html` is built from `sys.setprofile` traces
of real commands on the sample door (`vqapr new sample`: ten names, 2022-01-03 ~ 2024-12-30),
never from a reading of the code. The tools are `exp_230`'s (`trace.py`, `summarize.py`,
`render.py`); this directory holds the declarations the traced project was given beyond what
`vqapr new sample` emits, the curated scenes, and the commands.

The six scenarios are the owner's (2026-09-10): register data / a registration that fails /
a DataModel that writes firm characteristics / a factor strategy on them / a stop-loss strategy
that remembers / an enhanced index from a saved alpha.

| # | scenario | declaration | command(s) |
|---|---|---|---|
| ① | 데이터 등록 | `sample.yaml` (the sample's own) | `register sample.yaml` |
| ② | 등록 오류 | `bad.yaml` (a field the file does not have); then the execution table rewritten with other bytes | `register bad.yaml` (exit 1) · `check sample-run` (`dataset.source_changed`) · `register sample.yaml` again |
| ③ | DataModel → firm characteristics | `features.yaml` + `features.py` (`momentum_5d` on `matrix()`) | `register` · `run sample-features-run` |
| ④ | factor strategy | `factor.yaml` + `factor.py` (long 3 / short 3, `Rebalance.signed`) + `exchange_signed.py` | `register` · `run sample-factor-run` |
| ⑤ | stop-loss with memory | `stoploss.yaml` + `stoploss.py` (`self.memory`: entry closes, stops fired) | `register` · `run sample-stoploss-run` |
| ⑥ | enhanced index from the saved alpha | `enhanced.yaml` + `enhanced.py` (reads `sample-factor-weights`) | `register` · `run sample-enhanced-run` · `list datasets` · `show run` |

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
```

The traces are not committed (a run trace is several MB). Read one with
`uv run python experiments/exp_230_the_spine_trace/summarize.py TRACE.json [--top N | --grep RE | --around IDX]`.

## Rendering the page

```bash
uv run python experiments/exp_230_the_spine_trace/render.py \
    experiments/exp_235_the_scenario_trace/scenes_0_12_0.py "$T" \
    docs/walkthroughs/2026-09-10-scenario-stepper-0.12.0.html
```

## What the traces showed (numbers the page quotes)

| command | calls | ms | note |
| --- | ---: | ---: | --- |
| register sample.yaml | 973 | 808 | `verify_roster` 418 ms (first parquet read), `verify_source` 210 + 82 ms; `execution_prices: [close]` |
| register bad.yaml | 427 | 63 | `dataset.field_missing` at `check_schema`; nothing written |
| check sample-run (file rewritten) | 86,499 | 3,624 | `dataset.source_changed` from a digest compare, 3.9 ms; `derived_agenda` 1,782 + 1,673 ms (735 sessions, derived twice) |
| register sample.yaml again | 1,294 | 700 | the same declaration re-measured; `_merge_dataset` replaces the measured half |
| register features.yaml / run sample-features-run | 647 / 12,820 | 71 / 1,151 | 16 sessions, 108 rows; first `compute` 349 ms (cold read) then ~1.8 ms; output through `verify_source` |
| register factor.yaml / run sample-factor-run | 1,058 / 31,617 | 105 / 2,384 | 10 sessions, 20 events; `decide` 12.8 then 7.4 ms; first fill 48 ms (3 long, 3 short); 60 weights published |
| register stoploss.yaml / run sample-stoploss-run | 1,424 / 76,545 | 164 / 9,742 | 37 sessions, 74 events; 8 stops, the last name sold 2022-02-23, cash 84,184,068.92 |
| register enhanced.yaml / run sample-enhanced-run | 1,315 / 34,410 | 109 / 2,534 | 9 sessions, 18 events; `decide` 27.3 then 9.7 ms (two windows) |
| list datasets / show run | 1,081 / 32 | 77 / 12 | six datasets, four with `produced_by_record`; the record carries `source_digest` per dataset read |

Stop-loss timeline (from the run's `vqapr.weight` table, names held per session): 9 (01-04) → 8 (01-05, K000005 out) → 7 (01-06, K000004) → 5 (01-11, K000002 · K000006) → 4 (01-19, K000007) → 3 (01-24, K000001) → 2 (01-25, K000009) → 1 (01-26 ~ 02-22, K000008 alone) → all cash from 02-23.

The first stop-loss draft re-entered every name on 2022-02-24 (an empty `entry` read as "the first decision"); the committed `stoploss.py` keeps an `entered` flag and sells the last name with an empty `Rebalance` rather than a `Hold`. Both fixes are the strategy's, not the framework's.
