# exp_246 -- the seven scenarios traced again on 0.14.2

`docs/walkthroughs/2026-09-10-scenario-stepper-0.14.2.html` is built from `sys.setprofile` traces
of real commands on the sample door (`vqapr new sample`: ten names, 2022-01-03 ~ 2024-12-30),
never from a reading of the code. The tools are `exp_230`'s (`trace.py`, `summarize.py`,
`render.py`) plus `exp_238`'s `trace_worker.py` and the two probes; the declarations are
`exp_235`'s (unchanged since the 0.12.0 page, referenced by path from the scenes). This directory
holds the curated scenes and the commands. The seven scenarios are `exp_238`'s; what the page is
for is showing where the 0.14.x changes sit on them:

- **one door** (`verify_run`, records `240`-`241`): `check`, `run` and the `--jobs` worker pass the
  same function, and the judgments and the freeze inside it read one `RunFacts`;
- **each fact once** (records `238`-`240`): the 3-year `check` derives its agenda once, not twice;
  a run's freeze takes the agenda the judgments derived in 0.07 ms;
- **the run takes what the door loaded** (`RunResources`, record `242`): no re-import of the
  strategy, venue or rules and no re-scan of the horizon at run start;
- **the worker is judged** (record `240`): the worker trace begins with `verify_run` -> `judgments`;
- **memory framed once** (record `239`): `_candidate_callback_state` -> `prepare_callback(prepared=)`.

No computed number changed (showcase record digest 83/83 at 0.14.2); the fills, the accounts and
the published weight datasets on the page are the 0.13.0 page's.

| # | scenario | declaration | command(s) |
|---|---|---|---|
| 1 | data registration | `sample.yaml` (the sample's own) | `register sample.yaml` |
| 2 | registration errors, and the one door | `bad.yaml`; then the execution table rewritten with other bytes | `register bad.yaml` (exit 1) . `check sample-run` (`dataset.source_changed`) . `register sample.yaml` again |
| 3 | DataModel -> firm characteristics | `features.yaml` + `features.py` | `register` . `run sample-features-run` |
| 4 | factor strategy | `factor.yaml` + `factor.py` + `exchange_signed.py` | `register` . `run sample-factor-run` |
| 5 | stop-loss with memory | `stoploss.yaml` + `stoploss.py` | `register` . `run sample-stoploss-run` |
| 6 | enhanced index from the saved alpha | `enhanced.yaml` + `enhanced.py` | `register` . `run sample-enhanced-run` . `list datasets` . `show run` |
| 7 | `--jobs` batch: the worker judged, one cube per dataset | 4 and 5 again | `run sample-factor-run sample-stoploss-run --jobs 2 --force`; one worker traced in-process |

## The tree the traces were taken on

`develop` at `22b433bf` (0.14.2 stamped), clean. The project lived on a local disk (the session's
scratchpad), not on the CIFS home directory the 0.12.0 and 0.13.0 pages were traced on, so the
absolute milliseconds are far smaller than theirs (the whole registration 1,028 ms against
15,060 ms). Compare pages by call counts and by which calls exist, never by milliseconds.

## Regenerating the traces

One command per process, so `#idx` restarts at zero. `PYTHONUTF8=1` throughout. Pass the project
path as the CLI would (unresolved).

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

The traces are not committed (a run trace is several MB). Read one with
`uv run python experiments/exp_230_the_spine_trace/summarize.py TRACE.json [--top N | --grep RE | --around IDX]`.
The panel shapes and the cube files quoted on the page come from `exp_238`'s `probe_panel.py` and
`probe_cubes.py` run on the same project; both reproduced the 0.13.0 numbers (17 x 10, 11 x 10,
38 x 10, 10 x 10 + 10 x 10; `close.npy` (735, 10) 58,928 B; `momentum_5d.npy` (12, 9)).

## Finding the frames again

The 0.13.0 scenes were the starting point. Their call indices do not carry over (the door moved
calls), so each frame was re-found in the new trace by its function -- the old page's rendered
`S.push` payloads give every frame's `file:line`, the definition name at that line in the old
tree (`git show 9b42b047:FILE`) gives the qualname, and the new trace lists the candidates with
their locals (instant, event, rows) to pick the right occurrence. A one-off printed, for every
frame of the new scenes, the trace / index / qualname / ms beside the frame's title before the
page was rendered; all 53 agree.

## Rendering the page

```bash
uv run python experiments/exp_230_the_spine_trace/render.py \
    experiments/exp_246_the_scenario_trace_0_14_2/scenes_0_14_2.py "$T" \
    docs/walkthroughs/2026-09-10-scenario-stepper-0.14.2.html
```

## What the traces showed (numbers the page quotes)

| command | calls | ms | 0.13.0 calls | note |
| --- | ---: | ---: | ---: | --- |
| register sample.yaml | 973 | 1,028 | 973 | unchanged; `check_span` 443 ms is the process's first duckdb scan, `verify_roster` 351 ms its first pyarrow read |
| register bad.yaml | 427 | 67 | 427 | `dataset.field_missing` at `check_schema`; nothing written |
| check sample-run (file rewritten) | 48,326 | 2,261 | 90,168 | `verify_run` #336; `derived_agenda` #365 once, 1,922 ms (0.13.0: 2,020 + 1,839); `dataset.source_changed` from one digest compare (#45886, 0.5 ms), the freeze gets the stored exception (#48204, 6 ms) |
| register sample.yaml again | 1,294 | 686 | 1,294 | the same declaration re-measured; `_merge_dataset` replaces the measured half |
| register features.yaml / run sample-features-run | 647 / 10,336 | 71 / 1,041 | 647 / 13,673 | `verify_run` #470 (judgments 239 + freeze 12 ms; 0.13.0 ran `preflight_run` twice, 462 + 190 ms); `RunResources.of` #4160; panel 17 x 10; first `compute` 409 ms (scan 337), then ~2 ms; 108 rows |
| register factor.yaml / run sample-factor-run | 1,058 / 27,853 | 99 / 2,252 | 1,058 / 31,759 | `verify_run` #722: `RunFacts.agenda` served to the freeze in 0.07 ms (#4026); `RunResources.of` #4471 (0.8 ms, three 0.06 ms lookups); `registered_roster` #4496 407 ms (first pyarrow read, by design); `decide` 33.3 then 7.2 ms; first fill 50.9 ms (3 long, 3 short); 60 weights published |
| register stoploss.yaml / run sample-stoploss-run | 1,112 / 68,066 | 97 / 7,117 | 1,112 / 77,553 | `_candidate_callback_state` #9804 -> `prepare_model_state` once -> `prepare_callback(prepared=)` #10077; panel 38 x 10; last name sold 2022-02-23 (-52), cash 84,184,068.92 (v34) |
| register enhanced.yaml / run sample-enhanced-run | 1,315 / 31,594 | 106 / 2,196 | 1,315 / 35,341 | `verify_run` #1040; two panels 10 x 10; `decide` 80.7 then 9.7 ms |
| list datasets / show run | 1,081 / 32 | 79 / 22 | 1,081 / 32 | six datasets, four with `produced_by_record`; readers touch the workspace and the record only |
| run a b --jobs 2 --force (driver) | 3,492 | 1,693 | 3,659 | `batch_reads` #1064 once (`_reads` x2, was x4) -> `require_independent_batch` -> `batch_cubes` #1244: `bake` 376 ms (sample-features, the first scan) + 95 ms (sample-prices, 735 x 10); `in_workers` 1,094 ms; no `verify_run` in the driver |
| worker (sample-factor-run, cubes baked) | 26,832 | 1,679 | 27,442 | `verify_run` #16 -> `judgments` #18 (309 ms) -> `preflight_run` #3394 -> `RunResources.of` #3847 (the worker is judged, record 240); `open_cube` #4729 1.9 ms, `panel_from_cube` #4755 2.2 ms; no `observation_table`, no `Panel.from_table`; first `decide` 24.4 ms |

One thing the traces show that no record changed: `registered_roster` -> `verify_roster` at run
start costs 354-407 ms in each single-process run (08 #4496, 10 #7196, 12 #4858) and 19.9 ms in
the worker (16 #3863). It is the process's first pyarrow parquet read, and it is by design read
fresh every run (issue 009: a roster grows daily); the page says so on the scene 4 frame.

## What the traces led to

Read for duplicate work rather than for the story (the owner's question, 2026-09-10), the same
traces showed each callback deriving its source refs twice (`_actual_source_refs` x20 in 08, x71
in 10) and asking `inputs()` on every decision (x15, x42), a ten-session run reading the whole
three-year instant column to keep ten instants (`distinct_values` #752), and the record writer
touching the run lock on every chunk (`heartbeat` x110, x404). The one-callback campaign
(`docs/refactoring/2026-09-10-the-one-callback-campaign.md`, records `246`-`248`, 0.14.3) closes
those four; three more candidates were looked at and left (the exchange's memory framed at every
fill is the contract; `verify_roster`'s cost is the pyarrow import the first record chunk would pay
instead; the as-loaded re-hash is record 242's decision). Re-traced on the fixed tree with `--force`
(`traces_after/`, not committed): `_actual_source_refs` 20 -> 10 and 71 -> 37, `inputs` 15 -> 6
and 42 -> 6, instants read 735 -> 11 and 735 -> 38, calls 27,853 -> 25,913 and 68,066 -> 63,021.
The page above still shows the traces as they were taken.
