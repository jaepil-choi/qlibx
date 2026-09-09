# 148 — a datamodel is a run, and a run declares its sessions and one wall time

**Closes:** `docs/issues/archive/059` (a materialization holds every row and every access record until
the end, writes a 478 MB lineage, prints nothing). **Step:** 7 of
`docs/refactoring/2026-09-03-the-deletion-campaign.md` (decision D1, and the three owner
decisions taken on 2026-09-03 when the step opened: D5, D6, D7).
**Authority:** the owner, three times that day — *"datamodel은 account 없고 execution 없는
strategy처럼 돌아야 해. 둘은 매우 유사해야 하고 하나의 baseclass를 공유해야 해"*; *"전략은 매일
호출되고 전략이 한달에 한 번 돌고싶으면 전략 내에서 entry condition을 그렇게 넣으면 되잖아"*;
*"value at monitor at 은 애초에 왜 필요한거야? right after execution 에 valuation 이 도는거
아니야? … execution table의 해상도 이상으로 들어갈 수는 없잖아."* And the campaign's rule: a key
is made when it is used, never ahead of time.

## Why this exists

Three nouns stood between an author and a run, and none of them was the author's.

- **The agenda.** A run named an agenda per strategy through a `strategy_configs` binding, a
  valuation agenda through a `valuation:` block and a monitoring agenda through `monitoring:`;
  each was a registered declaration with an id, a role and a cadence. The owner found the id
  confusing and the cadence misplaced: a strategy that wants to act monthly is a strategy with a
  monthly rule, not a monthly agenda.
- **The valuation and monitoring clocks.** Two agendas said when the book was measured and
  judged. But the book is measured at the instant the venue fills -- the account had been marked
  and committed at every fill all along -- and a standalone valuation occurrence was a reporting
  row restating the same mark under another label. Monitoring likewise has nothing to judge
  between commits.
- **The materialization.** A DataModel ran through `materialize()`: its own loop over a list of
  instants from a spec file, every row and every access record held until the end, one parquet
  and a lineage file written at once, a record of its own kind. `059` measured it at 3 GB of
  RSS, a 478 MB lineage and twenty silent minutes.

## What changed

### The run declares its sessions and one wall time (M1, commit `7b9c781c`)

```yaml
runs:
  krx-2024:
    instruments: [A005930, A000660]
    start: "2024-01-02T00:00:00+09:00"
    end:   "2024-12-31T15:30:00+09:00"
    sessions_from: prices          # every session that dataset has; or `sessions: [...]`
    timezone: Asia/Seoul
    at: "15:29"                    # every strategy is called here, every session
    exchange: my-venue
    execution_input: my-exec
    initial_account: {cash: "1000000", mode: LONG_ONLY, positions: {}}
    strategies:
      my-alpha: {constraints: [no-short]}
```

- `RunDefinition` / `RunDocument` carry `sessions_from | sessions`, `timezone`, `at`; the
  `valuation` and `monitoring` blocks, `ValuationConfig`, `MonitoringPolicy` and their modules
  are deleted. `preflight.derived_agenda` builds the one internal `OperationAgenda`
  (`<run_id>.sessions`, one occurrence per session at `at`) that the flow already ran on;
  `OperationAgenda.daily` owns the occurrence ids and the DST proof.
- The loop dispatches callbacks and due executions only. The NAV row of `vqapr.account` rides
  the mark transition (`prepare_marked` / `prepare_valuation_only` take a recorder), so a marked
  account and its recorded NAV are one commit; monitoring runs from
  `ValuationPhase.monitor_after_commit` right after each commit, and its findings reach
  `vqapr.monitoring` stamped at the fill instant. Both rows stamp `event_time` in the agenda's
  zone, as every other table does (`058`).
- `agendas:` and `strategy_configs:` leave the document, the templates, `list` and `rm`;
  `register_agenda`, `register_strategy_config`, `StrategyConfig`, `ValuationConfig`,
  `MonitoringPolicy`, `OperationAgenda` leave `vqapr.public`. A 0.3.0 `workspace.yaml` still
  opens: the four retired sections are read and dropped, and a run entry in the old shape is
  refused naming the run and the keys it now needs.
- The evidence artifacts lose the fields that could only be `None` (`valuation_config`,
  `valuation_agenda`, `monitoring_agenda`); a run without an initial account reopens.

### A datamodel run executes (M2, commit `470e1a32`)

```yaml
runs:
  factors:
    instruments: [A, B]
    start: "2024-03-06T00:00:00+09:00"
    end:   "2024-03-08T00:00:00+09:00"
    sessions_from: price_daily
    timezone: Asia/Seoul
    at: "16:00"
    datamodels:
      reversal: {dataset_id: reversal_2d, value_fields: [score]}
      momentum: {dataset_id: momentum_2d, value_fields: [score]}
```

- A run holds one kind of model: `strategies:` or `datamodels:`, never both (D5). A datamodel
  run refuses `exchange`, `execution_input` and `initial_account` by name.
- `flow/loop.py::OccurrenceFlow` is the walk both kinds share -- static occurrences in order,
  due items between them, the progress heartbeat at the top of the loop -- with the hooks a
  kind fills in. `SimulationFlow` subclasses it and fills them with the three phases of record
  `147`. `flow/datamodel.py::DataModelFlow` fills them with one phase, `DataModelPhase`: the
  window, `compute`, the output contract (`validated_output`, the checks `materialize()` made,
  under `datamodel.output.*`), `derived_available_at`, one chunk. No account, no venue, no run
  state repository: the model's `memory` persists on the instance for the run.
- `DataModelOutput` writes each session's rows as one complete parquet chunk under
  `.vqapr/materialized/<dataset_id>/` (staged, then moved), holds the first chunk's schema for
  the rest, and registers the directory as the dataset once after the last session through the
  registration path every other dataset takes. A refused registration removes the chunks; a run
  refused before any row leaves no directory; a run killed midway leaves the chunks that landed
  and no registration.
- `FrozenDataModel` beside `FrozenStrategy`; `FrozenRun.datamodels`; preflight refuses an
  output dataset that is already registered (`preflight.datamodel.output_registered`) before
  any session runs, and `check` asks the same question (`check.datamodel.output_registered`)
  and judges a datamodel's datasets, fields and lookbacks as it judges a strategy's.
- The record: `runs/<run-id>/datamodels/<id>@<fp8>/datamodel.json` -- component (path,
  registered and as-loaded fingerprints), the dataset and value fields it wrote, one line per
  session (evaluation time, output `available_at`, row count), the total, the period; no
  tables, no per-instrument lineage. `run.json` lists the datamodels. `orchestration.run`
  executes datamodels in process or under `--jobs`, each worker re-freezing the registered run.

### The old door closes (M3)

- `materialize()`, `MaterializationSpec`, `MaterializationInvocation`, `MaterializationResult`,
  the spec-file path in `vqapr run` / `vqapr check` (`is_spec_path`,
  `require_materialization_spec`, `_materialize`), `materialization_judgments`,
  `flow/run_spec.py`, the `materialization` record kind and its lineage payload are deleted. A
  YAML path handed to `run` or `check` is refused by name, pointing at `register` and the run
  id. `publish_run_allocation` and `publish_run_record` stay as they were.
- `vqapr list datamodels --run <id>`, `vqapr show datamodel <run>/<id>@<fp8>`,
  `vqapr rm datamodel <run>/<id>@<fp8>` (the record; the dataset stays registered);
  `list runs` / `show run` report datamodel records under `recorded`.
- `vqapr new datamodel <id> --dataset <d>` emits, beside the component, the `runs:` block that
  computes it: `sessions_from: <d>`, a wall time, placeholder instruments and period, and
  `datamodels.<id>` naming `<id>-values`. It registers as emitted.
- Showcases 002, 003 and 004 compute their datamodels as registered runs; 002's report shows
  the datamodel record where it showed the lineage.

## What this does not do

- No progress line on stderr during a long run (`059`'s third finding). `OccurrenceFlow` calls
  `on_progress` once per occurrence and the record writer's heartbeat is wired to it; a CLI
  progress line is a separate, small decision.
- No `--force` replacement of a datamodel's output dataset. Running a datamodel run again while
  its output is registered is refused; the fix names a new `dataset_id` or the removal of the
  registration.
- A strategy's identity now folds the run id, because the derived agenda's id and provenance
  carry it (`<run_id>.sessions`). Under 0.3.0 a shared agenda name kept a strategy's identity
  the same across runs. Whether identity should fold the sessions' content only is the owner's
  call; noted in the plan, not changed here.
- Panel spill, `--jobs` panel sharing and `prepare` stay deferred (design §7-2, §7-5).

## Validation

- **Equality with the old path (M2, before `materialize()` was deleted).** On the
  `test_materialize` fixture, a datamodel run of the same component on the same two instants
  published exactly the rows `materialize()` published: anti-join zero in both directions, four
  rows each way. The same fixture, computed by hand, is now pinned in
  `tests/flow/test_a_datamodel_is_a_run.py`; `tests/acceptance/test_the_panel_and_the_rows_agree.py`
  keeps its panel-versus-rows proof on a datamodel run.
- **The CLI journey.** `register` a declaration with two datamodels under one run, `check`
  (four phases pass), `run --jobs 2` (two workers, two datasets, two records), `list datasets`,
  `list runs` (kind `datamodel`), `show run`, a second `check` refused with
  `check.datamodel.output_registered` -- `tests/cli/test_a_datamodel_run_through_the_cli.py`,
  plus the three new verbs.
- **Behaviour of a strategy run.** The Step 6 tracer over the sample journey, re-run at each
  milestone. M1's delta against Step 6 is exactly the 735 standalone valuation occurrences and
  the 735 monitoring occurrences removed, and `measurement_recorder` / `monitor_after_commit`
  called once per fill in their place; M2/M3's delta against M1 is the loop's hook methods
  (`_start`, `_dispatch_static`, `_dispatch_due`, `_finish`) and `FlowContext.in_agenda_zone`
  called for every fill and NAV row. Nothing else in `vqapr/flow/` moved. The journey's pinned
  counts: 1470 occurrences (was 2940), account version 729 (unchanged), run-state version 2929
  (was 3664: the 735 standalone valuation publications).
- **Suites.** ruff clean on `src/` and `scripts/`; the fast suite and the full suite green at
  each milestone (M1 1363, M2 1397, M3 1378 tests); the showcase gate (nine, `show_003` against
  the local warehouse by hand); vulture at the gate confidence; `uv build`.
- **The refusal inventory**, regenerated deliberately three times. M1: the agenda and
  strategy_config codes gone; `declaration.read.run_invalid`, `workspace.run.register.reference`,
  `workspace.execution_input.lookup.missing`, `dataset.register.*` and `source.scan.path_missing`
  now observed at runtime (the last five were silently dropped by a generator scenario missing
  `grain`); `declaration.read.value_invalid` no longer observed. M2: twelve `datamodel.*` /
  `preflight.datamodel.*` / `check.datamodel.*` codes added. M3: the eighteen `materialize.*`
  and `check.materialize.*` codes removed.
- **Tests.** 36 files rewritten for M1 by four agents in parallel, three added for M2, eight
  rewritten or deleted for M3 (`test_materialize.py`, `test_a_materialization_is_a_run.py`,
  `test_an_agenda_is_shareable.py` deleted with their subjects); the deferred-import ceiling
  lowered from 22 to 19.

## Open, for the owner

- Should a strategy's identity fold the run id (through the derived agenda's id and
  provenance), or the sessions' content only? Today it folds the run id; under 0.3.0 a shared
  agenda name did not.
- A progress line on stderr for a long run (`059`'s third finding) -- the heartbeat exists.
