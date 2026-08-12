# 043 — Isolated Strategy validation artifact inputs

## Intent

A frozen `QlibxModel` prevents attribute reassignment but does not recursively freeze mutable containers inside a user-declared artifact payload. Strategy validation previously passed the same `ArtifactInputProjection` graph to both fresh Strategy instances. The first run could mutate a nested dict or list and make the second run observe that mutation, masking hidden state from the determinism comparison.

## Observable outcome

- Each validation run receives a deep copy of every resolved artifact projection and payload.
- The resolver-owned projection graph remains unchanged.
- A Strategy whose global counter is hidden by an idempotent nested mutation is rejected as `STRATEGY_EXTENSION_NONDETERMINISTIC`.
- Artifact resolution and backend reads still occur once per validation request.

## Responsibilities and flow

`StrategyExtensionFlow` owns isolation at the validation boundary. After resolving immutable evidence once, it creates separate deep projection tuples for the first and second views. `StrategyView` continues to return the payload associated with its own projection and does not gain backend access or copy policy.

## Alternatives and trade-offs

Resolving artifacts twice was rejected because it would duplicate catalog and payload reads and could compare different external state rather than one frozen input. Copying only `payload` was rejected because future mutable fields could be added elsewhere in the projection graph. Deep-copying the bounded validation projections is more expensive than sharing them, but validation is an explicit pre-registration gate and correctness is more important than throughput on this path.

## Validation

- `uv run ruff check src/qlibx/flow/strategy_extensions.py tests/test_strategy_extensions.py`
  - `All checks passed!`
- `uv run pytest tests/test_strategy_extensions.py -q --basetemp .tmp/pytest-strategy-remediation-m6b-elevated`
  - `14 passed in 8.91s`

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

Runtime invocation does not automatically deep-copy every artifact access; the operation receives one frozen invocation graph. Project-local code remains trusted and can mutate its own process state. This change specifically protects the two-run deterministic validation comparison.