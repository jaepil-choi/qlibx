# 186 — The type checker reports nothing, and `object` means nothing

**Date:** 2026-09-08. **Branch:** `redesign/component-eventloop` (campaign M5a; plan
`.agent/plans/active/component-eventloop-redesign.md`). **Review:**
`docs/code-review/2026-09-08-four-readers-one-loop-and-the-missing-shapes.md` §5, order 0.

## Why

M0 put pyright on the gate and measured 184 errors (basic mode, `src/` only). The review's
reading of that number: the package checks by hand what a type would carry -- 585 `isinstance`,
30 `-> object` -- because the types it wrote did not say enough for a checker to help. An
`object`-typed field on `FlowContext` was read by five handlers, and every read was an error the
checker could not localise; a Protocol method without a return annotation made every caller of
the catalog an error. Until that count is zero the later steps (one validation regime, the
internal guards deleted) are documentation, because nothing would catch what the guards catch
today.

## What

`uv run pyright src` reports **0 errors** (184 at M0, 180 after M4b). By root cause:

- **`object` replaced by the real type.** `OccurrenceTrace.result`, `DueExecutionTrace.result`,
  `DueExecutionResult.post_account_result`, `HeldResult.valuation`, `monitoring`,
  `FlowContext.scan_session` / `registry` / `recorded_measurements` (`flow/context.py`, and the
  matching `StrategyEventLoop` constructor); the snapshot and publication closures in the
  execution and valuation handlers; the memory and state-ref locals of the callback handler;
  `_validate_initial_model_state(memory: ModelMemory)`; `Account.prepare_mark` /
  `prepare_valuation` stamps; `AccountHistory.marks`; `ExchangeRulesView.registry` /
  `terms_by_kind`; `_DeclaredReads.window` / `reads`; `build_horizon(session: ScanSession |
  None)`; `_outward(frame: FrameType | None)`; `FrozenAgenda.encoded`;
  `_roster_report_or_stale`; `Registered` (the roster receipt is a mapping, not a string);
  `SHIPPED_EXECUTION_PROFILES: tuple[type[Exchange], ...]`; `lookback_fits_grain`; the
  `DatasetCatalog.dataset()` Protocol returns `DatasetRegistration` (it returned nothing, so
  pyright inferred `None` and reported 26 errors in `data/store.py` alone).
- **An Optional that cannot be `None` is refused, not assumed.** `RuntimeError` naming the
  invariant where the engine's own construction guarantees a value: a tradable row's price
  (`KrxExchange.execute`), the latest mark after a prepared transition, the marked root's
  account, the run's exchange / opening account / mode inside `_run_strategy` (already refused
  by `run()`), the frozen account pair in `_derive_identity`, the resolved tolerance, a
  `count(*)` cursor row (`scan._one_row`, also in the skill's `profile_source.py`), a measured
  span. Where an ordinary refusal already existed the narrowing was added to its condition
  (`LOOKBACK_UNCOVERED` needs a span; a non-`str` instrument cell is `instrument_invalid`).
- **The base class's contract instead of a subclass attribute.** Preflight reads
  `exchange.rules.listings`, which `Exchange` promises, rather than `AcademicExchange.listings`;
  `exchange.execution_requirements()` replaces a `getattr` fallback that was dead since
  `load_exchange` admits only `Exchange` subclasses.
- **Typed identifiers at their constructors.** `occurrence_id(...)`, `agenda_id(...)`,
  `ComponentId(...)` where a plain `str` was handed to a `NewType` parameter.
- **Positional reads of the workspace state are gone.** `remove` and `_references_in` read
  `_State` by field name; the tuple lost a member at record 185 and the positional read was
  the one place that noticed too late.
- **Two pyright quirks named.** A `finalization: object = None` field made pyright discard the
  whole root after an `is not None` check (`"Never" is not iterable`); it is
  `RunFinalization | None`, which is what `__post_init__` enforced. `DecimalTuple.exponent` is
  `int | Literal['n', 'N', 'F']` in typeshed, accurately; `portfolio.optimize.finite_exponent`
  narrows it once for both callers.
- **Stub defects, two.** `pyarrow.compute.drop_null` and `pyarrow.compute.max` are bound at
  import time and absent from the stubs; both carry `# type: ignore[attr-defined]` with that
  sentence. No other ignore and no `cast` was added.
- The lazy `InstrumentRoster` import in `exchange/listings.py` moved to the top (no cycle);
  the deferred-import ceiling is 12.

## Trade-offs

- **Behaviour is unchanged by intent, and a few impossible paths now fail with a named error
  instead of an attribute error.** A non-`datetime` `TIMESTAMPTZ` cell, a duck-typed registry
  that is not an `InstrumentRoster`, a horizon without a run end.
- **`AcceptedRunState.pending_accepted_intent` is still `object`.** The same quirk silences
  two `is not None` checks; typing it needs a `TYPE_CHECKING` import from `context.py` and a
  sentinel for `prepare_callback`. Left for M5b, which touches that state anyway.
- **`ruff format` is not the gate** (`ruff check src` is); the files touched keep their
  pre-existing wrapping.

## Validation

- `uv run pyright src`: 0 errors, 0 warnings.
- `uv run ruff check src`: clean.
- `uv run pytest tests/ -q` (fast set): 1571 passed, 5 skipped, then the deferred-import
  ceiling lowered to 12 and its four tests pass.
