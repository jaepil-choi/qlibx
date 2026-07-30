# Capability requirement contract

## Why this change exists

Canonical PRD sections 4.8, 5.4, 5.5, 8.3, and P8 require every data-dependent capability to
declare its inputs, expose a read-only plan, fail with a machine-readable requirement gap, and let
the generated agent skill guide a user through registration/configuration before retrying.

The package previously had three incompatible partial patterns:

- execution profiles returned an `ExecutionProfilePlan` with profile-specific missing-role fields;
- `group_demean` used a `requires_groups` boolean and raised a raw `ValueError`;
- exposure analysis inferred intent from optional arguments, so `None` could mean either
  "unrequested" or "requested but unavailable."

That prevented agents from handling requirement gaps uniformly and allowed an omitted exposure
field to look like a complete result.

## User and system outcome

Users and agents can now inspect one public contract before execution, see why each input is needed,
compare acceptable alternatives, answer explicit questions, register/configure the selected input,
and rerun the same request. Runtime errors serialize the same resolution returned by the read-only
plan.

The existing installed onboarding and data-registration journey remains unchanged. This task does
not implement beta estimation or beta residualization.

## Responsibility and flow changes

`qlibx.requirements` is a dependency-free kernel module. It owns:

- `CapabilityRequirements`, `CapabilityRequirement`, and `DerivationAlternative` declarations;
- `RequirementEvidence` supplied by a capability adapter;
- `CapabilityResolution`, including `satisfied`, `unsatisfied`, and `not_requested`;
- the public `CapabilityPlan` and typed `UnavailableOutput`;
- the pure `evaluate_requirements` function.

The kernel does not inspect a project, catalog, CLI arguments, or user files. `profiles` converts
catalog/config state into evidence; `alpha` converts already-provided runtime inputs into evidence.

`errors.requirement_gap` preserves the existing `QlibxError` transport and places
`CapabilityResolution.to_dict()` unchanged in `context`. The stable code is
`QLIBX_MISSING_CAPABILITY_REQUIREMENTS`.

Execution profiles were deliberately migrated rather than adapted. `ExecutionProfilePlan` is no
longer public. Declaration, read-only planning, and runtime readiness now use
`CapabilityRequirements`, `CapabilityPlan`, and `require_execution_profile`.

`OperationSpec.requirements` replaces `requires_groups`. `plan_operation` and runtime dispatch use
the same evaluator. Project-local and signal-transform-backed operations can declare the same
requirement objects.

Exposure analysis now requires `requested_metrics`. Optional requirements that were not requested
are `not_requested`; requested missing inputs are `unsatisfied`. Runtime raises by default.
Callers that explicitly request `allow_incomplete=True` receive `status="incomplete"` plus typed
`UnavailableOutput` entries and cannot mistake the artifact for a complete result.

CLI, installed schemas, error guidance, generated skill text, and generated operation references
all expose the common contract and resolution-interview loop.

## Alternatives and trade-offs

Three approaches were considered:

- Full common contract and immediate public migration: one public shape, but an intentional
  breaking change.
- Alpha-local contract with profiles unchanged: smaller initial change, but two incompatible public
  models and later migration cost.
- Common internals with an `ExecutionProfilePlan` compatibility adapter: less immediate breakage,
  but two public views and adapter consistency burden.

The user selected full migration. At package version 0.1.0, updating all repository-owned consumers
in one change is preferable to preserving a second public representation.

The common model keeps capability-specific details in `CapabilityPlan.parameters`. This avoids
forcing profile clocks and role contracts into the universal requirement schema, at the cost of
those details being capability-defined rather than separate dataclass fields.

## Validation

Validation performed during implementation:

- `uv run pytest tests/test_requirements.py tests/test_execution_profile.py
  tests/test_alpha_lineage.py tests/test_architecture.py tests/test_documentation.py
  tests/test_cli.py tests/test_agent_onboarding.py` -> 51 passed.
- First full `uv run pytest` -> 116 passed, one expected public-contract assertion failed because
  `qlibx.requirements` was newly added to `qlibx.__all__`; the repository-owned assertion was
  migrated.
- `uv run ruff format .` -> 13 files formatted, including three pre-existing formatter drifts
  identified before implementation.
- Final `uv run pytest` -> 118 passed, including the installed P0/P1 agent onboarding and data
  registration acceptance journey, a project-local operation using the public requirement
  contract, and all Strategy/Qlib/research/reporting tests.
- Final `uv run ruff check .` -> all checks passed.
- Final `uv run ruff format --check .` -> 116 files already formatted.
- `uv build` -> successfully built `dist/qlibx-0.1.0.tar.gz` and
  `dist/qlibx-0.1.0-py3-none-any.whl`.

## Remaining limitations and follow-up

- Beta estimation and beta residualization remain deliberately unimplemented.
- `group_demean` validates that an explicit group matrix is present. Its point-in-time provenance is
  enforced by the caller's bounded data/artifact contract rather than by inspecting a project from
  the pure alpha layer.
- The first public migration covers current explicit registered-data surfaces: execution profiles,
  group demeaning, exposure requests, and signal-transform operation declarations. Future
  data-dependent capabilities must use the same public types rather than introduce another plan
  shape.
