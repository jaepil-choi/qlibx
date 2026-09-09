# 139 — the Run: configuration is registered, and each strategy's record is its own output

**Closes:** `docs/issues/archive/034`; testbed findings A7 and C4/E1 (ledger §1, never filed). **Step:** 7
of `docs/refactoring/2026-09-02-the-convergence-campaign.md` (M7, the last).
**Authority:** `docs/design/the-panel-the-surface-and-the-run.md` §4 (the contract) and §7-4
(RESOLVED: one Account per strategy); the owner's decisions of 2026-09-02 on §7-2 (no panel
spill in this step) and §7-5 (no `prepare` verb); architecture §17.3–17.6.
**Plan:** `.agent/plans/completed/m7-run-is-config-strategy-record-is-output.md`.

## Why this exists

One word, "run", did three jobs: the experiment's configuration, the strategy under test, and one
execution's record. Architecture §17.3–17.6 measured the cost line by line. A run was one strategy
at the level of a dataclass field, so a comparison across factor models was n runs carrying n
copies of one period and one universe. The durable form was a spec file read fresh on every
call, so the reusable unit was a filename. The record held two folded digests and could not say
which `.py` ran, what the strategy's own fingerprint was, which execution convention the fills
followed (`034`), or which instruments the run traded; a reader who wanted "this strategy's runs"
had no key to collect them by. Nothing deleted a record, and the source said so in prose.

The design's answer is one noun split in two: a **Run** is configuration and is registered; a
**strategy record** is output and is named by the strategy and its fingerprint.

## Rulings

| question | ruling |
|---|---|
| what a run is | a registered declaration (`runs:` in a declaration document): universe, period, venue, execution input, initial account **declaration**, and the strategies it tries. `vqapr run <run-id>`; the spec file and `--run-id` are gone. |
| the strategy's agenda | the strategy's registered `strategy_config` (record `138`); the run does not restate it. Deviates from design §4.1's YAML, which wrote `agenda:` per strategy: `138` made the binding the strategy's identity in the workspace, and stating it twice is the double declaration `040` complained about. One strategy on two cadences is two registered ids. |
| accounts | one `Account` per strategy from the shared initial declaration (§7-4); one `SimulationFlow` per strategy. |
| the records | `run.json` (configuration, written before any strategy starts, identical for every writer, so it needs no lock) and `strategies/<id>@<fp8>/strategy.json` beside that strategy's tables. Content-addressed by the registered fingerprint: the same fingerprint refuses without `--force`; an edited component lands beside the old record. A changed run under an old id is refused naming both digests. |
| `034` | `run.json` carries the execution input id and its fill declaration (selector, local time, timezone, trade price, declaration identity). Two runs at different conventions differ there. |
| A7 | `run.json` carries each dataset's source digest, the sha256 of the parquet bytes the registration pointed at. |
| `--jobs N` | N processes; each opens the workspace, freezes the registered run again and runs one strategy, building its own panels. The record is how a worker's result comes back, so `jobs > 1` needs a store and a registered run. |
| verbs | `vqapr rm run <id> [--keep-latest]`, `rm strategy <run>/<id>@<fp8>`, and `rm <declaration kind> <id>` — the machinery `Workspace.remove` and the record lock already had, given a caller. A live record is refused. |
| `list` / `show` | `list runs` lists registered runs and the records beside each; `list strategies --run` filters records on their own fields with no new I/O; `show run` and `show strategy`. |
| materialization | still a spec file (`datamodel:`), checked and run by path; a `strategy:` file is refused by name pointing at `runs:`. |
| not done | panel spill and `prepare` (owner, 2026-09-02); `023p` (HELD by `023`; the per-component registered and as-loaded fingerprints are now both in `strategy.json`, which is the data a verdict would read); `instruments_from: <roster>`; retiring the three config sections a registered run now makes redundant. |

## What changed

- **`flow/run.py`.** `RunDefinition` is ids and values — `run_id`, `strategies: tuple[StrategyEntry]`,
  valuation, monitoring, `exchange` (a component id), execution input id, period, initial account,
  instruments. `FrozenRun` is the run layer plus `strategies: tuple[FrozenStrategy]`; each
  `FrozenStrategy` carries its config, constraints, agenda slice, requirements, opening memory and
  payload, and its own identity; `record_ref` is `<id>@<fp8>`. `FrozenRun.identity` is the run
  layer's alone, so adding a strategy does not rename the rows the others wrote;
  `dispatch_order(layer)` is the static merge one flow dispatches.
- **`flow/preflight.py`.** Resolves the run layer once and freezes each strategy from its
  registered binding; the union of requirements is the panel set.
- **`flow/orchestration.py`.** `run(project_root, frozen, *, store_root, strategies, jobs,
  replace_record, record_account_positions) -> RunResult` (`results` per strategy in-process,
  `records` per strategy from disk, `result()` for the one-strategy case);
  `run_registered_strategy` is the spawn worker. `flow/simulation.py` takes the strategy layer
  (`layer=`) and reads what is the strategy's from it.
- **`flow/run_records.py`, `flow/records.py`.** `RunRecordWriter(root, run_id, strategy_ref)`;
  `write_run_record` / `RunRecordConflict`; `STRATEGY_KIND` with its field set and
  `RUN_JSON_FIELDS`; readers `read_run_record` (falls back to `record.json`), `strategy_refs`,
  `read_strategy_record`, table readers taking `strategy_ref`; `remove_run_record`,
  `remove_strategy_record`. `record.json` remains the materialization record and the shape of a
  run written before this. `data/store.physical_digest` is public for A7.
- **`workspace.py`, `workspace_codec.py`, `declarations.py`.** The `runs` section: registered
  through the same transaction, refused when it names anything unregistered
  (`workspace.run.register.reference`), decoded with forward checks, `remove("run", id)` and the
  reference edges a run adds to components, agendas and bindings. `decoded_run` / `encoded_run`
  are the one shape a run has in a document; `declaration.read.run_invalid` names a wrong one.
- **`flow/judgments.py`.** The eight judgments read a `RunDefinition` and judge every strategy it
  names. `flow/run_spec.py` keeps only the materialization kind; `flow/store_spec.py` and
  `reporting.tables_declared` are gone with the spec file.
- **CLI.** `run <run-id> [--strategy]... [--jobs N] [--force] [--store-root] [--no-account-positions]`
  with a per-strategy envelope; `check <run-id>` (phases `workspace, run, judgments, preflight`);
  `list runs` / `list strategies`; `show run` / `show strategy`; `rm`; `new run` emits the `runs:`
  template. The skill and README describe the new surface.
- **Tests.** `tests/flow/test_a_run_holds_several_strategies.py` holds the campaign's acceptance
  criteria: three strategies in one run leave three NAV series (sequentially and with `jobs=3`);
  `run.json` answers what `record.json` could not; a tweak is a directory beside the old one;
  a changed run under an old id is refused; a killed strategy leaves rows, no `strategy.json`,
  and a `run.json` that says what was attempted. `tests/test_a_run_is_registered.py`, the
  rewritten `tests/cli/test_check.py` and every test that built a run spec moved to the
  registered run.

## What this does not do

- **No panel spill, no `prepare`** — the owner's decisions; the panel identity is already the
  key a spill file would be named by, so the step is additive when a measurement asks for it.
- **The three config sections stay.** A registered run names its valuation and monitoring
  agendas and its strategies; `valuation_configs` and `monitoring_policies` are now consulted
  only by preflight's drift check, and `strategy_configs` is the one binding a run relies on.
  Retiring the first two is a separate decision.
- **Materialization** keeps its spec file, and `record.json` its shape.
- **`instruments_from: <roster>`** (design §4.1) is not read; a run lists its instruments.

## Validation

```
uv run ruff check src/                            All checks passed
PYTHONUTF8=1 uv run pytest tests/ -q -rs          1314 passed, 13 deselected
PYTHONUTF8=1 uv run pytest tests/ -q -m slow -rs  13 passed
```

Branch parent `develop @ 2e134d7d` (record `138` merged), measured: **1308 passed / 14
deselected** fast; **14** slow; showcases 9 of 9.

**Showcases: 9 of 9.** Every showcase completes on this tree; seven of them build their runs
through the new `RunDefinition` and `run(...).result()`.

Slow is 13 where the parent had 14: the record test file's three slow tests became two, and
the multi-strategy file adds two -- one former slow run (a second run of the sample) is now a fast
test of the refusal alone. Measured, not a floor.
