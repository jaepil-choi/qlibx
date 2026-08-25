# VQAPR execution input registration and public simulation

Status: current

This showcase proves the supported `Project.simulate` spine: `vqapr.open(root)` plus one
`vqapr.simulation.Simulation` declaration and one authored `vqapr.authoring.StrategyModel`
class run a real simulation end to end. The venue is a `vqapr.venues.Academic` value; the
execution input and fill convention are declared inline as `simulation.ExecutionInput` /
`simulation.FillConvention`. `Project.simulate` registers the strategy component, its
agendas, the exchange, and the execution input itself - no caller touches a `ComponentRef`,
a fingerprint, an agenda id, or an `EconomicPortfolioIntent`.

The strategy lives in `models.py`, a real project-local module, because the engine's loader
resolves a component by re-importing its module and looking the class up by name; a class
defined inside `run.py`'s `main()` would have no stable import location and would be
refused. `models.ShowcaseStrategy` returns only `Hold`/`Rebalance` - the framework stamps
every identity fact (intent id, strategy id, source refs, account version) itself.

Evidence includes:

- one real `Project.simulate` run with a real `.parquet` execution table: pending intent →
  due execution → account advance;
- a density-invariance comparison across two `Project.simulate` calls sharing one
  `Simulation` declaration and `run_id`: the dense execution table carries three extra
  non-selected 10:00 rows the canonical trim does not, and their `SimulationSummary` values
  are equal;
- rejection of an invalid execution input (a non-finite selected price on a tradable row)
  without any change to the project's persisted `.vqapr/workspace.yaml`.

## Dropped from the legacy showcase

The legacy showcase generated a project-local `Constraint` component whose `project`,
`validate_intended`, and `evaluate` methods were unconditionally-passing stubs projecting
trivial `[0, 1]` per-instrument bounds. It demonstrated no economic behaviour of its own -
only that a constraint component could be generated, fingerprinted, and registered. That
scaffolding claim does not carry over to the supported surface: `Simulation.constraints`
exists and is exercised elsewhere (`tests/models/test_agent_first_run_values.py`), but
authoring an inert `vqapr.authoring.Constraint` subclass here just to keep the field
non-empty would demonstrate nothing new. `constraints=()` is declared explicitly instead.

## Reproduce

From the repository root:

```powershell
uv run --no-sync python showcases/show_001_execution_input_registration/run.py
```

Inspect:

- `outputs/report.html` — reader-facing run and invariance evidence;
- `outputs/trace.json` — complete run summary and comparison signatures;
- `outputs/workspace.yaml` — persisted declarations (`.vqapr/workspace.yaml` from `PROJECT`);
- `outputs/*.parquet` — dense, canonical, and invalid execution-input fixtures;
- `models.py` — the authored `StrategyModel`, at module scope so the engine's loader can
  resolve it.

Environment assumptions: repository `uv` environment, Python 3.12+, DuckDB 1.5+.

Last verified at: 2026-08-25

Verified against: `vqapr-0.1.0+implementation-008-working-tree`
