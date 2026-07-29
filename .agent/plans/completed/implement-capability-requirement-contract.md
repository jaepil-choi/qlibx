# Implement the public capability requirement contract

Status: complete

## Purpose

Implement canonical PRD sections 4.8, 5.4, 5.5, 8.3, and P8 with one public requirement model
shared by data-dependent capabilities. Migrate the execution-profile public contract to that model,
make requested-but-unavailable exposure outputs explicit, and keep the installed human/agent
journeys working.

## Scope and non-goals

- Use `docs/qlibx-prd.md` as the canonical product contract.
- Add one public, machine-readable requirement declaration and resolution model.
- Migrate `execution_profile_requirements` and `plan_execution_profile` from
  `ExecutionProfilePlan` to the common public model; update all repository consumers together.
- Declare and enforce the existing `group_demean` point-in-time group input through the common
  model.
- Add explicit exposure metric requests and typed unavailable-output details; use the same
  requirement-resolution types in plan, error, and artifact surfaces.
- Expose declarations, plans, errors, schema, installed help, and generated-skill interview
  guidance through public package surfaces.
- Preserve the P0/P1 installed user/agent onboarding and data-registration journey and all other
  currently passing scenarios.
- Update `docs/qlibx-architecture.md` and create an implementation record under
  `docs/implementations/`.
- Do not implement, modify, or document `beta_residualize` or beta estimation in this task.
- Do not stage, commit, push, publish, change dependencies, or modify user source data.

## Acceptance criteria

- Requirement declarations include stable capability ID/version, stable requirement ID/role,
  semantics, axis/unit/currency, purpose, satisfaction rule, availability constraints,
  mandatory/optional status, derivation alternatives, user questions, and public next commands.
- One pure evaluator produces a typed resolution containing satisfied and unsatisfied
  requirements, reasons, alternatives, questions, retryability, and read-only/mutation metadata.
- Read-only plan results and runtime `QlibxError` contexts serialize the same evaluator result.
- The execution-profile public API returns the common declaration/plan types; repository CLI,
  docs, tests, and data facade no longer expose `ExecutionProfilePlan`.
- `group_demean` exposes its group-label requirement through installed help/schema and raises a
  documented structured requirement-gap error when the explicit group input is missing.
- Exposure callers explicitly select requested metrics. Requested metrics with missing optional
  input are represented by typed unavailable-output details; unrequested metrics are distinct and
  are not reported as failures.
- Project-local signal-transform operations can declare requirements through `OperationSpec`.
- Generated skills explain how to inspect a requirement gap, interview the user, register/configure
  the selected alternative, and rerun the same capability.
- Existing P0/P1 acceptance journey, complete test suite, Ruff lint, Ruff format check, and build
  pass. Any pre-existing formatting drift in touched files is corrected.

## Repository context

- `src/qlibx/errors.py` provides the generic `{code, message, action, context}` envelope and the
  `unknown_name` builder, but requirement contexts are untyped.
- `src/qlibx/profiles.py` owns the public `ExecutionProfilePlan` dataclass and performs declaration,
  catalog inspection, and plan projection in one module.
- `src/qlibx/alpha/registry.py::OperationSpec` has only `requires_groups: bool`; missing groups raise
  a raw `ValueError`.
- `src/qlibx/alpha/exposure.py::analyze_exposure` infers requested outputs from optional arguments,
  so it cannot distinguish unrequested from requested-but-unavailable metrics.
- `src/qlibx/documentation.py`, `src/qlibx/cli.py`, and `src/qlibx/skill.py` generate installed
  agent-facing public surfaces.
- Baseline at `8eedbff`: 110 tests pass and Ruff lint passes. Ruff format check reports three
  existing files: the handoff document, architecture document, and `alpha/exposure.py`.

## Milestones

- [x] M1: Inventory data-dependent public surfaces and freeze the common declaration, evidence,
  resolution, plan, and unavailable-output contracts with focused tests.
- [x] M2: Implement the common requirement kernel and structured error builder.
- [x] M3: Migrate execution-profile declaration and planning to the common public contracts.
- [x] M4: Migrate `group_demean`, operation/extension declarations, and exposure requests/results.
- [x] M5: Wire CLI, schemas, installed help, generated skill, architecture, and implementation log.
- [x] M6: Run focused and complete validation, preserve journey evidence, and close the plan.

## Progress

- 2026-07-29: User selected full common-contract/public-profile migration (option A).
- 2026-07-29: User required current PRD behavior and preservation of user/agent journey scenarios.
- 2026-07-29: User explicitly deferred `beta_residualize`; it is a non-goal.
- 2026-07-29: Baseline evidence from the immediately preceding review is 110 passing tests and
  clean Ruff lint; formatter drift is recorded above.
- 2026-07-29: Added dependency-free `qlibx.requirements` declarations, evidence, evaluator,
  resolution, plan, and unavailable-output types plus the stable requirement-gap error builder.
- 2026-07-29: Removed the `ExecutionProfilePlan` public shape and migrated execution profile
  declaration/planning/readiness to the common public contract.
- 2026-07-29: Replaced `OperationSpec.requires_groups` with common requirements, added operation
  planning, and connected group-demean plan/runtime failures to one resolution.
- 2026-07-29: Made exposure metrics explicit; added default structured failure and explicitly
  incomplete artifacts with typed unavailable outputs.
- 2026-07-29: Updated CLI, schemas, error guidance, generated skill, architecture, handoff status,
  public API tests, and implementation record.

## Discoveries

- The common requirement model must be reusable as a normal read-only plan/result and as serialized
  error context; it cannot be owned only by `errors.py`.
- Public-contract migration and internal commonality are deliberately coupled in this task:
  `ExecutionProfilePlan` will not remain as a compatibility adapter.
- Current registered-data surfaces are execution profiles, group demeaning, exposure requests, and
  signal-transform operation declarations. Other public modules consume explicit DataFrames or
  stored artifacts and did not need invented registered-data requirements.
- The first full suite had one expected assertion failure: exact root `__all__` did not yet list the
  newly public `requirements` responsibility. Migrating that repository-owned assertion resolved
  it; no behavior or journey test failed.

## Decision log

- Follow current canonical P8 rather than revisiting the product scope.
- Use option A: one public common contract and migrate the execution-profile public result.
- Preserve stable `QlibxError` transport while adding typed requirement-resolution payloads.
- Keep beta estimation and beta residualization untouched.

## Validation

- Focused contract/profile/alpha/architecture/docs/CLI/onboarding suite -> 51 passed.
- First full `uv run pytest` -> 116 passed, one expected root-public-surface assertion failed and
  was migrated.
- Final `uv run pytest` -> 118 passed, including installed P0/P1 agent onboarding/data registration
  and a project-local operation using the same public requirement contract
  and all Strategy/Qlib/research/reporting journeys.
- `uv run ruff check .` -> all checks passed.
- `uv run ruff format --check .` -> 116 files already formatted.
- `uv build` -> built `dist/qlibx-0.1.0.tar.gz` and `dist/qlibx-0.1.0-py3-none-any.whl`.

## Risks and recovery

- This is an intentional public contract change at version 0.1.0. Update every repository-owned
  consumer, installed example, schema, and generated skill in the same change.
- A universal model can become too broad. Keep the kernel declarative and pure; catalog/project
  inspection belongs in capability adapters.
- Optional exposure gaps are not always exceptions. Preserve one typed resolution that can be
  embedded in a plan, error context, or artifact.
- All edits remain local and uncommitted. Recover with file-level patches only; never reset user
  work or unrelated changes.

## Next action

Complete. No approval-required action remains; changes are local and uncommitted.
