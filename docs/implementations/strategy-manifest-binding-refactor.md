# Strategy manifest and binding refactor

## Why this change exists

User-authored Strategies need canonical pandas data such as `open_price` and `close_price`, while
registered source data may preserve opaque fields such as `시가` and `종가`. Basic registration
cannot safely assign Strategy-specific economic semantics because the same registered data can
serve different capabilities and the package cannot infer meaning from similar names.

The previous `StrategyDefinition.data_requirements` tuple named whole datasets only. It could not
declare required columns, express fixed lookback input contracts, inspect registered field
inventory, or record a project-specific mapping separately from Strategy identity. The shared
capability requirement contract also embedded literal interview questions, which mixed agent
wording with product facts.

## User and system outcome

A user-side agent can now:

1. author a plain pandas Strategy callable below the trusted project extension root;
2. declare its invariant requirements in `config/qlibx/strategies/*.yaml`;
3. run a read-only plan that reports missing roles and the exact registered field inventory;
4. propose an exact mapping to the user and wait for approval;
5. write only the approved mapping to `config/qlibx/bindings/*.yaml`;
6. validate and preview point-in-time fixed-lookback pandas inputs; and
7. run a weight Strategy inside the existing Qlib decision and confirmed-feedback loop.

Every Strategy inherits an explicit point-in-time `universe` requirement. Strategy code receives
only canonical pandas objects and ordinary parameters; it does not read registration, catalog,
project, YAML, runner, or agent APIs.

## Responsibility and flow changes

`qlibx.strategy_manifest` is the project adapter and composition boundary.

- `StrategyManifest` owns stable Strategy identity/version, trusted callable reference,
  parameters, positive fixed-row lookback, canonical pandas input/field contracts, and output kind.
- `StrategyBinding` owns only Strategy identity, registered logical dataset IDs, and exact
  canonical-to-registered field mappings.
- The `qlibx.pandas_strategy` base contract contributes `universe`; manifests cannot redeclare it.
- `plan_strategy_binding` adapts manifest inputs to the common `CapabilityRequirements` kernel and
  evaluates catalog evidence. Its parameters include registered field inventory and effective
  config identity. It never proposes a mapping or writes config.
- `StrategyInputResolver` validates the manifest/binding/catalog once, then resolves every decision
  with `as_of` availability filtering, fixed-period tailing, canonical renaming, dtype/null checks,
  and universe ticker alignment. Event time may be later than decision time when the registered
  availability contract says the future event was already known.
- Universe resolution pivots registered rows before boolean conversion and rejects duplicate or
  missing date/ticker membership. Absence is never inferred as membership and a pandas boolean cast
  cannot turn a missing cell into an eligible instrument.
- `invoke_pandas_strategy` validates the plain callable signature, detects pandas input mutation,
  and requires pandas output.
- `run_manifest_strategy_execution` freezes the resolver and trusted callable once, then uses
  `pandas_decision_program` inside the existing Qlib callback. It verifies registered and execution
  universe equality at each decision and submits only the latest weight row.

The existing adaptive `StrategyDefinition`/`DecisionContext` path remains for feedback, memory,
checkpoint, and nested what-if behavior. It now inherits universe through
`StrategyDefinition.all_data_requirements`; Qlib execution injects the actual scenario universe,
and child contexts inherit the parent universe automatically while retaining their narrowing
constraints.

The common requirement kernel no longer stores `user_questions`. Declarations and resolutions
return facts, alternatives, reasons, and next commands. The generated skill owns interview
wording and forbids writing a binding before user approval. Binding YAML does not contain question
text, confirmation status, or a duplicated pandas contract.

Public documentation now includes strict manifest/binding schemas and examples. The CLI exposes:

- `qlibx strategy requirements`
- `qlibx strategy plan`
- `qlibx strategy preview`

## Alternatives and trade-offs

Keeping Python `CapabilityRequirement` constants beside each user Strategy was rejected because a
user-side agent would have to edit executable declarations and couple Strategy source to qlibx
domain objects.

Putting required fields and source mappings in one YAML was rejected because a Strategy's semantic
contract is versioned independently from each project's datasets. It would also force duplicate
manifests for raw/adjusted or market-specific bindings.

Recording literal questions or `confirmation.status` in binding YAML was rejected. Core cannot
prove that a human conversation occurred, and wording changes by agent, language, and context.
The durable project choice is the valid binding; the generated skill enforces the approval policy.

A general dependency-injection container was rejected for Strategy composition. Parent Strategies
can call child plain-pandas callables directly with equal or narrower already-bounded data. DI is
used only at the infrastructure boundary where qlibx constructs the resolver and Qlib callback.

Resolving and validating the entire catalog on every decision would be wasteful. The resolver
freezes manifest/binding/catalog validation once and repeats only point-in-time data resolution.
This still performs catalog reads per decision; a future optimization may add safe snapshot-local
query caching without changing the public contract.

## Validation

Completed during implementation:

- Common requirement/profile/alpha/documentation focused tests: 28 passed; three onboarding
  fixtures initially could not start because the managed Windows user temp path was inaccessible.
- New manifest/binding/resolver/callable tests: 4 passed, including exact Korean field mapping,
  inherited universe, fixed two-period lookback, CLI plan/preview, direct child pandas composition,
  and the Qlib decision-loop adapter.
- Existing adaptive Strategy, nested child, Qlib checkpoint/resume, and public contract tests:
  15 passed after migrating explicit test contexts to the inherited universe contract.
- A 61-test focused suite reached 60 passed; its single assertion found capitalization drift in an
  existing generated-skill phrase and was corrected.

Final full-suite, lint, format, build, and acceptance results are recorded after completion below.

- Final focused regression including P0/P1 acceptance -> 73 passed.
- Final complete suite -> 125 passed.
- Post-format CLI/documentation/Strategy/architecture smoke -> 38 passed.
- `uv run ruff check .` -> all checks passed.
- `uv run ruff format --check .` -> 120 files already formatted.
- `uv build` -> built `dist/qlibx-0.1.0.tar.gz` and
  `dist/qlibx-0.1.0-py3-none-any.whl`.
- `git diff --check` -> passed; Git emitted only the repository's Windows LF-to-CRLF notices.

The first root Ruff run panicked while traversing an inaccessible `.pytest_cache`. Adding the
standard `.pytest_cache/` ignore entry prevented traversal; the exact manifest-declared root
commands then passed.

## Remaining limitations and follow-up

- Only positive fixed row-count lookbacks are supported by Strategy manifest schema version 1.
  Duration, event-count, or independently configured per-input lookbacks require a versioned schema
  extension.
- Plain manifest execution currently accepts weight output for direct Qlib submission. Signal
  output requires an explicit signal-to-weight Strategy or transform.
- Project-local Strategy code is trusted code, not sandboxed code.
- Basic registration policy preserves semantic opacity through documentation and generated skill;
  the registration format remains capable of user-confirmed output naming for non-Strategy uses.
- Beta estimation and `beta_residualize` remain intentionally untouched.
