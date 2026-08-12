# Supported axis, time, and readiness gaps

## Intent

Public contracts and documentation must describe implemented runtime capability rather than anticipated extensions.

## Observable outcome

`AxisRequirement.kind` accepts only `instrument`, and `TimeRequirement.available_at_required` accepts only `True`, while existing default serialization remains valid. Participation `volume_role` and Exchange arithmetic remain supported. PRD and architecture now identify `GAP-IMPACT-001` and `GAP-DIRECTION-001`; signed hypothetical research is not described as executable short support.

## Responsibilities and flow

Typed requirements enforce the current data axis and PIT boundary. Readiness documents own the deferred total-market-volume impact API and instrument-direction work.

## Alternatives and trade-offs

Adding unused direction or market-volume interfaces was rejected because an API without runtime authority would create a false compatibility claim. Narrow literals may reject speculative configurations earlier, which is intentional.

## Validation

`uv run python -m pytest tests -q -p no:cacheprovider` passed 247 tests in 114.80s, including requirement serialization, scenario registry, documentation traceability, and architecture checks. `uv run ruff check .`, the ignored `import qlibx` smoke script, and `uv build` also passed.
