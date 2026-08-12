# Installed Strategy composition

## Intent

Close `GAP-STRATEGY-COMPOSITION-001` with installed-project evidence for
`UC-ALPHA-PATH-001`, without changing the existing StrategyResult v2, Ensemble, or daily execution
contracts.

## Observable outcome

A fresh project can materialize `strategy-composition-v1`, run two path-dependent daily producers
with distinct Account and Strategy Memory origins, compose their exact frozen
`strategy_result:v2` artifacts, validate and register an artifact-only local consumer, and execute
that exact registration against a later, separate Account B. The sample emits machine-readable
source hashes, producer call counts, full source lineage, registration identity, and downstream
Account evidence.

## Responsibilities and flow

The sample producers establish package-observed Account, feedback, and Memory access. The existing
`CompositionFlow` loads exact member IDs and propagates each source's state lineage without a
synthetic singular identity. The project-local consumer reads only the bound Ensemble artifact;
the existing daily flow alone reads Account B for sizing, fills, feedback, checkpoints, and final
state. `SampleMaterializer` owns discovery and safe, idempotent materialization of the new bundle.

## Alternatives and trade-offs

A new core composition API or schema revision was rejected because the public-surface vertical
slice passed on the existing v2 contract. Extending `strategy-extension-v1` was also rejected: its
stored-signal lifecycle is intentionally narrow, while the new sample needs two stateful producer
runs and temporal separation between frozen source creation and downstream execution. The bundled
market data is deterministic contract evidence, not a performance or execution-realism claim.

## Compatibility and limitations

The change adds one opt-in sample ID and does not alter the default sample. Exact artifact and
registration selection remains mandatory; latest-compatible lookup and producer replay are not
introduced. Provenance-incomplete path-dependent v1 composition still fails. Next-open execution,
partial fills, market impact, executable short, external OMS, and distributed recovery remain out
of scope.

## Validation

The public vertical slice passed with 36 focused lineage/extension/daily tests. The final focused
lineage, extension, daily, composition, and sample set passed 46 tests in 19.32 seconds; registry,
capability, document traceability, architecture, and sample checks passed 18 tests in 7.97 seconds.
The complete source suite passed 250 tests in 120.53 seconds. `uv run ruff check .`, `uv run python
-c "import qlibx"`, and `git diff --check` passed.

`uv build` produced `qlibx-0.1.0-py3-none-any.whl` and `qlibx-0.1.0.tar.gz`; archive inspection
confirmed all seven `strategy_composition` sample files and the bundled qlibx skill in both
artifacts. A fresh Python 3.12 environment outside the source checkout installed only the wheel,
materialized `strategy-composition-v1`, and completed the sample. The installed import resolved to
the temporary environment's `site-packages`; producer counts remained 2 before/after composition,
source content hashes were unchanged, both source lineages were present, and every downstream
decision/execution account ID was `sample-downstream-account-b`.
