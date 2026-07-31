# Refactor Strategy requirements into manifest and binding contracts

Status: complete

## Purpose

Make the user-approved Strategy architecture real: user-authored Strategy implementations receive
only canonical pandas inputs, declarative YAML manifests state what each Strategy needs, separate
project YAML bindings record which registered dataset fields satisfy those needs, and the agent
skill owns the user interview before writing a binding.

## Scope and non-goals

- Use `docs/qlibx-prd.md` as the canonical product contract and update its uncommitted draft to the
  final manifest/binding decision.
- Update `docs/qlibx-architecture.md` so it describes the implemented, not aspirational, structure.
- Add strict immutable Strategy manifest and binding contracts, YAML loaders, a read-only
  requirement plan, registered-data resolver, fixed-row lookback handling, and plain-pandas
  callable invocation.
- Inherit the mandatory `universe` requirement from the common pandas Strategy contract.
- Keep basic registration semantically opaque; field renaming occurs only in the resolved
  Strategy input view.
- Generate agent guidance that proposes mappings, obtains user approval, then writes binding YAML;
  core plans expose facts and never embed conversational question strings.
- Preserve existing user/agent, Strategy, nested-Strategy, and Qlib closed-loop journeys.
- Keep the existing adaptive `DecisionContext` execution API as a compatibility path during this
  refactor; do not make it the authoring contract for new plain-pandas Strategies.
- Do not implement or change `beta_residualize`, beta estimation, dependencies, user source data,
  or Qlib accounting.
- Do not stage, commit, push, or publish without a new explicit user request.

## Acceptance criteria

- A strict Strategy manifest YAML declares implementation identity, parameters, output, fixed
  lookback, and canonical pandas input/field requirements without source field names.
- Every loaded manifest inherits a mandatory point-in-time `universe` input.
- A separate strict binding YAML references only catalog-registered logical dataset IDs and maps
  canonical fields to exact registered fields without duplicating the pandas contract or storing
  question/confirmation text.
- A read-only plan returns the common capability declaration/resolution plus registered field
  inventory and exact binding validation; an unresolved mapping cannot produce `ready=true`.
- The resolver enforces config containment, manifest/binding ID and version agreement, dataset and
  field existence, pandas shape/dtype expectations, point-in-time `as_of`, fixed-row lookback,
  universe alignment, and canonical field naming before invoking Strategy code.
- A plain Strategy callable can be authored with pandas and Python standard types only and can
  directly compose child pandas Strategies within its already-bounded inputs.
- Installed schema/help/generated skill expose the manifest/binding workflow without
  `user_questions`.
- Existing acceptance journeys and the complete declared validation suite pass.
- A production implementation record explains responsibility changes and validation evidence.

## Repository context

- `src/qlibx/strategy.py` currently owns `StrategyDefinition`, `DecisionContext`, nested research,
  and sequence execution. `StrategyDefinition.data_requirements` is only a tuple of dataset names.
- `src/qlibx/execution.py::run_strategy_execution` supplies independently bounded DataFrames to a
  `DecisionProgram` at each Qlib decision step.
- `src/qlibx/requirements.py` is the dependency-free common kernel but currently embeds literal
  `user_questions` in declarations and resolutions.
- `src/qlibx/catalog.py` resolves only project-declared logical datasets and is the correct boundary
  for binding references; raw paths must never appear in Strategy bindings.
- `src/qlibx/skill.py` currently tells agents to ask declaration-provided `user_questions`; that is
  replaced by generic skill policy and fact-based plans.
- `docs/qlibx-prd.md` has an uncommitted draft that correctly separates basic registration and
  capability binding but still duplicates pandas contracts and confirmation records in binding
  YAML. Preserve the useful draft and correct these stale parts.
- Baseline commit is `15cf9ae`; only `docs/qlibx-prd.md` is modified before this task.

## Milestones

- [x] M1: Finalize the PRD and architecture contracts, exact YAML shapes, responsibility boundaries,
  and executable guardrails.
- [x] M2: Remove conversational strings from the common requirement kernel and migrate all current
  consumers, schemas, help, skill text, and tests.
- [x] M3: Implement immutable Strategy manifest/binding models, strict loaders, common requirement
  adaptation, field inventory planning, pandas resolver, and plain callable invocation.
- [x] M4: Add public CLI/schema/examples/skill workflow and focused tests including Open Close
  Rebound, mandatory universe, fixed lookback, invalid mappings, and nested pandas composition.
- [x] M5: Update architecture details and implementation log, run focused and complete validation,
  and close the plan.

## Progress

- 2026-07-29: User approved the separate Strategy manifest and Strategy binding architecture and
  requested architecture documentation plus codebase refactoring.
- 2026-07-29: Loaded canonical project context, plan policy, package workflow, implementation-log
  rules, current architecture, current PRD draft, source contracts, tests, and prior capability
  implementation record.
- 2026-07-29: Task contract set: plain pandas authoring path, inherited universe, registered-only
  binding, skill-owned interview, fixed-row lookback, preserved legacy journeys, no beta work.
- 2026-07-29: Removed `user_questions` from the common requirement declaration/resolution and
  migrated execution profile, alpha operation/exposure, schema, skill, and focused tests.
- 2026-07-29: Added strict immutable manifest/binding models, inherited universe, common requirement
  adaptation, registered field inventory, `StrategyInputResolver`, fixed-lookback projection,
  canonical rename, and plain callable validation.
- 2026-07-29: Added `strategy requirements|plan|preview`, installed schemas/examples, generated
  skill policy, and resolver-backed Qlib execution. Adaptive Strategy and child contexts now
  inherit universe.
- 2026-07-29: Updated the canonical PRD draft, as-is architecture, and implementation record.

## Discoveries

- The common requirement evaluator currently treats conversational wording as domain data. This
  conflicts with the approved boundary: core should expose missing facts and alternatives; the
  generated skill decides how to conduct the interview.
- The existing catalog is already the raw-path firewall. A binding should name a logical dataset
  known to `DataCatalog`, then the resolver may inspect and project its query output.
- A Strategy binding must not repeat dtype/layout/lookback semantics because those belong to the
  versioned manifest. Repetition would permit two conflicting contracts.
- Direct child composition is simplest in the plain-pandas authoring surface: a parent calls a
  child callable with equal or narrower already-bounded pandas objects. qlibx need not inject a
  general DI container.
- Injecting universe exposed a latent `DatetimeIndex.le` use. The installed pandas requires the
  equivalent `index <= decision_time` comparison on the no-explicit-availability path.
- A final design review caught two semantic hazards: event time later than decision time is valid
  when availability is already known, while missing universe membership must be rejected before
  pandas boolean conversion. Focused tests now lock both behaviors.

## Decision log

- Use two project config documents: Strategy manifest for invariant requirements, Strategy binding
  for environment-specific dataset/field choices.
- Treat binding existence as the durable project choice. Do not claim that core can prove a human
  conversation occurred; the skill forbids writing before approval.
- Inherit `universe` from contract `qlibx.pandas_strategy` rather than duplicating it in each
  manifest.
- Keep fixed lookbacks declarative and row-based in this milestone; duration/event-count variants
  can be added as versioned schema extensions.
- Preserve the adaptive `DecisionContext` API for existing execution journeys while making the new
  plain-pandas callable path the agent-authored Strategy surface.
- Freeze Strategy plan/catalog validation once per execution, resolve observations at every Qlib
  decision, and require registered universe to match execution universe.

## Validation

- Baseline working tree: only `docs/qlibx-prd.md` modified; commit `15cf9ae`.
- Common requirement focused checks -> 28 passed; three onboarding fixture setup errors came from
  the managed Windows temp path, not assertions.
- New Strategy manifest/binding tests -> 4 passed, including Qlib loop integration.
- Existing adaptive Strategy/Qlib/public-contract tests -> 15 passed after universe migration.
- Broad focused suite -> 60 passed and one skill capitalization assertion failed; phrase
  compatibility was restored before final validation.
- Final focused regression including P0/P1 -> 73 passed.
- Final complete `uv run pytest` -> 125 passed.
- Post-format CLI/documentation/Strategy/architecture smoke -> 38 passed.
- `uv run ruff check .` -> all checks passed.
- `uv run ruff format --check .` -> 120 files already formatted.
- `uv build` -> source distribution and wheel built successfully after the isolated build
  environment was allowed to resolve `uv-build`.
- `git diff --check` -> passed with only expected Windows line-ending notices.
- Validation commands to run: focused Strategy/requirements/docs/CLI/architecture/acceptance tests,
  `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, and `uv build`.

## Risks and recovery

- Removing `user_questions` touches all common-requirement consumers. Migrate in one bounded
  milestone and use repository-wide search plus focused tests.
- Loading arbitrary Strategy code is trusted project-local execution, not sandboxing. Contain the
  source path under the configured extensions root and record its digest.
- Catalog queries may be expensive. Field inventory and preview must use bounded/zero-or-small-row
  reads and remain read-only.
- Preserve the pre-existing PRD draft through targeted patches; never reset the worktree.

## Next action

Complete. Move this plan to `.agent/plans/completed/`. No staging, commit, push, or publication was
authorized.
