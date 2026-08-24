# Final Consensus Plan: vqapr Agent-First Python API

Status: pending approval

## Consensus Receipts
- Planner initial: `05818437c7981c476eb0bc627c093126f74aa9e89fc1d47c3fe5ec3928888287`
- Revision 2: `397137c38099e717e89fd5d6bc9d060b0714446a1f435683066f3da0f77dcadd`
- Revision 3: `5756bb06d1e512764032d35c463e37fa4c6f773c4bcf149924725b83bdf825a5`
- Architect pass 3: `3706f3fb2894dc99937dedbf4e0a62e6de81b5fbff315f87af3e41f384157fc8` — CLEAR/APPROVE
- Critic pass 3: `9e7dfc0a6ed57d66d22b73ea7bec143ec37b8176476657d80dbd827bcba00e7e` — OKAY
- Intent reconciliation: `cbf78ea2ba82e3d15124a705c908153f615f850bd0fabb99df787da9dea2f387` — reconciled-clean

## ADR
### Decision
Replace the flat, authority-leaking Python API with one Project facade, complete immutable declarations, named/typed model inputs, semantic atomic model results, atomic publication, and capability namespaces. Move retained authority code under `vqapr._internal` and remove every old qualified/public route in one breaking `0.2.0a1` cutover.

### Drivers
1. AI agents should author economic decisions, not registry/fingerprint/preflight/provenance/evidence object graphs.
2. Dataset, lookback, cadence, execution, exchange, account, constraints, budget and outputs must remain explicit.
3. Existing registry/PIT/Flow/run-state machinery is valuable but belongs behind one authority boundary.
4. Scientific output and replay evidence must remain exact across the migration.

### Alternatives Considered
- Rename/re-export existing primitives: rejected because authority remains caller-owned.
- Replace registry/Flow engine: rejected because it duplicates mature machinery and raises parity risk.
- God function or fluent builder: rejected because it hides omitted economics and creates partial/order state.
- Supported low-level escape hatch: rejected because it recreates an alternate lifecycle.

### Why Chosen
Project + immutable declarations is the smallest cohesive interface that reduces ceremony without choosing economics. Candidate-catalog CAS and content-addressed publication provide falsifiable atomicity. Named semantic model contracts eliminate positional and provenance leaks.

### Consequences
- Deliberate breaking release and physical module relocation.
- Significant cross-repo migration and exact parity fixtures before deletion.
- No compatibility aliases; rollback is whole-release revert.
- More complete declaration types, but fewer lifecycle concepts in user code.

### Follow-ups
- Execute only after explicit approval.
- Stop before commit/push for owner review as required by both repositories.

## Consolidated Implementation Plan

# vqapr Agent-First Python API — Consensus Revision 2

## Summary

Deliver one intentionally breaking `vqapr` release from `../qlibx`, then migrate and verify the real `vqapr-testbed-2` consumer. The only supported lifecycle is:

```python
import vqapr

project = vqapr.open(root)             # read-only open
project.register(declaration)          # only external declaration mutation door
result = project.materialize(...)      # preparation + execution
completed = project.run(...)           # preparation + execution
published = completed.publish(...)     # one atomic visibility transaction
```

`Project` owns identity, registration, candidate-catalog preparation, preflight, execution wiring, source/access provenance, state/evidence commit, and publication. Data/strategy classes declare named semantic inputs and return semantic rows/results only. The retained registry, PIT scanner, Flow, run-state root, loader, and evidence machinery are moved below `vqapr._internal`; no former qualified route remains importable.

This revision incorporates architect receipt `4b136b659f9e08cdd7cb3db7621b4b5cf25c3917a480cf57daa68c74688f7414`, critic receipt `782ab7fe10d3e6fad23d881ce0bc45ab39bf70396525d108785e24a396487fdd`, intent receipt `3cf5debb6f014b36d195c2b22e4727f7140f0651fd39e129b63b386b5fe237ec`, and prior planner receipt `05818437c7981c476eb0bc627c093126f74aa9e89fc1d47c3fe5ec3928888287`.

Locked intent IDs preserved literally and substantively:

- `artifact:api-spec`
- `surface:project-workflow`
- `surface:model-authoring`
- `integration:runtime-internals`
- `constraint:agent-first`
- `constraint:economic-explicitness`
- `constraint:hard-removal`

Evidence remains grounded in the current repositories: `../qlibx/src/vqapr/public.py` exposes the flat low-level surface; `workspace.py` commits declarations one at a time; `flow/materialize.py` makes a single dataset visible through multiple physical steps; `flow/simulation.py` reuses one strategy instance; and testbed `register.py`, `build_characteristics.py`, `build_factors.py`, both model files, and `measure_session_effect.py` import removed or private contracts.

## Intent Diff

| Existing evidenced behavior | Required behavior |
|---|---|
| `vqapr.public` exports `Workspace`, `ComponentRef`, `RunDefinition`, registration functions, preflight/run/publish functions, raw store/account/evidence types. Direct qualified modules are importable. | Top-level `vqapr.__all__` is exactly `("VqaprError", "open", "project", "authoring", "materialization", "simulation", "portfolio", "methodologies", "venues", "analysis", "testing")`. `vqapr.public` and every former qualified lifecycle/internal route fail to import. |
| Workspace validates/persists declarations individually; preflight reads committed Workspace state. | Project prepares an in-memory candidate catalog, validates/conforms/preflights against that exact catalog, then uses a locked generation-and-digest CAS to install one catalog root. `Project.open()` never creates a workspace. |
| Fingerprint uses caller path/component kind/object/config and workspace uses caller component IDs. | Schema-versioned fingerprint has a fixed byte preimage based on stable module bytes, qualname, typed canonical config, kind, and package version; framework derives opaque authority ID. Human name/path never contributes. |
| Models declare positional/indexed `DataRequirement`, receive raw row windows, directly mutate `memory`/`recorder`, and return raw authority intent. | Models declare unique aliases and semantic schema; each invocation has a fresh instance and returns `DerivedRow` or `StrategyResult(Hold|Rebalance, next_state, diagnostics)`. One callback candidate root stages all semantic and framework-owned facts before one commit. |
| Publication links/parquet-publishes then registers each output independently; allocation and records have separate public calls. | All output objects are immutable content-addressed objects. One catalog-root CAS is the only visibility operation for every output registration in a `Publication`; unreachable objects are invisible recoverable orphans. |
| Testbed only partially migrates in prior plan. `register.py` imports `vqapr.public` and `vqapr.data.datasets.validate`; `measure_session_effect.py` imports `vqapr.data.*`, Workspace, and old requirements. | Full testbed scan/migration covers scripts, models, declarations, docs, operations, handoff, lock/dependency and removed/private imports. `register.py` uses Project declarations/receipt timings; `measure_session_effect.py` is retired as obsolete private-mechanism benchmark and replaced by the canonical same-shape performance harness. |

## Decision Drivers

1. Preserve all research economics explicitly: raw source/field/key/availability mapping; every lookback; output materialization dates/universe; daily strategy/valuation/monitoring sessions/times/timezone/horizon; exchange access/listings/grids/costs; execution input/fill/price; account/mode; ordered constraints including `()`; strategy state rule; targets/cash/budget; publication output/table/fields; Fama–French reference/fractions/labels.
2. Make one authority boundary real in Python, not merely curated by `__all__`: retained mechanisms must physically move beneath `_internal`, and old public-looking qualified modules must be deleted without forwarding shims.
3. Preserve the existing immutable run-state root pattern, but make returned state and declared diagnostics the only author-controlled callback effects.
4. Make declaration preparation concurrency-safe and publication crash-safe with a single catalog-root visibility authority.
5. Pin identity and parity as reproducible byte contracts, not descriptions. The testbed’s editable sibling dependency proves development behavior; it does not prove a released wheel.
6. No compatibility surface, no inferred economic values, no alternate lifecycle API, no experiment manager, and no unrelated CLI redesign.

## Options

### A. Selected — Project facade over moved private authority, two root transactions

Move retained engine code to `vqapr._internal`; add thin public capability modules and a `Project` facade. Use (1) a candidate-catalog generation CAS for declaration/preflight preparation and (2) the existing immutable run-state root extended with one semantic callback candidate. Publish immutable objects first and make them visible only by one catalog-root CAS.

**Selected:** preserves tested PIT/Flow/evidence logic, closes all former imports, supplies falsifiable concurrency/crash semantics, and permits checkpoints that work end-to-end before destructive public-path removal.

### B. Rejected — namespace/re-export cleanup only

Keep `Workspace`, `ComponentRef`, `RunDefinition`, `preflight_run`, `run`, and publishers under renamed public modules.

**Rejected:** callers still control registration, identity, preflight, provenance, and publication; direct imports still bypass Project. It violates `surface:project-workflow`, `surface:model-authoring`, and `constraint:hard-removal`.

### C. Rejected — recreate registry/Flow/persistence under Project

Replace current registration, scan, preflight, Flow, state, and publication implementations wholesale.

**Rejected:** duplicates mature mechanisms, increases trace/parity risk, and is unnecessary once former qualified routes are physically removed. The defect is authority placement, not the internal engine’s capability.

### D. Rejected — sequential multi-file renames plus exception cleanup for publication

Publish allocation and records one by one and delete files on caught exceptions.

**Rejected:** cannot guarantee process-crash consistency or concurrent visibility. A catalog root is the only durable visibility authority.

## Public declaration algebra and exact export homes

All public declaration classes below are `@dataclass(frozen=True, slots=True, kw_only=True)`. Every tuple is ordered; `Mapping` is copied/validated into an immutable canonical view. Any omitted field is a constructor error; deliberate absence uses the explicitly permitted `None` or `()` shown below. Constructors reject duplicate names, empty identifiers, naive datetimes, non-finite `Decimal`, untyped/unsupported canonical config values, and author-supplied framework-envelope fields.

### Exact module/export matrix

| Public home | Exact exported names | Notes |
|---|---|---|
| `vqapr` | `VqaprError`, `open`, `project`, `authoring`, `materialization`, `simulation`, `portfolio`, `methodologies`, `venues`, `analysis`, `testing` | Exact `__all__`; `open` is `project.open`. |
| `vqapr.project` | `Project`, `open`, `ProjectDeclaration`, `DatasetDeclaration`, `ExecutionInputDeclaration`, `ExtensionDeclaration`, `RegistrationReceipt`, `RegistrationTiming`, `CatalogConflict`, `PublicationConflict` | Only home for registration declarations and receipt/conflict facts. |
| `vqapr.authoring` | `RowsLookback`, `CalendarLookback`, `DatasetInput`, `Observation`, `Output`, `DerivedRow`, `DataCall`, `DataModel`, `DiagnosticTable`, `StrategyCall`, `StrategyModel`, `Hold`, `Rebalance`, `StrategyResult` | Only home for extension authoring/read/result contracts. |
| `vqapr.materialization` | `Materialization`, `MaterializationResult`, `MaterializationInvocation` | A model owns `Output`; caller never supplies output fields. |
| `vqapr.simulation` | `ExecutionInput`, `FillConvention`, `FillSelector`, `Cadence`, `Schedule`, `Execution`, `InitialAccount`, `AccountSnapshot`, `AccountMode`, `ConstraintDeclaration`, `Simulation`, `Publication`, `AllocationOutput`, `RecordOutput`, `CompletedRun`, `PublishedRun` | Only home for run, account, execution, constraint, and publication declarations. |
| `vqapr.portfolio` | `Budget`, `PortfolioDirection` | Semantic economic budget only; no intent, optimizer, allocation checker, or account engine. |
| `vqapr.methodologies.fama_french` | `cut_points`, `assign` | Keep the current operation behavior under the exact methodology capability; reference set/fractions/labels stay explicit arguments. |
| `vqapr.venues` | `Academic`, `Listing`, `ListingAccess`, `VenueCost` | `Academic` requires explicit listings/access/quantity step/price step/costs; no academic shortcut/default. |
| `vqapr.analysis` | `returns`, `nav_series`, `drawdown`, `information_coefficient`, `rank_information_coefficient`, `hit_rate`, `decay` | Analysis only; no storage/read handles. |
| `vqapr.testing` | `conformance` | Supported extension contract test entry only; no runtime/store escape. |

`vqapr.project.ProjectDeclaration` is the closed union:

```python
ProjectDeclaration: TypeAlias = (
    DatasetDeclaration | ExecutionInputDeclaration | ExtensionDeclaration
)
```

No other runtime type, mapping/YAML shape, old `ComponentRef`, raw source registration, or private class is accepted by `Project.register`.

### Exact registration declarations

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class DatasetDeclaration:
    dataset_id: str
    path: Path
    hive_partitioned: bool
    instrument_field: str
    available_at_field: str
    key_fields: tuple[str, ...]
    fields: Mapping[str, str]

@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionInputDeclaration:
    input: simulation.ExecutionInput

@dataclass(frozen=True, slots=True, kw_only=True)
class ExtensionDeclaration:
    extension: type[authoring.DataModel | authoring.StrategyModel | Constraint]
    config: Mapping[str, object]
    name: str
```

`DatasetDeclaration.path` is caller-owned physical source selection, while source digest and internal source identity are framework-owned. `dataset_id` is a user semantic selection; it is not an authority identity. `hive_partitioned` is explicit because it changes physical read behavior. `fields` maps semantic framework field name to physical column name. `available_at_field` and `key_fields` remain explicit because the framework cannot infer the economics of availability/keying.

`ExtensionDeclaration` is accepted only for pre-registering a constraint or testing an extension. `Project.materialize(model=...)` and `Project.run(strategy=...)` create the same internal extension registration candidate themselves; callers never construct a ref/kind/fingerprint. Built-in and local classes go through this identical pathway. `name` is non-empty human diagnostics text only and never enters identity.

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionInput:
    input_id: str
    path: Path
    hive_partitioned: bool
    trade_at_field: str
    instrument_field: str
    is_tradable_field: str
    price_fields: Mapping[str, str]

@dataclass(frozen=True, slots=True, kw_only=True)
class FillConvention:
    selector: FillSelector
    at: time
    timezone: str
    trade_price: str

@dataclass(frozen=True, slots=True, kw_only=True)
class ConstraintDeclaration:
    constraint: type[Constraint]
    config: Mapping[str, object]
    name: str
```

`ExecutionInputDeclaration(input=...)` is mandatory before a `Simulation` references the `input_id`; the `input_id` is an explicit human binding key, while its internal authority identity is framework-derived. `ConstraintDeclaration` is carried in ordered `Simulation.constraints`; Project prepares/registers it atomically with the run. It can also be submitted via `ExtensionDeclaration` to preflight/validate early. A fresh project needs no public source/ref/loader type.

### Exact materialization, authoring, simulation, and publication contracts

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class Materialization:
    output_dataset_id: str
    evaluation_times: tuple[datetime, ...]
    instruments: tuple[str, ...]

@dataclass(frozen=True, slots=True, kw_only=True)
class DatasetInput:
    dataset_id: str
    fields: tuple[str, ...]
    lookback: RowsLookback | CalendarLookback

@dataclass(frozen=True, slots=True)
class Observation:
    instrument_id: str
    available_at: datetime
    values: Mapping[str, object]

@dataclass(frozen=True, slots=True, kw_only=True)
class Output:
    semantic_fields: tuple[str, ...]

@dataclass(frozen=True, slots=True, kw_only=True)
class DerivedRow:
    instrument_id: str
    values: Mapping[str, object]

class DataCall:
    evaluation_time: datetime
    def read(self, alias: str) -> tuple[Observation, ...]: ...

class DataModel:
    def inputs(self) -> Mapping[str, DatasetInput]: ...
    def output(self) -> Output: ...
    def compute(self, call: DataCall) -> tuple[DerivedRow, ...]: ...

@dataclass(frozen=True, slots=True, kw_only=True)
class DiagnosticTable:
    table_id: str
    semantic_fields: tuple[str, ...]

@dataclass(frozen=True, slots=True, kw_only=True)
class Hold:
    reason: str

@dataclass(frozen=True, slots=True, kw_only=True)
class Rebalance:
    target_weights: Mapping[str, Decimal]
    cash_weight: Decimal
    budget: portfolio.Budget

@dataclass(frozen=True, slots=True, kw_only=True)
class StrategyResult:
    decision: Hold | Rebalance
    next_state: object
    diagnostics: Mapping[str, tuple[Mapping[str, object], ...]]

class StrategyCall:
    evaluation_time: datetime
    account: EconomicAccountView
    previous_state: object
    account_history: DeclaredAccountHistory
    constraint_bounds: ConstraintBounds
    def read(self, alias: str) -> tuple[Observation, ...]: ...

class StrategyModel:
    def inputs(self) -> Mapping[str, DatasetInput]: ...
    def diagnostics(self) -> tuple[DiagnosticTable, ...]: ...
    def decide(self, call: StrategyCall) -> StrategyResult: ...
```

`inputs()` aliases are non-empty and unique. `DiagnosticTable` is preparation-time schema; `StrategyResult.diagnostics` must contain exactly declared table IDs, and each row must contain exactly that table’s semantic fields. `diagnostics()` returns explicit `()` when no diagnostics exist. The framework rejects reserved identity/provenance/envelope names and adds `observed_at`, producer, stage, event time, sequence, source references, lineage, versions, and state references itself.

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class Cadence:
    sessions: tuple[date, ...]
    at: time
    timezone: str

@dataclass(frozen=True, slots=True, kw_only=True)
class Schedule:
    strategy: Cadence
    valuation: Cadence
    monitoring: Cadence | None
    start: datetime
    end: datetime

@dataclass(frozen=True, slots=True, kw_only=True)
class Execution:
    input: ExecutionInput
    fill: FillConvention

@dataclass(frozen=True, slots=True, kw_only=True)
class InitialAccount:
    snapshot: AccountSnapshot
    mode: AccountMode

@dataclass(frozen=True, slots=True, kw_only=True)
class Simulation:
    schedule: Schedule
    execution: Execution
    exchange: venues.Academic
    account: InitialAccount
    constraints: tuple[ConstraintDeclaration, ...]
    instruments: tuple[str, ...]
    initial_strategy_state: object

@dataclass(frozen=True, slots=True, kw_only=True)
class AllocationOutput:
    dataset_id: str
    value_field: str

@dataclass(frozen=True, slots=True, kw_only=True)
class RecordOutput:
    dataset_id: str
    table_id: str
    semantic_fields: tuple[str, ...]

@dataclass(frozen=True, slots=True, kw_only=True)
class Publication:
    allocation: AllocationOutput | None
    records: tuple[RecordOutput, ...]
```

`monitoring=None`, `constraints=()`, and `initial_strategy_state=None` are required explicit values, not defaults. `Publication.allocation=None` is explicit when no allocation is selected; `records=()` is explicit when no diagnostic record is selected; `Publication` must select at least one output. `Rebalance` is a complete target set, missing instruments mean zero, liquidation is `{}` plus `cash_weight=Decimal("1")`, cash/weights must close exactly, and any exception is failure rather than a Hold fallback.

### Fresh registration example

```python
from pathlib import Path
import vqapr
from vqapr import project, simulation

p = vqapr.open(Path("research-project"))  # does not create .vqapr

prices = project.DatasetDeclaration(
    dataset_id="stock_daily",
    path=Path("prepared/stock_daily.parquet"),
    hive_partitioned=False,
    instrument_field="instrument",
    available_at_field="available_at",
    key_fields=("available_at", "instrument"),
    fields={"ret": "ret", "market_cap": "market_cap", "is_trading_halt": "is_trading_halt"},
)
execution = project.ExecutionInputDeclaration(
    input=simulation.ExecutionInput(
        input_id="krx-daily",
        path=Path("prepared/execution.parquet"),
        hive_partitioned=False,
        trade_at_field="trade_at",
        instrument_field="instrument",
        is_tradable_field="is_tradable",
        price_fields={"close": "close"},
    )
)
price_receipt = p.register(prices)
execution_receipt = p.register(execution)
```

`RegistrationReceipt` exact fields are `created: bool`, `declaration_kind: str`, `authority_id: str`, `fingerprint: str | None`, `catalog_generation: int`, `timing: RegistrationTiming`, and `diagnostics: tuple[Diagnostic, ...]`. Dataset registration reports no extension fingerprint (`None`); source digest and all physical paths are omitted from receipts. `RegistrationTiming` reports `schema_seconds`, `key_seconds | None`, `conformance_seconds | None`, and `preparation_seconds`. Input validation still occurs once through Project; the receipt preserves the testbed’s current schema/key timing facts without exposing `validate()`.

## Fingerprint and authority identity contract

Implement `vqapr._internal.extensions.identity` and delete the former `vqapr.extension.component`, `vqapr.extension.fingerprint`, `vqapr.extension.loading`, and `vqapr.extension.registration` routes.

For source-backed DataModel, StrategyModel, and Constraint classes, source is stable only when `inspect.getsourcefile(type)` resolves to a regular readable `.py` file, `type.__qualname__` contains neither `<locals>` nor `<lambda>`, and module bytes can be read. Reject REPL, zip-only/no-file, generated, missing, unreadable, or unstable sources before any callback. This rule applies equally to built-ins and local extensions.

Fingerprint schema `vqapr.extension.fingerprint/v1` is exactly:

```
sha256(
  field(b"vqapr.extension.fingerprint/v1") ||
  field(kind_ascii) ||
  field(package_version_utf8) ||
  field(module_bytes) ||
  field(qualname_utf8) ||
  field(canonical_config_utf8)
)
```

`field(x)` is unsigned eight-byte big-endian byte length followed by `x`. `kind_ascii` is exactly one of `data_model`, `strategy_model`, `constraint`; `package_version_utf8` is installed `vqapr` distribution version. `module_bytes` are the full unmodified source-file bytes, not source path, mtime, or import name. `canonical_config_utf8` is UTF-8 canonical JSON generated by `vqapr.config/v1`: mappings have string keys sorted by UTF-8 byte order; list and tuple are distinct tagged arrays; allowed scalars are `None`, `bool`, `int`, finite `Decimal` encoded as canonical coefficient/exponent tuple, `str`, date, time, timezone-aware datetime, and nested allowed collections; float, path, callable, set, bytes, non-finite, and arbitrary object values are refused. Type tags prevent `1`, `True`, `"1"`, and `Decimal("1")` from colliding.

The opaque authority ID is `extension/v1/<kind>/<full-lowercase-fingerprint>`. It never includes caller name, path, source ID, workspace state, or fingerprint prefix. Dataset/execution authority IDs are likewise versioned hashes of their canonical declaration plus framework-computed source digest; their human `dataset_id`/`input_id` remain catalog binding keys, not authority IDs.

At registration and again immediately before each materialization evaluation/strategy callback, `_internal.extensions.load_fresh()` rereads module bytes and recomputes the same v1 fingerprint. A mismatch is a typed zero-callback drift error. This protects changed local source after preparation; no caller can slice/create/rebind an identity.

## Internal relocation and retained-engine reconciliation

Retain the engine but physically relocate it before cutover:

| Former module/path | New private location | Decision |
|---|---|---|
| `vqapr/workspace.py` | `vqapr/_internal/catalog.py`, `catalog_store.py` | Replace individual mutation API with detached `Catalog`, `CatalogView`, root codec, lock/CAS. |
| `vqapr/flow/*` | `vqapr/_internal/flow/*` | Retain preflight/simulation/materialization/run-state mechanics through private adapters. |
| `vqapr/data/*` | `vqapr/_internal/data/*` | Retain PIT scan/store/window and translate alias inputs to private requirements. |
| `vqapr/extension/*` | `vqapr/_internal/extensions/{identity,load,register}.py` | Retain renamed private loader/ref engine; private `RegisteredExtension` replaces former public `ComponentRef`/`ComponentKind`. |
| `vqapr/account/*`, `vqapr/evidence/*`, `vqapr/orders/*`, `vqapr/valuation/*`, legacy `vqapr/constraints/*` | matching `vqapr/_internal/*` subtrees | Retain implementation-only account/state/evidence/execution mechanics. |
| `vqapr/portfolio/*`, `vqapr/analysis/*`, `vqapr/testing/*`, `vqapr/transforms/*` | private implementation modules plus new public facade files | Convert current public directories to controlled public module files; `vqapr.methodologies/fama_french.py` is the sole intended public qualified methodology module. |

At T4, delete—not forward—the old files and packages: `public.py`, `workspace.py`, `flow`, `data`, `extension`, `account`, `evidence`, `orders`, `valuation`, `constraints`, legacy portfolio/analysis/testing submodules, and `transforms`. New public facades must never import a former path. Clean-process tests assert import failure for former lifecycle routes including `vqapr.workspace`, `vqapr.flow.preflight`, `vqapr.flow.simulation`, `vqapr.data.store`, `vqapr.data.scan`, `vqapr.extension.loading`, `vqapr.extension.registration`, `vqapr.account.account`, `vqapr.evidence.recorder`, and `vqapr.public`.

This resolves the apparent deletion conflict: former public ref/kind/fingerprint/loader routes are deleted; the needed mechanism remains only as renamed, unsupported `_internal` implementation details with no compatibility import path.

## Candidate-catalog preparation transaction

### Catalog model and non-mutating open

`Project.open(root)` resolves and stores `root` only. If `.vqapr/catalog.json` does not exist, it returns a Project bound to immutable `Catalog.empty(generation=0, root_digest=EMPTY_V1)` in memory; it creates neither directory, lock, catalog, nor artifacts. It is therefore safe to use before a failed first registration.

`Catalog` is a detached immutable value containing schema version, `generation: int`, declaration/extension bindings, registered dataset/execution metadata, publication registrations, and referenced content object digests. `CatalogView` is the only interface passed into private validation, scan, loader, and preflight code. Existing `Workspace` lookup calls are replaced by this view before the old module is deleted.

### Preparation protocol

For `Project.register`, `Project.materialize`, and `Project.run`:

1. Read current catalog root and capture `(generation, root_digest)` without mutation.
2. Build an in-memory candidate catalog by applying every required declaration/extension binding. Reject duplicate/conflicting semantic bindings; unchanged canonical declaration is idempotent.
3. Validate datasets/execution tables, compute source digests, source-backed class identity, conformance, alias/input/output/diagnostic schemas, schedules/exchange/account/constraints, and run preflight against **the candidate CatalogView**, not committed state.
4. Assemble private frozen execution/materialization authority using only candidate bindings. No model callback, account, run-state root, evidence, output object, or visible catalog changes exist yet.
5. Acquire catalog writer lock; reread root; compare both expected generation and root digest. If either differs, release lock and raise typed `CatalogConflict(expected_generation, observed_generation)` with `mutation=False`. Do not automatically rebase/preflight because validation facts may have changed.
6. Write one canonical temporary catalog-root file, flush/fsync it, atomically replace catalog root while holding lock, and release. The root generation increments exactly once.
7. Only after step 6 may materialization/run callbacks start. A post-preparation callback failure does not claim preparation was unmutated; its registration was a valid successful preparation commit.

No current `Workspace.register_*` call survives. The candidate catalog supplies all declaration lookups used by private preflight, preventing between-validation and commit races.

## Callback state and diagnostics transaction

`Project` invokes a fresh constructed model instance for every DataModel evaluation and StrategyModel occurrence. It does not reuse instances, attach memory/recorder, or retain model object attributes between calls. Construction uses registered canonical config; re-fingerprint/drift verification immediately precedes construction. The only permitted cross-callback author state is `StrategyCall.previous_state` and `StrategyResult.next_state`, normalized by the existing strict JSON state codec before staging.

For every strategy occurrence, private Flow constructs one `PreparedCallbackRoot` containing:

- decision normalized as Hold or complete Rebalance;
- normalized next-state bytes and state reference;
- diagnostics against the predeclared `DiagnosticTable` set and rows;
- actual alias reads/access records and derived source references;
- framework-generated correlation/authority IDs and callback evidence;
- a pending execution/valuation object and current immutable account reference.

All validation/serialization/schema work finishes before `RunStateRepository.publish(prepared)`. That one pointer swap makes decision, state, diagnostics manifests/rows, provenance/evidence, and pending execution visible together. Rejection or callback exception publishes none. The current immutable root remains the basis, but private recorder/table APIs are removed from author reach.

## Crash-safe content-addressed publication

1. `CompletedRun.publish(Publication)` validates the entire declaration, selected allocation/record schemas, non-empty typed output, framework envelope projection, source lineage, and uniqueness before object visibility.
2. It serializes every parquet and lineage payload deterministically, computes SHA-256 content digests, writes to `.vqapr/objects/sha256/<digest>` temporary files, flushes/fsyncs data, verifies digest, then atomically installs immutable object paths. Object paths are not catalog-visible merely because they exist.
3. It reads a catalog root snapshot and builds one candidate root adding all selected logical datasets, source metadata, lineage object digests, and output bindings. Every requested output ID must be absent in that snapshot; allocation and all records are one candidate set.
4. Under the writer lock it CAS-checks root generation/digest, fsyncs and atomically swaps the one catalog root. On success all selected outputs become visible together through ordinary supported reads. A CAS mismatch raises `PublicationConflict` with no new catalog visibility.
5. A crash before the root swap leaves only unreferenced immutable objects; reopening reads the old complete root. A crash after the root swap leaves a root whose every referenced digest has already been verified/written, so all outputs are visible.
6. `Project.open()` never mutates/collects. The next successful writer performs private orphan sweep after committing its own root: it may remove only digest-valid, unreferenced objects older than a fixed 24-hour grace period; sweep failures are recorded internally but cannot invalidate a committed root. Orphans never block retry because logical output identity lives solely in the catalog.

Directory fsync is performed where the platform supplies it; the object write/verify occurs before root replacement on all supported platforms. Tests assert process-crash logical consistency rather than a filesystem-specific promise about power-loss hardware semantics.

## T0 canonical baseline and same-shape performance protocol

Create testbed baseline tooling before any behavior change:

- `vqapr-testbed-2/baselines/agent-first-v1/manifest.json`
- `vqapr-testbed-2/baselines/agent-first-v1/declarations.json`
- `vqapr-testbed-2/baselines/agent-first-v1/materialization.rows.jsonl`
- `vqapr-testbed-2/baselines/agent-first-v1/simulation.trace.jsonl`
- `vqapr-testbed-2/baselines/agent-first-v1/publication.rows.jsonl`
- `vqapr-testbed-2/baselines/agent-first-v1/hashes.json`
- **New** `vqapr-testbed-2/capture_agent_first_baseline.py`
- **New** `vqapr-testbed-2/compare_agent_first_baseline.py`
- **New** `vqapr-testbed-2/benchmark_agent_first_shape.py`

`manifest.json` schema is `vqapr-testbed-agent-first-baseline/v1` and records: capture UTC timestamp; qlibx Git SHA; testbed Git SHA; `importlib.metadata.version("vqapr")`; qlibx/testbed `pyproject.toml` and `uv.lock` SHA-256; Python version; exact command argv; source path logical label plus byte/tree SHA-256, parquet byte count, and source schema; prepared artifact digest; universe ordered hash; evaluation/session ordered hashes; factor list; benchmark shape; and canonicalizer schema version. Paths are diagnostic-relative labels only and do not enter row/trace identity.

Canonicalizer `vqapr-testbed-canonical/v1` writes UTF-8 JSON Lines with lexicographically ordered keys; mappings are recursively key-sorted; `Decimal` is a tagged normalized coefficient/exponent tuple; datetime is RFC3339 UTC with six fractional digits; date/time retain ISO syntax; tuple/list distinction is tagged; `None`/bool/int/string are tagged; and unknown/non-finite values fail capture. Materialization rows sort by `(dataset_id, available_at, instrument_id)`. Publication rows sort by `(dataset_id, available_at, instrument_id, table_id, sequence)`. Simulation trace preserves exact dispatched lifecycle order and captures callback result, declared aliases/read digests, targets/cash/budget, execution target/fills/costs, account snapshots/positions, marks/`observed_at`, NAV, diagnostic rows, and correlation/authority facts with framework-only IDs normalized into separately compared authority fields.

`hashes.json` contains SHA-256 for each JSONL, each dataset subsequence, each factor/full-row subsequence, ordered trace subsequence, and canonical manifest. Comparator first verifies schema/source/shape digests, then performs a streaming first-difference comparison with JSON pointer/location and expected/actual canonical values; aggregate correlation never substitutes for row/trace equality. `compare_factors.py` remains the external Kimchi check and must additionally retain SMB `.971509`, HML `.972553`, RMW `.941883`, CMA `.917683`, MOM `.984659`; HML remains exactly 2,096 callbacks, 97 formations, and 110,919 rows; NAV must use account-row `observed_at`.

Commands at T0 and after every T3 migration slice:

```powershell
cd vqapr-testbed-2
uv run --no-sync python capture_agent_first_baseline.py --out baselines/agent-first-v1
uv run --no-sync python compare_agent_first_baseline.py --expected baselines/agent-first-v1 --actual outputs/agent-first-candidate
uv run --no-sync python compare_factors.py
```

The capture harness is allowed only before public cutover to observe current authoritative outputs; after cutover it uses the supported Project result/lineage views and the private test-only trace hook supplied by qlibx integration fixtures, never a testbed private import.

Same-shape performance protocol: use manifest-pinned source digests, instrument/session/evaluation counts, factor list, package wheel, and a fresh workspace per repetition; run no cProfile/`--hot-frames`; execute five separate processes after one discarded warm-up; record wall-clock monotonic phase timing and rows/evaluations in canonical JSON; do not compare runs with changed shape, source digest, wheel, or concurrent workload. Compare medians: each equivalent materialize/run/publish phase and total pipeline must be `<= 1.10 ×` baseline median; p95 must be `<= 1.25 ×` baseline p95. A failed threshold blocks T4 unless a measured profiling root cause is approved as an explicit scope decision; a speedup never excuses row/trace mismatch.

```powershell
cd vqapr-testbed-2
uv run --no-sync python benchmark_agent_first_shape.py --manifest baselines/agent-first-v1/manifest.json --repetitions 5 --discard-warmup 1 --out outputs/agent-first-performance.json
```

## Cross-repository version, SHA, lock, and wheel handoff

The cutover package version is `0.2.0a1` (current qlibx is `0.1.0a16`; this is a breaking API line). T1–T3 coexistence is development-only and must never be published.

1. T0 manifest pins baseline qlibx SHA/testbed SHA and both lock hashes.
2. After T4 deletion gates pass, commit the qlibx cutover source/doc/test/implementation record as SHA `Q`; set version `0.2.0a1`; build `vqapr-0.2.0a1-py3-none-any.whl`; record its SHA-256 in `../qlibx/docs/implementations/<next>-agent-first-api.md` and testbed `baselines/agent-first-v1/handoff.json`.
3. Migrate testbed as commit SHA `T` against `Q`, replace `vqapr>=0.1.0a16` with `vqapr==0.2.0a1`, and remove editable `[tool.uv.sources].vqapr = { path = "../../qlibx", editable = true }` for the release verification copy. Resolve/update `uv.lock` from the built local wheel, record its lock hash and `(Q,T,wheel SHA)` tuple in `handoff.json` and `HANDOFF.md`.
4. Run the complete testbed parity/performance suite once against editable `Q` for developer feedback and once in a clean temporary non-editable testbed copy installed from that exact wheel. The second result is release evidence. Verify `importlib.metadata.version("vqapr") == "0.2.0a1"` and package source is not the sibling worktree.
5. Publish/tag only after both editable and wheel results identify the same Q/T pair and all T5 gates pass. A source/lock/wheel mismatch blocks release; no implicit `uv sync` replacement is accepted.

## In scope / out of scope

### In scope

- Exact public declaration algebra/capability homes, Project preparation/catalog transaction, source identity, fresh model calls, diagnostic schema, atomic content-addressed publication, physical module relocation/removal.
- CLI/scaffold/skill/showcase/docs migration required to dogfood the API.
- Full testbed migration: `register.py`, `build_characteristics.py`, `build_factors.py`, models, `compare_factors.py`, `rebuild.ps1`, declarations, `OPERATIONS.md`, `HANDOFF.md`, `PENDING-UPSTREAM.md`, `FRICTION.md`, `FINDINGS.md`, `PROFILING.md`, dependency/lock, and all imports found by a whole-tree scan.
- Baseline capture/comparison/performance harness and qlibx/testbed wheel handoff.

### Out of scope

Experiment manager, economic defaults, methodology generation, public raw storage/evidence, compatibility/migration aliases, one-line wrappers, unrelated CLI redesign, source data preparation changes, and changes to Kimchi methodology.

## File-level changes

### `../qlibx`

| File/path | Exact work |
|---|---|
| `src/vqapr/__init__.py` | Exact 11-name export tuple and `open`; no legacy imports. |
| **New** `src/vqapr/project.py` | Public declarations/receipts/conflicts and Project orchestration; non-mutating open. |
| **New** `src/vqapr/authoring.py`, `materialization.py`, `simulation.py`, `portfolio.py`, `venues.py`, `analysis.py`, `testing.py`, `methodologies/__init__.py`, `methodologies/fama_french.py` | Implement exact matrix above. |
| **New** `src/vqapr/_internal/catalog.py`, `catalog_store.py` | Detached Catalog/View, canonical root codec, generation/digest CAS, lock, object reference index, post-commit orphan sweep. |
| **New** `src/vqapr/_internal/extensions/{identity,load,register}.py` | v1 fingerprint/authority ID, stable-source/drift checks, private `RegisteredExtension`, common built-in/local conformance registration. |
| **New/moved** `src/vqapr/_internal/{data,flow,account,evidence,orders,valuation,constraints,portfolio,analysis,testing,methodologies}/...` | Move retained logic and rewrite imports to private paths. Preserve current Flow/state/PIT behavior through adapters. |
| moved private `data/windows.py` / `flow/views.py` / model adapter | Alias-to-requirement bridge, typed Observation and access capture. |
| moved private `flow/preflight.py`, `flow/run.py` | Candidate CatalogView preflight, complete Simulation translation. |
| moved private `flow/simulation.py`, `flow/run_state.py`, `flow/model_state.py`, `evidence/recorder.py` | Fresh instance per call; PreparedCallbackRoot; state/diagnostic/evidence/pending single root swap. |
| moved private `flow/materialize.py` | Model-owned Output validation; object staging; combined Publication candidate/root swap. |
| **Delete** `src/vqapr/public.py` and former public-root directories/files listed in relocation table | No redirects, aliases, old subclasses, or former FQNs. |
| `src/vqapr/cli/{main,register,run,new,list_,skill,envelope}.py`, `extension/scaffold.py` replacement location, `agent/sample/*` replacement location | Rewrite around Project declarations/facades; remove raw identity/provenance/memory/recorder instructions. |
| `docs/`, `README.md`, `showcases/`, skills | Replace old paths/workflow; delete obsolete usage. |
| `tests/boundaries/*`, `tests/flow/*`, `tests/extension/*`, `tests/acceptance/*`, `tests/cli/*` | Add exact API/deletion, candidate-CAS, hard-kill/concurrency, fingerprint, fresh-state/diagnostics, content-addressed publication, wheel/CLI/scaffold acceptance coverage. |

### `vqapr-testbed-2`

| File | Exact work |
|---|---|
| `register.py` | Parse current dataset YAML into `project.DatasetDeclaration`, open Project once, call `Project.register` for every source. Record `RegistrationReceipt.timing.schema_seconds/key_seconds` and `created`; delete direct `validate`, `DatasetRegistration`, `SourceSpec`, and `register_dataset` imports. |
| `build_characteristics.py` | Open Project once; three `Project.materialize` calls; delete manual component registration/fingerprint/spec/output fields. |
| `models/characteristics.py` | Alias inputs/Output/DerivedRow/typed Observation; preserve all lookbacks, source fields, precise Decimal behavior, statement fallback, sorting, and deliberate missingness. |
| `build_factors.py` | Delete dynamic venue file generation, manual registrations/agendas/config/preflight/fingerprint suffixes, dynamic import, free publishers. Declare complete Simulation and one Project.run/one CompletedRun.publish per factor. |
| `models/factors.py` | Alias reads + explicit DiagnosticTable; return Hold/Rebalance/next_state/diagnostics; remove consumer/strategy IDs, UUID, source refs, account version, model mutable memory/recorder. Preserve factor economics/outputs. |
| `measure_session_effect.py` | Delete at T3: it intentionally benchmarks removed private API and its premise is obsolete after the existing ScanSession materialization fix. Preserve historical result in `PROFILING.md`; replace future measurement with `benchmark_agent_first_shape.py`. |
| `compare_factors.py`, `rebuild.ps1`, declarations, docs listed above | Point to new commands/output selection and Q/T/wheel handoff. |
| entire testbed | Add `tests/test_agent_first_public_boundary.py` (or established test location) and a whole-tree scan excluding `.venv`, `.ruff_cache`, `outputs`, `__pycache__` that rejects `vqapr.public`, former private prefixes, `ComponentRef/Kind`, `component_ref`, register/preflight/run/publish old symbols, dynamic import, source-ref/UUID/account-version author fields, mutable recorder/memory usage. |

## Sequencing and dependencies

### Working transition states and rollback boundaries

- **T0 — frozen baseline:** current code unmodified; canonical manifest, rows/traces/hashes, correlation/HML facts, and five-run performance baseline captured. Rollback is simply no implementation work.
- **T1 — public algebra/private target:** types, public facades, `_internal` destination imports, identity codec, and test fixtures exist behind the current unshipped surface. Existing suite remains green. Rollback deletes new code only.
- **T2 — transactional spine:** candidate CatalogView/CAS, fresh callbacks, callback root, and content-object publication work in a fixture. Legacy path still exists solely for baseline comparison; no wheel is built/published. Rollback is source revert to T1.
- **T3 — dogfood/migration:** CLI/scaffold/sample/showcase/testbed registration and builds run solely through new supported API; baseline comparator passes after each slice. `measure_session_effect.py` retired. This is final rollback boundary before removal.
- **T4 — hard cutover:** physically move retained authorities to `_internal`, delete every old public/qualified route, update all qlibx/testbed references, and produce version `0.2.0a1` candidate. Rollback is full T4 revert only.
- **T5 — sealed handoff:** Q wheel + T non-editable lock pair passes full quality/parity/performance/recovery gates. Stop for approval before tag/push/publish.

### Ordered implementation steps

1. **Capture T0 exactly.** Add baseline canonicalizer/capture/comparator/benchmark harness, record manifest and hashes from baseline sources, trace hooks, rows, correlations, counts, and five-repetition same-shape measurements. Do not accept aggregate correlation as a replacement for trace/row hash proof.
2. **Define and test the public algebra.** Implement the exact module/export matrix and immutable constructors, fresh registration example, receipt fields, explicit absence rules, capability import tests, and canonical config codec before adapters.
3. **Move/add internal foundations.** Introduce `_internal` copies/destination modules, rewrite internal imports, add Catalog/CatalogView/root codec/lock/CAS, v1 private identity/loader/register engine. Keep old paths temporarily only inside the unshipped source tree while proving destination behavior.
4. **Implement candidate preparation.** Route Project.register/materialize/run through in-memory candidate catalog validation/conformance/preflight and generation+digest CAS. Make Project.open non-mutating. Add conflict, validation failure, first-open, and concurrent writer tests.
5. **Implement semantic authoring/runtime adapters.** Alias observations, Output validation, fresh class instantiation, diagnostic schemas, StrategyResult decision/state/diagnostics/access/pending callback root. Preserve internal state/evidence behavior and prove all-or-none callback effects.
6. **Implement object-store publication.** Replace multi-step visible output registration with verified immutable objects plus one catalog-root publication candidate/CAS; implement non-mutating-open/orphan sweep semantics. Add caught failure, concurrent publisher, and hard-kill subprocess tests.
7. **Dogfood all package surfaces.** Migrate CLI, scaffold, skills, samples, docs, and showcases. Fresh-project and float-parquet generated-model e2e must use supported imports only.
8. **Migrate complete testbed.** `register.py` first, characteristics second, factor model third, factors runner/publication fourth, then docs/rebuild/whole-tree scan and measure-script retirement. After each slice run T0 comparator; only then proceed.
9. **Cut over physically.** Delete old public/fq modules and legacy tests/docs. Clean-process import absence, search/AST scans, and full testbed scan must pass. Build Q `0.2.0a1` wheel, migrate T to noneditable dependency/lock, and archive handoff receipt.
10. **Run T5 gates and document.** Full quality, build, isolated wheel, showcases, qlibx/testbed exact parity/performance/crash/concurrency gates. Create the next-numbered qlibx implementation record; stop pending approval before commit/tag/push/release.

## Acceptance criteria

### API and declaration completeness

- Exact matrix exports and exact top-level `__all__` pass clean-process tests.
- ProjectDeclaration accepts only the three stated declaration variants; each field/explicit `None`/`()`, validation ownership, and capability home is tested from a fresh project example.
- No economic default/inference/fluent builder/god function exists.
- `Project.open()` creates no workspace/object/lock; failed first register leaves none.

### Identity, candidate preparation, and internal boundary

- v1 length-delimited fingerprint/typed-config fixture vectors are stable; path/name do not affect digest; source/config/version changes do; unstable source and pre-callback source drift fail.
- Authority IDs are framework-derived opaque full-digest IDs; no caller suffix/fingerprint slicing is possible.
- Candidate catalog preflight sees all staged declarations and no unstaged state; a CAS conflict exposes no candidate catalog/callback/output mutation.
- No former FQN imports; only new intended capability homes are public.
- Private loader/ref engine exists only under `_internal`; no public ComponentRef/Kind/fingerprint/loader route survives.

### Callback/publication atomicity

- New instance per callback/evaluation; no instance state carries across calls.
- Diagnostics must match declared schema; a rejected strategy result makes no decision/state/diagnostic/evidence/pending root mutation.
- Content objects are invisible until one root swap; allocation and all records become visible together or none do.
- Exception, writer conflict, process hard-kill before swap, and hard-kill after swap meet catalog visibility/reopen/orphan invariants.

### Testbed and release pair

- Whole-tree testbed scan is clean, including `register.py`; `measure_session_effect.py` is absent and its historical note is retained only in docs.
- Three materializations, five runs, one atomic publication each, root once per script, all economics explicit.
- Exact canonical materialization/publication rows and ordered simulation traces match T0 hashes; external factor correlations/counts/NAV observed-at match.
- Q/T/wheel SHA, both lock hashes, and noneditable wheel run are recorded and agree; no T1–T3 artifact is published.
- Same-shape median/p95 thresholds meet stated limits.

## Verification plan

### Unit and boundary

- Constructor/export/import failure matrix; canonical-config and fingerprint test vectors; identity/path/name/drift tests.
- Dataset/execution schema/key validation receipt timings; Catalog candidate/CAS/idempotency/conflict/open-no-mutate tests.
- Alias/PIT/lookback/typed Observation; output and diagnostic schema/reserved fields; finite Decimal/cash/budget/target invariant tests.
- Fresh-instance sentinel test where an undeclared instance mutation would change a later callback if reused; prove it cannot.
- Callback root failure injection; catalog object digest/lineage/candidate publication failure injection.

### Integration, crash, and concurrency

- Supported-only temp project register→materialize→run→publish→analyze.
- Preflight failure after multiple staged declarations, no callback and byte-identical root/object reference set.
- Two-process registration and publication writers contend on same generation; exactly one commits, loser returns typed conflict, catalog remains readable.
- Subprocess `os._exit` injection after object fsync/before root swap and immediately after root swap; reopen proves old complete root or new complete root respectively, never partial; next writer’s orphan sweep leaves referenced objects intact.

### E2E, observability, and commands after approval

From `../qlibx`:

```powershell
uv run --no-sync pytest -q tests/boundaries tests/extension tests/flow tests/acceptance tests/cli
uv run --no-sync ruff check src tests
uv build
```

From testbed, run T0/T3 comparator and performance commands shown above, then:

```powershell
uv run --no-sync python register.py
uv run --no-sync python build_characteristics.py
uv run --no-sync python build_factors.py
uv run --no-sync python compare_factors.py
```

For sealed wheel verification, execute the same commands in the noneditable temporary testbed copy after lock resolution from Q’s built wheel. Record receipts/phase timings/error envelopes/lineage object digests; do not claim real-data gates where manifest-pinned inputs are unavailable.

## Escalation / risk gate

Do not begin T4 deletion/build Q unless all hold: public algebra is reviewed; candidate-CAS and callback/publication transaction tests pass; hard-kill/concurrency tests pass; CLI/scaffold/sample/showcase/fresh-project tests use new imports; whole testbed—including `register.py`—passes T0 trace/row comparator; and package/testbed source/docs scans contain no former paths.

Do not publish/tag Q unless noneditable wheel testbed T passes with matching Q/T/wheel/lock receipt, external factor correlations/counts, and performance thresholds. A failure before T4 returns to last green transition; a failure after T4 is a whole cutover revert, never an alias or fallback.

## RALPLAN-DR summary

- **Decision:** select Project facade with private moved authority, candidate catalog CAS, fresh callbacks, and content-addressed publication/root swap.
- **Rejected:** renamed old primitives, engine rewrite, sequential publication cleanup.
- **Rationale:** closes direct import/lifecycle escapes, makes identity/preparation/publication/callback semantics testable, retains proven engine behavior, and protects factor parity.
- **Required proof:** exact public algebra, source identity vectors, catalog generation conflicts, hard-kill/recovery, callback root atomicity, whole testbed scan, canonical T0 trace/row equality, performance thresholds, and Q/T/noneditable wheel handoff.
- **Approval state:** pending approval after T5 evidence; no product mutation performed by this planning stage.

## Risks and mitigations

### Pre-mortem 1 — a facade exists but legacy authority remains callable

- **Scenario:** `__all__` is clean but `vqapr.workspace`, `vqapr.flow.preflight`, or `vqapr.extension.loading` remains importable.
- **Early warning:** subprocess import succeeds; a scaffold/doc/test can register/run/publish without Project.
- **Mitigation:** physical `_internal` move, delete former FQNs, clean-process absence tests, and whole source/docs/template scan.
- **Rollback:** stop at T3; never ship compatibility redirects.

### Pre-mortem 2 — catalog/publication leaves partial state under race or hard kill

- **Scenario:** preflight validates stale catalog, a concurrent writer overwrites it, or one output becomes visible without its companion.
- **Early warning:** root generation differs from prepared snapshot; object exists without catalog reference; hard-kill reopen finds partial registration.
- **Mitigation:** candidate CatalogView, lock + generation/digest CAS, verified immutable objects, single root swap, grace-period orphan sweep, two-process and kill-point tests.
- **Rollback:** before root swap discard candidate; after T4 revert the complete cutover.

### Pre-mortem 3 — model hidden state or diagnostics bypass returned semantic state

- **Scenario:** a reused instance carries an attribute between calls or emits dynamically shaped records that cannot replay.
- **Early warning:** changing callback ordering changes output without `previous_state`; diagnostics fail schema only during publication.
- **Mitigation:** fresh instance per call, preparation-time DiagnosticTable validation, one PreparedCallbackRoot and pointer swap.
- **Rollback:** retain current private run-state root while correcting adapter before T4.

### Pre-mortem 4 — parity is claimed from correlation while exact economics drift

- **Scenario:** aliases/lookbacks/cadence/output stamps change but correlations stay close; performance appears slower due to changed workload/host load.
- **Early warning:** canonical source/shape hash mismatch, first trace/row difference, HML count change, or different observed-at.
- **Mitigation:** T0 manifest/JSONL hashes/comparator, exact first-difference report, five-process same-shape median/p95 protocol, external correlation as secondary gate.
- **Rollback:** return to last T3 parity checkpoint; fix translation, never add inference.

### Pre-mortem 5 — editable dogfood passes but released package fails

- **Scenario:** testbed points at sibling Q worktree, while built wheel/lock contains a different version or source.
- **Early warning:** Q/T/wheel/lock hashes absent or metadata says a path/editable source.
- **Mitigation:** required `0.2.0a1` Q/T/handoff receipt, remove editable source in release copy, verify noneditable wheel separately.
- **Rollback:** block tag/publish and rebuild/relock from recorded Q.


## Final Algebra-Closure Delta

# vqapr Agent-First Python API — Consensus Revision 3 (Narrow Algebra-Closure Delta)

## Summary

This is a delta to `stage-02-revision.md` SHA-256 `397137c38099e717e89fd5d6bc9d060b0714446a1f435683066f3da0f77dcadd`. It preserves every resolved transaction, content-addressed publication, private relocation, identity, fresh-callback, parity/performance, testbed, and Q/T/wheel handoff decision without modification.

It resolves only carryover `ARCH-VQAPR-001` / `CRIT-VQAPR-P1-001`: all public annotation-level capabilities are now mechanically closed, defined, and single-homed. In particular, `Constraint`, `EconomicAccountView`, `DeclaredAccountHistory`, `ConstraintBounds`, and `Diagnostic` are exact public contracts rather than implicit internal types.

Locked intent IDs remain preserved literally and substantively:

- `artifact:api-spec`
- `surface:project-workflow`
- `surface:model-authoring`
- `integration:runtime-internals`
- `constraint:agent-first`
- `constraint:economic-explicitness`
- `constraint:hard-removal`

## Intent Diff

| Revision 2 annotation hole | Revision 3 closed contract |
|---|---|
| `ExtensionDeclaration` and `ConstraintDeclaration` name undefined `Constraint`. | `vqapr.authoring.Constraint` is the single public extension base, with inputs/project/validate/monitor methods and common Project/testing conformance. |
| `StrategyCall` exposes untyped account/history/bounds capabilities. | `vqapr.authoring.EconomicAccountView`, `AccountHistoryInput`, `DeclaredAccountHistory`, and `ConstraintBounds` are bounded immutable read-only values/methods with no account version, storage, raw mark, or mutation escape. |
| `RegistrationReceipt.diagnostics` names undefined `Diagnostic`. | `vqapr.project.Diagnostic` is a bounded immutable receipt fact with exact field/error semantics. |
| The matrix is descriptive only. | An annotation-closure test extracts every project-owned annotation reference from all public modules, resolves it, verifies exactly one home/export, and fails on unresolved, duplicate, `_internal`, former-route, or unsupported-module references. |

## Decision Drivers

1. These five types are public because users must subclass `Constraint`, receive strategy economic views/bounds/history, or inspect registration diagnostics; exposing `_internal` types would violate the public boundary.
2. Economic access must be useful but bounded: a strategy can read committed cash/positions/latest valuation and explicitly declared history/bounds, but cannot observe account versions, mutable account state, raw mark/evidence/store objects, or undeclared/open-ended history.
3. Constraint behavior must remain deterministic, preflight-conformant, source/PIT bounded, and framework-attested. Constraint identity, provenance, account version, and envelope fields remain framework-owned.
4. `Diagnostic` must be safe for agent handling: immutable, bounded, serializable, and devoid of source paths, traceback, raw exception objects, storage object handles, or unbounded payloads.

## Public export-matrix replacement delta

Replace only the following rows in Revision 2’s exact module/export matrix; every other row is unchanged.

| Public home | Exact exported names | Single-home rule |
|---|---|---|
| `vqapr.project` | `Project`, `open`, `ProjectDeclaration`, `DatasetDeclaration`, `ExecutionInputDeclaration`, `ExtensionDeclaration`, `Diagnostic`, `RegistrationReceipt`, `RegistrationTiming`, `CatalogConflict`, `PublicationConflict` | `Diagnostic` is receipt/error-detail capability only. It is not exported by authoring, simulation, testing, or top-level `vqapr`. |
| `vqapr.authoring` | `RowsLookback`, `CalendarLookback`, `DatasetInput`, `Observation`, `Output`, `DerivedRow`, `DataCall`, `DataModel`, `DiagnosticTable`, `AccountHistoryInput`, `EconomicAccountView`, `DeclaredAccountHistory`, `ConstraintBounds`, `ConstraintCall`, `ConstraintFinding`, `Constraint`, `StrategyCall`, `StrategyModel`, `Hold`, `Rebalance`, `StrategyResult` | This is the sole home for every author-implemented, author-received, or author-inspected callback capability. No account/history/bounds/constraint types are exported by simulation or `_internal`. |
| `vqapr.simulation` | `ExecutionInput`, `FillConvention`, `FillSelector`, `Cadence`, `Schedule`, `Execution`, `InitialAccount`, `AccountSnapshot`, `AccountMode`, `ConstraintDeclaration`, `Simulation`, `Publication`, `AllocationOutput`, `RecordOutput`, `CompletedRun`, `PublishedRun` | `ConstraintDeclaration.constraint` is annotated `type[authoring.Constraint]`; it does not define/re-export Constraint. |

All other public type references use either (a) the one project-owned home above or Revision 2’s unchanged declared home, qualified in source to avoid accidental duplicate aliases, or (b) standard-library types imported directly from their standard modules (`Path`, `date`, `datetime`, `time`, `Decimal`, `Mapping`, `Literal`, `TypeAlias`). Standard-library types are not package exports and are excluded from package-home uniqueness checks.

## Exact definitions and failure semantics

Every data value in this section is `@dataclass(frozen=True, slots=True, kw_only=True)` unless shown as an abstract class. Incoming mappings are copied into read-only sorted mappings; incoming sequences are detached tuples. All `Decimal` values must be finite. All timestamps must be timezone-aware. Public constructors and framework views never expose mutable internal mappings.

### `vqapr.project.Diagnostic`

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class Diagnostic:
    code: str
    severity: Literal["error", "warning"]
    requirement: str
    observed: str
    examples: tuple[str, ...]
    example_total: int
```

Validation is exact: `code` and `requirement` are non-empty ASCII-safe identifiers/text; `severity` is exactly `"error"` or `"warning"`; `observed` is at most 500 Unicode code points; each example is at most 500 code points; `examples` has at most 20 members; `example_total` is a non-negative integer and is at least `len(examples)`. Values failing these limits are framework bugs and raise `TypeError`/`ValueError` before a receipt is produced; they are never truncated silently.

`RegistrationReceipt.diagnostics: tuple[Diagnostic, ...]` is a detached ordered collection. Successful idempotent/created registration uses `diagnostics=()` unless the framework has a bounded non-fatal warning. A rejected preparation raises `VqaprError` with the same bounded `Diagnostic` shape in its serialized failure payload and `mutation=False`; it does not return a partial receipt. Diagnostic fields never include a physical path, source digest, traceback, exception object, internal class name, account version, or authority-envelope field.

### Bounded account/history/bounds capabilities in `vqapr.authoring`

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class EconomicAccountView:
    cash: Decimal
    positions: Mapping[str, Decimal]
    nav: Decimal | None
    nav_observed_at: datetime | None

    def quantity(self, instrument_id: str) -> Decimal: ...

@dataclass(frozen=True, slots=True, kw_only=True)
class AccountHistoryInput:
    fields: tuple[Literal["nav", "cash", "quantity", "price", "observed_at"], ...]
    lookback: RowsLookback

class DeclaredAccountHistory:
    @property
    def fields(self) -> tuple[str, ...]: ...
    @property
    def lookback(self) -> RowsLookback: ...
    def series(self, field: Literal["nav", "cash"]) -> tuple[Decimal, ...]: ...
    def panel(
        self,
        field: Literal["quantity", "price", "observed_at"],
    ) -> Mapping[str, tuple[Decimal | datetime, ...]]: ...

@dataclass(frozen=True, slots=True, kw_only=True)
class ConstraintBounds:
    lower_weights: Mapping[str, Decimal]
    upper_weights: Mapping[str, Decimal]

    def lower_weight(self, instrument_id: str) -> Decimal: ...
    def upper_weight(self, instrument_id: str) -> Decimal: ...
```

`EconomicAccountView` is constructed only by the framework for a callback. It contains the current committed cash and non-zero position quantities, sorted by instrument. `quantity()` returns the explicit current quantity or `Decimal(0)` for a valid absent instrument. It has no constructor argument/property/method for account version, account identity, storage, fills, mutable account, raw mark batch, provenance, or recorder.

`nav` and `nav_observed_at` are coupled: both are `None` before any committed valuation; otherwise `nav` is a finite `Decimal` and `nav_observed_at` is the timestamp of the valuation whose NAV is exposed. They are never synthesized from cash/positions by author code. `positions` and all panel mappings are immutable views; attempts to mutate them fail. `EconomicAccountView` is a snapshot and never advances after callback entry.

`StrategyModel.account_history()` is added to the public contract:

```python
class StrategyModel:
    def inputs(self) -> Mapping[str, DatasetInput]: ...
    def account_history(self) -> AccountHistoryInput | None: ...
    def diagnostics(self) -> tuple[DiagnosticTable, ...]: ...
    def decide(self, call: StrategyCall) -> StrategyResult: ...
```

Returning `None` explicitly declares that no historical account fields are read; returning `AccountHistoryInput` declares every field and bounded `RowsLookback` before preparation. `fields` is non-empty/unique, `lookback.rows > 0`, and no undeclared field is retained. `DeclaredAccountHistory` returns oldest-first, at-most-lookback data from committed valuations only. `series("nav"|"cash")` returns at most `lookback.rows` values. `panel("quantity"|"price"|"observed_at")` returns only observations for an instrument at marks where it was present; it never inserts zeros or forward-fills values. `panel` returns a detached sorted immutable mapping. Calling `series`/`panel` for a field not declared by `AccountHistoryInput`, with a field in the wrong scope, or with any non-permitted string raises `KeyError`; it never returns an empty result as an implicit fallback.

`ConstraintBounds` must cover exactly the `Simulation.instruments` tuple passed to the callback: keys are non-empty unique instrument IDs, every lower/upper value is finite, and `lower_weights[id] <= upper_weights[id]`. Accessor calls for an invalid/uncovered instrument raise `KeyError`. The bounds contain target-weight limits only; they expose no constraint identity, raw finding, source read, or internal optimization representation. Framework merges all registered constraint projections by maximum lower/minimum upper and rejects an empty intersection before Strategy invocation.

### Constraint authoring/conformance in `vqapr.authoring`

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class ConstraintCall:
    evaluation_time: datetime
    account: EconomicAccountView
    instruments: tuple[str, ...]
    def read(self, alias: str) -> tuple[Observation, ...]: ...

@dataclass(frozen=True, slots=True, kw_only=True)
class ConstraintFinding:
    passed: bool
    measured: Decimal
    bound: Decimal
    excess: Decimal
    details: Mapping[str, object]

class Constraint:
    def inputs(self) -> Mapping[str, DatasetInput]: ...
    def project(self, call: ConstraintCall) -> ConstraintBounds: ...
    def validate(
        self,
        decision: Rebalance,
        bounds: ConstraintBounds,
    ) -> ConstraintFinding: ...
    def monitor(
        self,
        call: ConstraintCall,
        bounds: ConstraintBounds,
    ) -> ConstraintFinding: ...
```

A Constraint is class-authored and config-constructed through the same `ExtensionDeclaration` / `ConstraintDeclaration` source-identity, stable-source, fingerprint, loading, and conformance path as DataModel and StrategyModel. It has no public `constraint_id`; the framework binds the opaque authority ID from its v1 fingerprint. It has no mutable memory, recorder, source references, account version, state reference, UUID, raw intent, store, or Flow access.

`inputs()` obeys the same non-empty unique alias and DatasetInput rules as models. `ConstraintCall.read(alias)` has the exact `DataCall.read` contract: declared alias only, typed observations only, specified fields/lookback/PIT only, actual-read provenance captured by framework. Its `account` has the exact immutable `EconomicAccountView` contract above. `ConstraintCall.instruments` is the complete ordered Simulation universe; it is detached and immutable.

`project()` computes only per-instrument `ConstraintBounds` for the current PIT cutoff and must cover that entire call universe. It cannot choose or mutate a portfolio. `validate()` examines a fully normalized `Rebalance` plus the merged bounds used by the framework and returns a semantic finding. `monitor()` examines the committed immutable account view plus the same projection bound at a monitoring cutoff and returns a semantic finding. Framework rejects an intended decision when any `validate()` result has `passed=False`; monitoring retains findings as framework evidence and does not retroactively alter account state.

`ConstraintFinding` validation: `passed` is bool; `measured`, `bound`, and `excess` are finite Decimal; `details` is a sorted immutable mapping limited to 32 non-empty semantic keys and 4 KiB of canonical `vqapr.config/v1` encoded data. Reserved framework envelope/authority keys are refused. Constraint ID, provenance/source references, account version, event time, sequence, and stage are derived/stamped by framework outside `details`.

Conformance occurs during Project candidate preparation and `vqapr.testing.conformance` for every built-in/local Constraint. It verifies stable source/fingerprint/config construction; base class; exact positional signatures; `inputs()` alias/schema validity; `project`, `validate`, and `monitor` method presence; and that no annotation resolves to `_internal`. Runtime return types/schema/universe coverage are validated before any callback root/account mutation. Bad input/schema/signature/source/construction fails with a bounded `VqaprError`, `mutation=False`, and no candidate catalog/root change. A runtime constraint exception or invalid bounds/finding is a typed pre-commit simulation failure: the relevant strategy decision/callback root is not published, no pending execution is staged, and account state is unchanged.

### Updated `StrategyCall` exact contract

```python
class StrategyCall:
    evaluation_time: datetime
    account: EconomicAccountView
    previous_state: object
    account_history: DeclaredAccountHistory
    constraint_bounds: ConstraintBounds
    def read(self, alias: str) -> tuple[Observation, ...]: ...
```

`previous_state` is the strict canonical state decoded from the prior accepted callback root, detached at call entry; it may be `None` only when `Simulation.initial_strategy_state=None` or a prior accepted strategy explicitly returned `next_state=None`. The model cannot mutate the persisted value by mutating its received object. `constraint_bounds` is the complete merged immutable bound set projected before callback; it is not a request to infer constraints. All `StrategyCall` data are bounded snapshots. No public call property/method exposes a mutable model object, account version/ID, workspace/catalog, source path/digest, evidence writer, state ref, Flow, or storage query.

## Annotation closure algorithm and acceptance test

Add `../qlibx/tests/boundaries/test_public_annotation_closure.py`. The test is mechanical and mandatory at T1 and T4/T5; it does not rely on documentation review.

1. Import only the supported public modules listed in the exact matrix in a clean subprocess. Read each module’s exact `__all__` and reject exported names that are aliases of a class/function owned by a second supported public module.
2. For every exported class, inspect constructor/dataclass field annotations, public `@property` return annotations, and all public callable parameter/return annotations using `inspect.get_annotations(..., eval_str=True)` and `typing.get_type_hints(..., include_extras=True)`. For every exported function, inspect parameters/return the same way. For abstract public contracts, inspect every abstract/public method.
3. Recursively walk `Annotated`, `Literal`, `Union`/`|`, `TypeAlias`, `type[T]`, `tuple`, `Mapping`, list/set/frozenset generic arguments. Standard-library allowlist is exactly `str`, `int`, `bool`, `float`, `object`, `NoneType`, `Path`, `date`, `datetime`, `time`, `Decimal`, `Mapping`, `Sequence`, `Literal`, `Annotated`, and their generic origins. No other unqualified/structural `object` is allowed except the explicitly specified opaque `config`, `previous_state`, `next_state`, and semantic row/detail value slots; those slots are annotated `object` by contract and validated by `vqapr.config/v1` at runtime.
4. Every remaining referenced class/type alias must have exactly one defining module in the supported public matrix, be named in exactly that module’s `__all__`, and be imported in annotations using that module’s canonical qualified reference. The test rejects missing resolution, duplicate public homes, re-export aliases, a `vqapr._internal.*` defining module, a former removed route, or a non-matrix `vqapr.*` module.
5. Assert the expected closure inventory includes and resolves exactly once: `Constraint`, `EconomicAccountView`, `AccountHistoryInput`, `DeclaredAccountHistory`, `ConstraintBounds`, `ConstraintCall`, `ConstraintFinding`, and `Diagnostic`, in addition to Revision 2’s declared type inventory. Include negative fixtures that deliberately reference `_internal.catalog.Catalog`, omit `Constraint` from authoring `__all__`, duplicate-export `Diagnostic`, and use an undefined forward reference; each must make the probe fail.
6. Add an AST companion check that every project-owned annotation in `src/vqapr/{__init__,project,authoring,materialization,simulation,portfolio,venues,analysis,testing}.py` and `src/vqapr/methodologies/**/*.py` is qualified/imported from its canonical matrix home. This catches a postponed string annotation that runtime resolution would otherwise accidentally satisfy through a local import.

## File-level delta

| File | Change |
|---|---|
| `../qlibx/src/vqapr/authoring.py` | Add exact AccountHistoryInput/EconomicAccountView/DeclaredAccountHistory/ConstraintBounds/ConstraintCall/ConstraintFinding/Constraint definitions and StrategyModel.account_history contract; update `__all__`. |
| `../qlibx/src/vqapr/project.py` | Add Diagnostic and bounded receipt serialization; annotate ExtensionDeclaration with `type[authoring.Constraint]`; update `__all__`. |
| `../qlibx/src/vqapr/simulation.py` | Annotate ConstraintDeclaration with `type[authoring.Constraint]`; do not re-export Constraint. |
| `../qlibx/src/vqapr/_internal/flow/*`, `_internal/constraints/*`, `_internal/account/*` | Adapt retained mechanics to construct/read these public immutable views and constraint adapters only; do not leak old `Constraint`, `AccountHistory`, `AccountSnapshot` version view, or raw bounds through public calls. |
| `../qlibx/src/vqapr/_internal/extensions/{load,register}.py` | Extend common local/built-in conformance to Constraint’s exact contract. |
| `../qlibx/tests/boundaries/test_public_annotation_closure.py` | New closure/import-home/negative-fixture test. |
| `../qlibx/tests/extension/*`, `tests/flow/*`, `tests/acceptance/*` | Add Constraint conformance, declared-history/bounds, immutable-view, diagnostic receipt, and invalid constraint pre-commit tests. |
| `vqapr-testbed-2/models/factors.py`, `build_factors.py` | No change required by this narrow delta beyond using the already planned `authoring.Constraint` home only if the testbed declares a custom constraint; factor run keeps explicit `constraints=()`. |

## Sequencing delta

Insert one bounded substep **2a** immediately after Revision 2 step 2 (“Define and test public algebra”) and before any `_internal` adapters:

**2a — close annotation capabilities.** Implement the changed export rows, exact definitions, constructor/view/failure invariants, Constraint conformance, and annotation-closure test. Gate step 3 on closure test success. No transaction, publication, relocation, parity, performance, or release behavior changes in this substep.

## Acceptance criteria delta

- Every type named in every public annotation resolves to either the stated standard-library allowlist or exactly one matrix-defined public home; no duplicate re-export/forward-path/internal type passes.
- `Constraint`, EconomicAccountView, DeclaredAccountHistory, ConstraintBounds, and Diagnostic are each defined, exported, and documented exactly once at the homes above.
- A fresh project can author/register a Constraint class using only `vqapr.authoring`, `vqapr.project`, and `vqapr.simulation`; no old/public-private loader/ref type is needed.
- Strategy account/history/bounds reads are immutable, declared/bounded, and reject undeclared/wrong-scope/uncovered access without fallback.
- Constraint input/schema/signature/source failures are zero-mutation preparation failures; runtime constraint return/exception failures are pre-commit and leave callback/account/pending state untouched.
- Registration diagnostic receipts are bounded/immutable/path-free and no rejected preparation returns a partial receipt.
- Mechanical closure test and all negative fixtures pass before the Revision 2 T2 candidate-CAS implementation starts.

## Verification delta

- Unit: diagnostic limit/type/immutability/serialization tests; EconomicAccountView snapshot/cash/position/nav coupling/quantity tests; history declaration/lookback/scope/missing/no-fill tests; bounds coverage/intersection/access tests; Constraint source/config/signature/alias/return conformance tests.
- Integration: custom Constraint reads a declared PIT alias, projects bounds, rejects an intended Rebalance, and proves no callback root/account/pending publication; monitoring creates framework-attested finding without author envelope fields.
- Boundary: clean-process module/export test plus mechanical annotation closure and four negative fixtures specified above; former old constraint/account/history qualified modules remain unavailable.
- Run these focused qlibx commands after implementation approval:

```powershell
cd ../qlibx
uv run --no-sync pytest -q tests/boundaries/test_public_annotation_closure.py tests/extension tests/flow
```

## RALPLAN-DR delta summary

- **Decision:** put Constraint and all StrategyCall economic read views in `vqapr.authoring`; put receipt Diagnostic in `vqapr.project`; add ConstraintCall/Finding and AccountHistoryInput only as the minimum supporting public types needed to make those contracts executable.
- **Rejected:** `_internal` annotations, simulation re-exports, unbounded raw account/history/constraint objects, and undocumented structural objects.
- **Rationale:** each is a public author capability and must be mechanically resolvable, bounded, and single-homed without reopening Revision 2’s resolved authority protocols.
- **Gate:** public annotation closure test must pass before adapters/candidate transactions; all original locked IDs and Revision 2 gates remain unchanged.

## Risks and mitigations delta

### Pre-mortem — type closure regresses into a public internal escape

- **Scenario:** an adapter annotates a public method with a legacy/internal `AccountSnapshot`, `ModelWindow`, `Catalog`, old Constraint, or raw finding.
- **Early warning:** annotation closure’s defining-module/AST check finds a non-matrix or `_internal` type.
- **Mitigation:** canonical qualified annotation rule, clean-process closure test, and negative fixtures.
- **Rollback:** stop at substep 2a; do not begin adapter/CAS work until closure passes.

### Pre-mortem — bounded views become implicit economic defaults

- **Scenario:** history access silently returns empty/filled values, bounds omit instruments, or nav is inferred from an unmarked account.
- **Early warning:** undeclared/wrong-scope fields do not raise, length exceeds lookback, absent panel values appear as zero, bounds differ from universe, or nav/instant coupling breaks.
- **Mitigation:** immutable view constructors, strict access errors, exact coverage/coupling checks, and focused unit/integration tests.
- **Rollback:** correct public view adapter before T2; do not introduce fallback behavior.


## Intent Reconciliation
No material post-consensus intent delta exists. All locked IDs are preserved. No economic default, compatibility route, alternate lifecycle, low-level escape hatch, or methodology change was introduced.

## Approval State
This plan is pending approval. It authorizes no source mutation, commit, push, release, or publication until a separate execution approval is recorded.
