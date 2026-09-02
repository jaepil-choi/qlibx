# VQAPR execution input registration and simulation

Status: current

This showcase proves the shipped spine end to end: `vqapr.public` registrations plus one
authored `vqapr.authoring.StrategyModel` run a real simulation. The dataset, the execution
input and its fill convention, the strategy, the exchange, and the two agendas are each
registered explicitly, then frozen by `preflight_run` and executed by `run` — the same path
`vqapr register` and `vqapr run` take.

The strategy lives in `show001_models.py`, a real project-local module, because the engine's
loader resolves a component by re-importing its module and looking the class up by name; a
class defined inside `run.py`'s `main()` would have no stable import location and would be
refused. `ShowcaseStrategy` returns only `Hold`/`Rebalance` — the loader adapts the authoring
contract onto the engine's, and the framework stamps every identity fact (intent id, strategy
id, source refs, account version) itself.

It declares one dataset read and the read is real: the loader requires a registered
StrategyModel to declare at least one requirement, and a declaration nothing consumes would be
a lie told to satisfy a gate. No observed close, no book.

Evidence includes:

- one real run against a real `.parquet` execution table: pending intent → due execution →
  account advance;
- a density-invariance comparison across two runs of one registered declaration: the dense
  execution table carries three extra non-selected 10:00 rows the canonical trim does not,
  and the two runs' economic signatures — account version, cash, positions, lifecycle
  counts — are equal;
- rejection of an invalid execution input (a non-finite selected price on a tradable row) by
  `register_execution_input`, without any change to the project's persisted
  `.vqapr/workspace.yaml`.

## Dropped from the legacy showcase

The legacy showcase generated a project-local `Constraint` component whose `project`,
`validate_intended`, and `evaluate` methods were unconditionally-passing stubs projecting
trivial `[0, 1]` per-instrument bounds. It demonstrated no economic behaviour of its own —
only that a constraint component could be generated, fingerprinted, and registered. That
scaffolding claim is not worth keeping: constraints are exercised for real in `show_003`
and `show_008`, and authoring an inert one here just to keep the field non-empty would
demonstrate nothing. The run's `StrategyEntry("showcase-strategy")` names no constraints instead.

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
- `show001_models.py` — the authored `StrategyModel`, at module scope so the engine's
  loader can resolve it;
- `show001_exchange.py` — the registered `AcademicExchange` the run fills against.

Environment assumptions: repository `uv` environment, Python 3.12+, DuckDB 1.5+.

Last verified at: 2026-09-03

Verified against: `vqapr-0.3.0`
