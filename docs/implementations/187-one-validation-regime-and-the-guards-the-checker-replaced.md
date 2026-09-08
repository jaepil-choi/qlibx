# 187 — One validation regime, and the guards the checker replaced

**Date:** 2026-09-08. **Branch:** `redesign/component-eventloop` (campaign M5b; plan
`.agent/plans/active/component-eventloop-redesign.md`). **Review:**
`docs/code-review/2026-09-08-four-readers-one-loop-and-the-missing-shapes.md` §5, §8-4, order 4.

## Why

The package had **two validation regimes**: pydantic frozen models for anything stored to disk
(seven modules), and `@dataclass(frozen=True) + __post_init__` with hand-written `isinstance`
checks for everything else. The same rule -- *this must be a finite Decimal* -- was written two
ways depending on which side of the line a value fell, and the line was historical rather than
principled. The owner's ruling (2026-09-08): **pydantic by default**; a lightweight dataclass
only for a validation-free carrier the engine hands to itself.

The second half follows from record `186`. With `pyright src` at zero, a runtime
`isinstance(frozen_run, FrozenRun)` on a parameter annotated `FrozenRun`, called only from
engine code, checks something the checker has already proved. It is not free: it is a line a
reader must decide the meaning of, and 585 of them taught that the annotations were decoration.
What stays is every check at a **boundary** -- what an author's `decide` / `compute` / `judge` /
`execute` returns, what `load_*` admits, what a document decodes to, what a row from disk
carries -- because there the annotation is a hope and the check is the thing that makes it true.

## What

### The author-facing values are pydantic frozen models

`ConfigDict(extra="forbid", frozen=True, strict=True)`, the house style of `flow/run.py`:

- `data/lookback.py`: `RowsLookback`, `InstantsLookback`, `CalendarLookback`, over a shared
  `_Lookback` base. `strict=True` is what keeps a count a count -- `RowsLookback(True)` and
  `RowsLookback("3")` are refused rather than coerced, which is what the `isinstance(value, int)
  and not isinstance(value, bool)` pair spelled by hand.
- `data/requirements.py`: `DataRequirement`. `of()` keeps the reserved-name rule; the lookback
  union is the field's type rather than a check in the body.
- `authoring.py`: `DatasetInput`, `AccountHistoryInput`, `ConstraintBounds`, `Hold`,
  `Rebalance`, `ConstraintFinding`. `Rebalance.of()` and `.signed()` are untouched, and every
  invariant of the old `__post_init__` is an after-validator with its message intact -- the
  budget refusals that name their numbers (`docs/issues/071`) are asserted sentence for
  sentence by `tests/qa/test_a_budget_refusal_names_its_numbers.py`.
- `portfolio/budgets.py`: `Budget`. `account/snapshot.py`: `AccountSnapshot`.
  `exchange/listings.py`: `TradeRule` (with a `replace()` that re-validates through
  `model_validate` -- `model_copy` is forbidden on a rule-bearing model, memory
  `pydantic-model-copy-does-not-revalidate`) and `ExecutionFieldRequirement`.
  `exchange/venues/krx.py`: `KrxTradeRule` inherits the base's validators, so the explicit
  `TradeRule.__post_init__(self)` call that slotted subclassing forced is gone.
- **Coercions are kept as validators, not lost.** `_copy_weights` returning a read-only
  `CrossSection[Decimal]`, `AccountSnapshot` dropping zero positions into a `MappingProxyType`,
  `ConstraintFinding.details` bounded to 32 keys and frozen: all `mode="before"` /
  `mode="after"` now, so an author's `dict` still goes in and the same read-only value comes out.
- **The trusted door.** `AccountSnapshot.trusted(version=, cash=, positions=)` on
  `model_construct`, used once per commit in `Account.prepare_fill` where every field was just
  derived from a snapshot that already passed and from fills the batch already validated.

### The engine's own type guards are gone

134 `isinstance` sites deleted from the engine (those files 306 -> 172; package-wide 585 at the
review, 569 at M5a, **423** now). The canonical case is `StrategyEventLoop.__init__`, which
checked fifteen constructor arguments the type checker now reads. Where a guard mixed a type
check with a value check the value half stays as a `ValueError` (a non-empty `agenda_id`, a
64-character identity, `layer not in frozen_run.strategies`). Where a guard was the only
narrowing of an `AccountState | None` root it became an explicit `is None` refusal, so the reads
after it stay type-safe.

Kept, by rule rather than by file: author returns (`Hold` / `Rebalance` from `decide`,
`tables()`, `requirements()`, `account_history()`, `Fill` / `FillReport` from `execute`), the
public doors (`run`, `run_frozen`, `preflight_run`), registration declarations
(`ExecutionTableSpec`, `FillConvention`, `DatasetRegistration`, the instrument roster), values
read from disk or from the venue table, and every `isinstance` that implements behaviour rather
than a guard -- a `bool` refused before an `int`, a `Mapping` branch that picks a code path,
`normalize_memory`.

No test was deleted: none of the 134 was pinned by one. The tests that assert a "must be a ..."
refusal all target guards that stayed, which is the evidence the split was drawn where it was
claimed.

`object.__setattr__` falls 62 -> 51 and `-> object` 30 -> 13; the 13 that remain are all
`mode="before"` validators, the author-boundary scalar coercion, annotation introspection, the
record encoder, and the loader that returns a user's own instance.

## Trade-offs

- **A wrong TYPE at an author door now raises `pydantic.ValidationError`.** It is a `ValueError`
  subclass, and the sentence inside is the one the `__post_init__` wrote; what is new is
  pydantic's envelope around it (`1 validation error for Rebalance ... For further information
  visit ...`), which an author sees when a refusal is stringified into a run record. A wrong
  type refused *inside* a before-validator still raises the old `TypeError` unchanged, because
  pydantic does not wrap it. Seven tests were updated to the new type; the assertions on the
  message text are unchanged.
- **The hot path pays for the door, and the numbers say it is affordable.** At 3,000 names,
  once per callback:

  | value | per construction |
  |---|---|
  | `Rebalance` | 2.72 ms |
  | `ConstraintBounds` | 4.18 ms |
  | `AccountSnapshot` (validated) | 0.41 ms |
  | `AccountSnapshot.trusted` | 0.01 ms |

  Cross-section arithmetic at the same width is ~10 ms per callback and a real run's time is
  data movement (`docs/issues/068`), so these are the same order as work already being done and
  not a new bottleneck. The 41x gap on the snapshot is why the trusted door exists and why it is
  used at the one place that runs per commit rather than per callback.
- **Positional construction is kept** with an explicit `__init__` that forwards to pydantic's,
  because `RowsLookback(313)`, `AccountSnapshot(0, cash, positions)`, `TradeRule("A", ...)` and
  `Budget(direction, ...)` are spelled that way by scaffolded venue files, the shipped sample
  strategy, and the tree. `ConstraintBounds` and `Rebalance` take the same treatment for a
  different reason: the parameter is a `Mapping[str, Decimal]` while the field is the validated
  `CrossSection[Decimal]`, and only an explicit signature says both.
- **Two guards survive on a technicality.** `StrategyEventLoop.pending()` and
  `_dispatch_pending` still check `isinstance(pending, (AcceptedIntent, PendingValuation))`
  because `AcceptedRunState.pending_accepted_intent` is typed `object`; typing it needs a
  `TYPE_CHECKING` import of `flow/context.py` into `flow/run_state.py`, which M6 rearranges
  anyway. Same reason record `186` left that field alone.
- **`callable(...)` / `getattr(exchange, "execute")` duck checks remain** in the two loop
  constructors. They are the same redundancy in a different spelling, and deleting them is a
  separate decision about whether a test double may be a duck.

## Validation

- `uv run pytest tests/ -q` (fast set): 1572 passed, 5 skipped.
- `uv run pyright src`: 0 errors. `uv run ruff check src`: clean.
- `uv run --no-sync python showcases/show_001_execution_input_registration/run.py`: runs.
- Counters: `isinstance(` 569 -> 423; `object.__setattr__` 62 -> 51; `-> object` 30 -> 13.
