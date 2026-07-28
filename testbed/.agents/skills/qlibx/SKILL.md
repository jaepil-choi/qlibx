---
name: qlibx
description: Execute qlibx point-in-time data and alpha research through public package surfaces.
metadata:
  qlibx_version: 0.1.0
  instruction_schema_version: 1
  target: codex
---

# qlibx agent workflow

Never edit installed qlibx, Qlib, site-packages, `references/`, or user source data. Start with
`qlibx project status`, `qlibx docs`, `qlibx schema`, and the task-specific help below.

Load an existing project with `Project.load(<root>)`. Build the YAML loader with
`ConfigDrivenDataLoader.from_project(project)` and the centralized research catalog with
`ResearchCatalog.from_project(project)`. Respect the configured source, generated-data, state,
research, and extension roots.

## Register data interactively

1. Run `qlibx data requirements`.
2. Run `qlibx data discover --root <project>`; this is read-only and excludes generated data.
3. Run `qlibx data inspect --root <project> --path <candidate> --sample-rows 5`.
4. Show the exact schema and unresolved questions to the user. Do not infer availability, ticker,
   value meaning, primary key, frequency, or timezone from a similar name.
5. After confirmation, author `config/qlibx/data/registrations.yaml` using
   `examples/data-registration.yaml` as structure only.
6. Run `qlibx data plan`, explain every assumption/warning, then `qlibx data register`.
7. Add source/dataset YAML and run catalog plus bounded preview. Upstream must hash identically.
   `available_at` is the only required time axis and controls point-in-time visibility. A matrix
   may index it directly. Declare a separate `time_field` only when the user explicitly chose to
   preserve and use an optional event/observation field; use `examples/logical-dataset.yaml`.

## Research and execution

Before proposing a trial, query prior proposals, successful/failed/invalid attempts, searched
ranges, and nearest semantic/empirical neighbors. Freeze resolved config, dataset snapshot,
component source and seed before execution. Publish durable success/failure/invalid evidence; do
not promote scratch output. Start from `examples/research-workflow.py`.

Load verified members with `combine_stored_weights`; do not import or rerun their strategies.
Use the combined signed weight in `construct_enhanced_index` or the stored-matrix convenience
`run_signed_execution`. For an adaptive signed StrategyAgent, use `run_strategy_execution` with
`SignedExecutionConfig`; the agent is called at each Qlib decision step with prior confirmed active
account state. Start from `examples/stored-ensemble.py` and `examples/signed-execution.py`.

Matched capitalization is a Qlib long-only compatibility mode, not native borrow, margin, recall,
forced buy-in, or borrow-fee support. Treat Qlib dealt quantity and account state as authoritative.

## Error recovery

Every `QlibxError` returns `code`, `message`, `action`, and `context`. Run
`qlibx errors <code>` before editing config or retrying. If guidance requires user confirmation,
explain the unresolved meaning and ask the user; never guess or silently fall back.

## Project-local extension

Run `qlibx extension contracts`, then read `references/contracts.md`. Put trusted code below the
configured extension root and load it with `qlibx.extensions.load_extension`; never patch the
package. Record
its source digest and contract version, then invoke the matching public validator. Store named
intermediate values through `ArtifactStore`; only complete JSON/Parquet artifacts are portable.
Keep analysis sections, report composition and rendering separate. Reporting must not publish a
canonical research result or invoke the original strategy. Start from
`examples/artifact-reporting.py`.
