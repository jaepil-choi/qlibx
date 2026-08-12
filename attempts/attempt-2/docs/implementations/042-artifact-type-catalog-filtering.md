# 042 — Artifact-type catalog filtering

## Intent

Registration listing previously enumerated every successful artifact envelope and then invoked `load_model` for matching registrations. The envelope scan itself was bounded to catalog JSON, but payload deserialization still grew with the number of matching checks performed by each consumer and required application-side type filtering. The catalog already owns indexed artifact type metadata and should perform that selection.

## Observable outcome

- `LocalArtifactBackend.list_envelopes` accepts an optional `artifact_type` while preserving existing no-argument and `include_failure` behavior.
- Status and artifact-type values are bound as DuckDB parameters.
- Strategy and neutralization extension listings query only their registration artifact type.
- A mixed catalog causes Strategy listing to deserialize only Strategy registration payloads.

## Responsibilities and flow

The local evidence backend now builds a WHERE clause only from fixed internal condition fragments and binds all values separately. Extension flows declare the registration artifact type they need and retain responsibility for typed payload validation and result sorting.

## Alternatives and trade-offs

Adding a generic predicate API was rejected because it would expose backend query structure and complicate portability. Returning decoded payloads directly from `list_envelopes` was rejected because the backend does not know the consumer's payload contract. The single optional type parameter is backward compatible and keeps contract validation in the flow, at the cost of one catalog query followed by one payload read per selected registration.

## Validation

- `uv run ruff check src/qlibx/evidence/local.py src/qlibx/flow/extensions.py src/qlibx/flow/strategy_extensions.py tests/test_evidence.py tests/test_strategy_extensions.py`
  - `All checks passed!`
- `uv run pytest tests/test_evidence.py tests/test_strategy_extensions.py tests/acceptance/test_extension_scenarios.py -q --basetemp .tmp/pytest-strategy-remediation-m5-elevated`
  - `19 passed in 11.86s`

## Completion validation

- `uv run pytest tests -q --basetemp .tmp/pytest-strategy-remediation-full-20260807`
  - `220 passed in 453.97s`
- `uv run ruff check .` and `git diff --check`
  - passed; only pre-existing inaccessible ignored scratch-directory warnings and Git line-ending notices were emitted
- `uv build`
  - built `qlibx-0.1.0-py3-none-any.whl` and `qlibx-0.1.0.tar.gz`; archive inspection includes the changed production modules and bundled recovery guidance
- Fresh Python 3.12 wheel environment
  - installed the built wheel, ran the strategy-extension sample, loaded a deferred-annotation nested Pydantic extension, rejected post-registration source drift before execution, and filtered the mixed catalog by artifact type

## Remaining limitations

Listing registrations still validates every selected registration payload on each call and has no in-process payload cache. This is intentional until registration volumes or profiling justify a cache with explicit invalidation semantics.