# 038 Layer-safe typed Strategy artifact inputs

## Intent

A Strategy could previously consume a stored signal only through the specialized
`CompositionFlow`, and generic `ResearchFlow` had no typed artifact-input boundary. Callers could
attach `additional_dependencies`, but that recorded caller assertions rather than artifacts the
Strategy actually read. This prevented a reusable Strategy from declaring a portable input role
while keeping exact artifact selection frozen outside Strategy code.

## Observable outcome

Artifact-aware Strategies may implement optional `artifact_requirements()` and declare a consumer
role, exact artifact type/schema, and bounded top-level scalar semantic constraints. A frozen
`StrategyInvocation` binds each declared role to one exact artifact ID. Existing Strategies that
only implement dataset `requirements()` continue to run with the empty default.

`ResearchFlow` eagerly validates every declared input before Strategy compute. It rejects missing,
extra, or duplicate roles, unsupported contracts, invalid payloads, and semantic mismatches with
typed `STRATEGY_ARTIFACT_*` errors. The built-in registry supports only
`stored_signal_result:v1` and `strategy_result:v1` in M2.

A Strategy receives an immutable, backend-free projection through
`view.artifact(consumer_role, PayloadType)`. The view exposes no catalog, path, envelope, loader, or
dependency mutation API. Only successful calls to `view.artifact()` produce artifact dependency
edges; declared but unused inputs are still validated but do not become lineage.

## Responsibilities and flow

- `qlibx.operations.artifacts` owns portable requirement, binding, semantic constraint, and stored
  signal payload models without importing evidence or Flow code.
- `qlibx.context.scoped` owns the immutable input projection, access record, typed view-access
  failure, and role/type gate.
- `qlibx.flow.artifact_inputs` owns the built-in contract registry, exact backend load, hash and
  payload validation through `LocalArtifactBackend.load_model()`, semantic checks, and projection
  construction.
- `ResearchFlow` resolves dataset requirements first, resolves all artifact inputs second, runs the
  Strategy third, and derives direct artifact dependencies from recorded view access.
- `CompositionFlow` keeps its existing public stored-signal imports and specialized Ensemble path;
  `additional_dependencies` remains only for that compatibility path until M4.

## Failure contract

Pre-compute failures use `STRATEGY_ARTIFACT_REQUIREMENTS_FAILED`,
`STRATEGY_ARTIFACT_BINDING_MISSING`, `STRATEGY_ARTIFACT_BINDING_UNDECLARED`,
`STRATEGY_ARTIFACT_CONTRACT_UNSUPPORTED`, or
`STRATEGY_ARTIFACT_SEMANTICS_INCOMPATIBLE`. View access uses
`STRATEGY_ARTIFACT_ACCESS_UNDECLARED` or
`STRATEGY_ARTIFACT_PAYLOAD_TYPE_MISMATCH`.

Each error carries the requirement ID when one exists, consumer role, expected contract, bounded
actual contract, and exact artifact ID when selected. Failures do not publish a Strategy success
artifact or enter Account, memory, or decision-intent commit paths.

## Alternatives and trade-offs

A lazy backend handle in `StrategyView` was rejected because it would expose evidence authority to
user code and make validation timing control-flow dependent. Artifact IDs are not embedded in
Strategy declarations because that would make reusable Strategies environment-specific. Catalog
search for latest or first-compatible candidates is deliberately absent because it would make
frozen reruns non-deterministic.

Semantic compatibility is deliberately limited to strict type-and-value equality on a top-level
scalar field. Dotted paths, callback validators, and import-based validators are outside the
portable M2 contract. Project-local payload model registration remains M3 scope.

`StrategyResult` schema and Ensemble multi-source state compatibility are unchanged. Direct
consumption lineage is stored in the result envelope; M4 owns any state/cursor schema migration and
special Ensemble-flow migration.

## Validation

```
.venv/Scripts/python.exe -m pytest tests/test_strategy_artifact_inputs.py tests/test_pit_research.py tests/acceptance/test_research_scenarios.py tests/acceptance/test_analysis_scenarios.py -q -p no:cacheprovider --basetemp C:\tmp\qlibx-pytest-m2-core-019fd94d
-> 30 passed in 16.83s

.venv/Scripts/python.exe -m pytest tests -q -p no:cacheprovider --basetemp C:\tmp\qlibx-pytest-m2-core-full-019fd94d
-> 186 passed in 162.42s

.venv/Scripts/python.exe -m ruff check .
-> All checks passed!
```

The tests prove generic stored-signal consumption, eager validation of unused inputs,
actual-access-only dependency edges, cardinality failures, exact type/schema failures, semantic
failures, optional-contract failures, and typed role/payload access failures.

Daily propagation validation:

```
.venv/Scripts/python.exe -m pytest tests/test_public_daily.py tests/test_strategy_artifact_inputs.py -q -p no:cacheprovider --basetemp C:\tmp\qlibx-pytest-m2-daily-019fd94d
-> 28 passed in 31.67s
```

The daily tests pin the pre-M2 empty-binding configuration and request hashes, prove non-empty
bindings change both frozen and recovery identity, observe the same exact input artifact dependency
at every decision, and reject changed artifact selection on resume.

Final completion gate:

```
.venv/Scripts/python.exe -m pytest tests -q -p no:cacheprovider --basetemp C:\tmp\qlibx-pytest-m2-final-019fd94d
-> 191 passed in 270.87s

.venv/Scripts/python.exe -m ruff check .
-> All checks passed!

git diff --check
-> clean

$env:UV_CACHE_DIR = 'C:\tmp\qlibx-uv-cache-m2-final-019fd94d'; uv build
-> built dist/qlibx-0.1.0.tar.gz and dist/qlibx-0.1.0-py3-none-any.whl
```

The default uv cache under the non-ASCII user profile returned access denied. The build was rerun
with a task-scoped ASCII cache according to the corporate Windows workflow. Wheel and sdist
inspection confirmed the new artifact contracts, resolver, ResearchFlow, daily flow, and simulation
modules are packaged. An import smoke loaded the new public operation/context types directly from
the wheel.

## Remaining limitations

- Only the two built-in contracts are registered.
- Semantic constraints cannot inspect nested fields or execute custom code.
- Ensemble continues to use its specialized M1/M4 compatibility path.