# Project artifact backend reuse

## Intent

`QlibxProject.artifacts` constructed a new `LocalArtifactBackend` on every access. Construction was cheap while the backend was stateless, but it made any bounded instance-level catalog session ineffective because each flow received a different object.

## Observable outcome

One opened `QlibxProject` lazily creates and then reuses one artifact backend for all facade operations. Public method signatures, catalog paths, publication results, and direct `LocalArtifactBackend` construction remain unchanged.

## Responsibilities and flow

`QlibxProject.__init__` owns an optional backend reference. The `artifacts` property creates it on first access from the immutable project root/config paths and returns that identity thereafter. Recovery tests continue to instantiate and subclass `LocalArtifactBackend` directly, so crash injection and independent backend use remain available.

## Alternatives and trade-offs

Eager construction was unnecessary because many project operations do not access artifacts. A module-global backend cache was rejected because it would couple projects and make connection lifetime unbounded. Memoization means future instance state is shared across all flows from one project, which is intentional for the explicit scoped session introduced in the next milestone.

## Validation

- `.venv/Scripts/python.exe -m pytest tests/test_project.py tests/test_catalog_recovery.py -q --basetemp .agent/test-runs/catalog-c2-focused -p no:cacheprovider` -> 16 passed in 10.39s.
- `.venv/Scripts/python.exe -m ruff check src/qlibx/project.py tests/test_project.py` -> passed.
- `git diff --check` -> passed.
- `.venv/Scripts/python.exe -m pytest tests -q --basetemp .agent/test-runs/catalog-c2-full -p no:cacheprovider` -> 234 passed in 417.55s.

## Remaining limitations

This refactor alone does not reduce DuckDB connection counts. It only establishes the project-owned identity needed for an explicit bounded session; calls made through independently constructed backends retain their own state and connection behavior.