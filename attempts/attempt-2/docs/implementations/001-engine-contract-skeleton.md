# 001 Engine contract skeleton

## Why

The second implementation started with only a placeholder package entrypoint. Building data,
research, and execution behavior without enforceable boundaries would allow later slices to bypass
the architecture's strict serialization, explicit failure, dependency-direction, and deterministic
time contracts.

## Outcome

The package now has a minimal layer skeleton, a strict immutable boundary-model base, a bounded
machine-readable operation error, and an explicit operation outcome. Tests enforce architecture
dependency direction, prohibit production wall-clock reads, and verify that every stable PRD use
case is traced by the architecture document.

## Responsibility and flow

- QlibxModel owns construction-time validation for objects crossing package boundaries.
- OperationError records observed failure facts and retry preconditions without guessing a user
  resolution.
- OperationOutcome separates complete, incomplete, failed, and unsupported terminal states.
- Layer packages establish the intended dependency direction before feature implementations exist.
- The CLI entrypoint reports the package purpose without claiming unimplemented commands.

## Alternatives and trade-offs

OperationError is a serializable model rather than an exception hierarchy. Flow code will return it
as evidence in OperationOutcome; an exception adapter can be added at a public invocation boundary
if callers need raise/catch semantics. The initial import guard is static and deliberately checks
package-layer imports rather than incidental private class names.

## Validation

- uv run pytest -p no:cacheprovider tests/test_contracts.py tests/test_architecture.py
  tests/test_document_traceability.py -q: 8 passed.
- uv run ruff check src tests: passed.
- uv run python -c "import qlibx; print(qlibx.QlibxModel.__name__)": printed QlibxModel.
- uv build: built qlibx-0.1.0.tar.gz and qlibx-0.1.0-py3-none-any.whl.
- git diff --check -- src tests: passed, with the repository's expected LF-to-CRLF warning.

The first sandboxed build attempt used an empty task cache, could not resolve uv-build from the
blocked public index, and failed. The successful build used the existing approved uv cache under a
scoped elevated uv build invocation; no dependency changed.

## Remaining limitations

This milestone provides contracts and guards only. Project onboarding, registration, artifact
storage, PIT views, execution, account state, and reconciliation remain for later vertical slices.
