# 040 — Exact registered Strategy source execution

## Intent

Registration evidence must identify the exact project-local Strategy bytes that execute. The previous flow hashed the path once, then the import loader read the file again and executed a third path-based read. A file swap between those actions could execute unregistered code. The loader also omitted `sys.modules` registration, so common deferred Pydantic annotations could not resolve their defining module.

## Observable outcome

- Loading with an expected source hash rejects different bytes before any module code executes.
- Hashing, compilation, and execution use one source byte buffer.
- Deferred annotations and nested Pydantic models resolve normally.
- Repeated loads within one project reuse a validated module identity, while identical files in different projects remain isolated.
- Failed imports restore the previous module entry or remove the new entry.

## Responsibilities and flow

`LocalModuleLoader` now owns exact-byte reading, hash validation, stable project/path/source module identity, cache validation, `sys.modules` lifecycle, compilation, and execution. `StrategyExtensionFlow` still owns registration selection and error evidence. It passes the registered hash into the loader and translates a loader source-drift exception to the existing `STRATEGY_EXTENSION_SOURCE_DRIFT` contract.

## Alternatives and trade-offs

Using `spec.loader.exec_module()` was rejected because it reads from the path independently of the validated byte buffer. Re-executing every load was also rejected because it replaces class identity and breaks deferred-model consumers holding earlier classes. Cache reuse follows normal import semantics and can retain module globals; project-local Strategies are therefore still required to be deterministic and the validation gate remains responsible for detecting hidden mutable behavior. The module name includes project-root identity in addition to relative path and source hash so separate projects cannot share mutable module state.

## Validation

- `uv run ruff check src/qlibx/extensions/local_modules.py src/qlibx/flow/strategy_extensions.py tests/test_local_modules.py tests/test_strategy_extensions.py`
  - `All checks passed!`
- `uv run pytest tests/test_local_modules.py tests/test_strategy_extensions.py -q --basetemp .tmp/pytest-strategy-remediation-m2-elevated`
  - `17 passed in 10.13s`

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

Project-local modules remain trusted Python and are not sandboxed. A module can intentionally mutate process state. Stable module caching means module globals live for the process lifetime; deterministic validation must continue to reject Strategies whose output depends on such hidden state.