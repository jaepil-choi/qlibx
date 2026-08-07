# 044 — Least-authority role-specific views

## Intent

`MaterializeView`, `ExecutionView`, and `MonitorView` previously inherited every `StrategyView` capability. Missing injected state caused runtime errors, but the objects structurally advertised artifact, feedback, performance, memory, and account methods that their operations were not authorized to use. This contradicted the documented role boundary and the Interface Segregation Principle.

## Observable outcome

- Materialization and execution views expose only frozen PIT dataset reads and access lineage.
- Monitoring exposes dataset reads plus the committed account snapshot it actually evaluates.
- Strategy retains dataset, artifact, account, feedback, session-performance, and memory capabilities.
- Execution no longer accepts an unused account snapshot through `ViewGate`.
- Structural architecture tests prove forbidden methods are absent, not merely unusable at runtime.

## Responsibilities and flow

An internal `_DatasetView` owns binding validation, PIT reads, and dataset access records. `_AccountStateView` adds the bounded actual-account projection used by Strategy and monitoring. Concrete public role views inherit only the capabilities required by their operation. `ViewGate` remains the construction authority and passes only the inputs each view can expose.

## Alternatives and trade-offs

Keeping one broad view with optional inputs minimized classes but made authority an undocumented runtime convention and weakened static understanding. Duplicating dataset and account methods in every role was rejected because it would drift. The two internal capability bases add inheritance depth, but each base represents one cohesive authority and concrete role surfaces remain small. Removing the unused `account_state` argument from `execution_view` is an intentional API tightening; callers that relied on it were depending on a capability execution never consumed.

## Validation

- `uv run ruff check src/qlibx/context/scoped.py src/qlibx/flow/daily.py tests/test_architecture.py`
  - `All checks passed!`
- `uv run pytest tests/test_architecture.py tests/test_public_daily.py tests/test_public_constraints.py tests/test_session_timezone.py tests/acceptance/test_execution_scenarios.py tests/acceptance/test_research_scenarios.py -q --basetemp .tmp/pytest-strategy-remediation-m7-elevated`
  - `46 passed in 170.83s`
- `uv run pytest tests/test_architecture.py -q --basetemp .tmp/pytest-strategy-remediation-m7-architecture-elevated`
  - `3 passed in 0.78s`

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

The internal capability bases use inheritance rather than composition. This is acceptable while each role is a synchronous in-process view over the same dataset read mechanism. A future remote or asynchronous view transport may require explicit protocols or composition instead.