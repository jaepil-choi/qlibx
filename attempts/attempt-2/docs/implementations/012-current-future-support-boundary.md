# 012 Current and future support boundary

## Intent

Align the executable package contract with the narrowed MVP scope in the current PRD and
Architecture. Daily full-fill simulation is current support. Multi-event intraday execution,
partial fills as an execution lifecycle, external OMS reconciliation, and actual settlement remain
future characterization and must not appear as current acceptance or public workflow guidance.

## Implementation

- The qlibx.flow facade no longer re-exports the intraday characterization types. The implementation
  remains importable from qlibx.flow.intraday so its architecture seam can still be tested without
  claiming it as a current public facade.
- tests/scenarios/current_scope.yaml now declares support_status: current and contains only
  real-data current-support scenarios.
- The synthetic multi-event case moved to tests/scenarios/future_characterization.yaml and its
  executable test moved from tests/acceptance/ to tests/characterization/.
- Registry validation rejects overlap between current and future scenario identities, checks both
  registries against stable document IDs, and requires future cases to declare
  current_support: false.
- The bundled qlibx skill now identifies committed MVP simulation fills as the current feedback
  authority and labels prepared decisions, acknowledgements, and OMS reconciliation as future.
- The empty qlibx.production package explicitly states that it does not expose a supported OMS or
  reconciliation API.

## Trade-offs

The intraday module was retained rather than deleted because it is useful architecture
characterization and already proves preflight failure and per-event Account CAS behavior. Keeping
it out of qlibx.flow.__all__, current-scope YAML, and acceptance tests avoids turning that evidence
into a support claim.

The same stable ID UC-EXEC-001 appears in both registries with different case identities. This is
intentional: the current case proves executor-neutral daily children, while the future case probes
whether that seam can support multiple execution events. Registry identity is therefore the
use-case ID plus case, not the use-case ID alone.

## Validation

- Current/future registry, public facade, installed skill, daily acceptance, and intraday
  characterization narrow suite -> passed.
- Full pytest -> 67 tests passed.
- Ruff -> passed.
- Public import smoke confirmed qlibx imports and IntradayExecutionFlow is absent from qlibx.flow.
- uv build -> built qlibx 0.1.0 sdist and wheel. The sandboxed first attempt could not reach the
  isolated build dependency index; the approved retry succeeded without source changes.
