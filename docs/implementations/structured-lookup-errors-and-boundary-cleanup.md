# Structured lookup errors and module-boundary cleanup

## Why this change exists

A refactoring review found that the CLI's documented error contract was only half
implemented, and that several module boundaries were expressed as duplicated literals
rather than as named contracts.

## What outcome it serves

- The `error_response` schema promises that every failure returns `code`, `message`,
  `action`, and `context`. Two commands broke that promise.
- PRD §4.6 expects an agent to recover from a failed lookup using the returned
  alternatives, which requires a machine-readable response rather than a traceback.

## Behavior change

`qlibx alpha operation <unknown>` and `qlibx extension contract <unknown>` previously
raised a bare `ValueError` and printed a Python traceback, because the CLI only
translates `QlibxError`. `catalog`, `registration` and `documentation` already raised
`QlibxError` for unknown-name lookups, so `alpha` and `extensions` were the inconsistent
ones; they now follow the same convention.

Three error codes are new and documented in `ERROR_GUIDANCE`, so `qlibx errors <code>`
answers for each: `QLIBX_ALPHA_OPERATION_UNKNOWN`, `QLIBX_BUDGET_POLICY_UNKNOWN`,
`QLIBX_EXTENSION_CONTRACT_UNKNOWN`.

`errors.unknown_name` builds the shared shape that four call sites previously hand-rolled,
so a failed lookup answers identically whichever registry raised it.

## Structural changes (no behavior change)

- `cli.dispatch` was a 179-line nested if/elif whose trailing bare `else` meant "agent
  instruction"; a command added to `parser()` without a matching branch silently ran that
  path. Each subcommand now binds its handler with `set_defaults(handler=...)` at the point
  of declaration, and `dispatch` is a lookup. Handlers return the value to print, so JSON
  encoding, printing and error translation stay in one place.
- `execution` built the same 16-field `SimpleNamespace` backend input in two functions,
  and the copies had already drifted on `active_booksize`. `ExecutionScenario` declares
  those fields once. The backend reads optional fields through `getattr(..., default)`, so
  a dataclass satisfies it while making a missing field fail at construction.
- `portfolio.construct_enhanced_index` repeated one normalize-and-cast expression seven
  times. `_AxisAligner.series` names it once; only `tradable` and `current_quantity` pass
  `fill`, which is now visible instead of requiring a visual diff.
- `strategy._digest` (pandas-structural) and `serialization` (JSON) were two different
  canonicalizations reachable under the same private name. They are now
  `serialization.digest_dataset` and `serialization.digest_document`, with the module
  docstring stating which to use. The move is verbatim: frozen invocation digests were
  compared before and after and are byte-identical.
- Shared serialization helpers were imported as `X as _y`, making package-level functions
  read as module-private. Call sites now use the real names, and the open-coded
  `_digest(_canonical(x))` idiom (7 sites) collapses to `digest_document(x)`.
- Removed `serialization.digest_value`, which was exported but never called.

## Efficiency

`ResearchCatalog` answered each question about the append-only event log with its own full
scan. `_EventProjection.build` folds the log once per operation: `query_context` drops from
three scans to one, and record manifests are parsed once per listing instead of twice.

The projection is deliberately **not** cached across calls. The catalog is append-only and
PRD §9.7 allows parallel agents to publish concurrently, so a cache spanning calls could
serve a stale view. One scan per operation is the correct boundary.

## Trade-offs

- `alpha` and `extensions` now import `qlibx.errors`. `errors` has no dependencies, so the
  direction is domain to shared kernel, and it buys contract consistency across every
  named lookup in the package.
- `_committed_record_ids` returns `frozenset`. `recover_publications` mutates a local copy
  because it commits additional records inside its own loop; two existing tests caught the
  first attempt and the copy is explicit.
- `ResearchCatalog` remains a large class. Splitting the event log, blob store, and
  publication protocol into separate collaborators is the natural next step but is a
  larger change than this pass, and was left out rather than started and abandoned.

## Validation

- `uv run ruff check .` and `uv run ruff format --check` — clean.
- `uv run pytest` — 96 passed (93 before).
- Three new invariant tests, each mutation-checked to confirm it is not vacuous:
  - every CLI leaf command binds a handler (removing one fails with
    `command alpha budgets has no handler`);
  - every raised `QlibxError` code has installed recovery guidance and vice versa
    (deleting one entry fails with `raised but undocumented`);
  - unknown-name lookups across three registries share one structured response shape.
- Frozen strategy invocation digests compared across the digest move: identical.
