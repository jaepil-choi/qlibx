# 167 — explicit runtime ownership and readable execution boundaries

**Closes:** R1, R2, R3, R4 and the sample half of R7 of the
[0.6.0 call-flow review](../diagnostics/2026-09-07-v060-call-flow-review.md); assesses R5 and
records the decision. **Branch:** `develop @ 7d2ab0ee` (v0.6.0), checkpointed at `cf5f7211`
(M1-M2) and finished in the session that followed. **Campaign:** none; the
[proposal](../refactoring/2026-09-07-v060-call-flow-proposal.md) ordered the work. **Scope:**
`flow/orchestration.py`, `flow/context.py`, `flow/simulation.py`, `flow/callback.py`,
`flow/execution.py`, `flow/valuation.py`, `workspace.py`, `agent/sample/journey.py`, two tests,
the diagnostics index. No record format, public result shape or economic rule changed.

## Why this exists

The review ran the registered sample through the CLI under `sys.setprofile` and injected a
constructor failure. It found four things a reader of the runtime spine should not have to work
around:

- **R1.** `_run_strategy` opened a `ScanSession`, opened the record writer and built the flow
  before its `try`, so a failure in requirements checking, state construction or the
  `SimulationFlow` constructor reached neither `release` nor `close`. Injected: one session and one
  writer opened, zero closed, zero released.
- **R2.** `ValuationPhase` stored a `CallbackPhase` it never read, `SimulationFlow` back-patched
  it after construction, and `Workspace._commit` had no caller.
- **R3.** `FlowContext()` took no arguments and annotated its fields; `SimulationFlow.__init__`
  filled them one by one afterwards, so nothing said when a context was complete.
- **R4.** Every stage boundary was a higher-order call — `guard(stage, cutoff, lambda: ...)`,
  `due_boundary(..., operation=lambda: ...)` — so the live stack under `plan_orders` was 17
  package frames, four of them `timed -> lambda -> guard -> lambda`, and `execute_due` read as
  metadata around lambdas rather than as the fill chain it is.

The review's caveats hold: the injection proved a skipped cleanup, not a leak; the wrappers cost
readability, not measurable time.

## What changed

- **Ownership begins at acquisition** (`orchestration.py`, `_run_strategy` and `_run_datamodel`).
  The `try` opens immediately after `ScanSession()`; the writer variable is bound only after
  `open` returned, so the `except BaseException` branch releases exactly the writer this run
  acquired and never the claim of a run whose `RunRecordLive` refused ours. `finally` closes the
  session. `tests/flow/test_runtime_resource_ownership.py` injects a failure at the store, the
  writer's `open` and the flow constructor for both member kinds, counts closes and releases, and
  proves two consecutive `RunRecordLive` refusals leave the other run's lock in place.
- **The context is built complete** (`context.py`). `FlowContext` is a keyword-only dataclass:
  the authorities — frozen run, layer, state, account, exchange, strategy, constraints, valuation
  service, the three window factories — are required; the per-strategy bookkeeping (`timing`,
  `horizon`, `recorded_measurements`) has defaults. `SimulationFlow.__init__` validates, then
  constructs it once. `static_occurrences` and `on_progress` moved to the loop, which is the
  only reader.
- **Phases reference what they call** (`simulation.py`, `valuation.py`, `callback.py`).
  `ValuationPhase(context)` and `CallbackPhase(context)`; the callback reads the committed mark
  off the account state it already holds. `ExecutionPhase(context, valuation)` stays, because
  execution does call valuation, in that order. `Workspace._commit` is deleted.
- **Boundaries are lexical** (`context.py`, every phase). `timed`, `guard` and `due_boundary`
  are `@contextmanager`s; a stage reads as

  ```python
  with self._context.due_boundary(stage=..., cutoff=..., owner=..., family=..., kind=...):
      orders = plan_orders(...)
  ```

  Exception translation, `__cause__`, `stage`, `family`, `owner`, `PRE_COMMIT` versus
  `FAILED_AFTER_COMMIT` and the per-stage timing keys are unchanged: the translation moved from a
  `return operation()` inside `try` to the `except` clauses around a `yield`, which is the same
  clause. `_callback_intent_boundary` keeps its data-owner branch. No generic pipeline, no step
  registry.
- **The sample passes the product's own check** (`agent/sample/journey.py`). The registered
  run's horizon now opens on the second session: the first close is published at 15:30 and the
  decision is made at 08:00, so a horizon opening on the first session asked its first decision
  for history the dataset did not have, and `vqapr check` refused it with
  `check.lookback.uncovered` while `execute`, which reaches `preflight_run` and `run` directly,
  accepted it. The strategy Held through that session either way. Counts:

  | | before | after |
  | --- | --- | --- |
  | occurrences | 1470 | 1468 |
  | account version | 729 | 729 |
  | run-state version | 2929 | 2927 |

  `test_the_installed_sample_is_accepted_by_the_products_own_check` asks the judgments of what
  `install` registered and expects nothing found and nothing blocked.
- **The diagnostics index** says which of its 2026-09-03 observations record 164 superseded.

## What was assessed and NOT changed

- **R5, four `load_strategy_model` calls per CLI run.** Measured again after the change: still
  four, and two `load_exchange`. Three are contracts, not duplication: `_freeze_strategy` stages
  the initial payload from one fresh instance, `_validate_initial_model_state` restores it on a
  second fresh instance (`docs/issues/076`), and `_run_strategy` owns the mutable instance that
  runs. The one recoverable load is the judgments' — it reads `requirements()` and nothing
  else — and recovering it means handing a loaded object from `judgments` into `preflight_run`
  across two verbs whose contract is that neither passes objects to the other. One module import
  per member per command does not pay for that signature. Decision: leave it; if a member load
  ever becomes expensive, the fix is to pass the validated declaration, not the instance, and
  never a module-level cache (a cache would hide a source edit under `--jobs`).
- **The two doors were still two doors** when this record closed: `judgments` was asked by
  `vqapr run` and not by the public `preflight_run`, so the sample's `execute` could not ask
  what the CLI asked. Left open here as an owner decision about the surface; decided the next
  day and closed by record [`168`](168-the-python-door-asks-the-judgments-too.md).
- **`OccurrenceFlow` inheritance, `RunResult`'s four mappings, `record.py`'s size,
  `observation_rows`'s branches**: per the proposal's §6, no evidence from this work argues for
  touching them.
- **Vulture** after the change: 22 candidates (23 in the review; `_commit` is gone). Every
  remaining one was classified in the review as a serialisation field, a context-manager
  signature, a compatibility field or a test helper; none is dead production code.

## Evidence

`docs/diagnostics/v060-review-evidence/record-167-before-after.json`: the review's
`review-bounded` run (ten sessions, v0.6.0 tree) against the same registered run re-executed by
`probe.py` on this tree.

- Envelope minus timing and paths: equal. `strategy.json` minus `timing`: equal. `run.json`:
  equal. `vqapr.weight` (30 rows), `vqapr.account` (40), `vqapr.fill` (42): schema and data
  equal. Timing keys: the same set.
- Package frames at the first call: `decide` 13 → 9, `execute_due` 13 → 9, `plan_orders`
  17 → 10, `Account.prepare_fill` 17 → 10. The stack under `plan_orders` is now
  `main → run → orchestration.run → _run_strategy → SimulationFlow.run → OccurrenceFlow.run →
  _dispatch_due → _dispatch_pending → execute_due → plan_orders`.
- Lambda calls under `flow/`: 337 → 16 (the window factories, which are closures by design).
  Distinct code labels: 628 → 593. The boundary generators register twice as many `call` events
  because a generator-based context manager is entered and exited; the boundaries themselves
  are the same 92 guards, 150 due stages and 80 intent boundaries per ten sessions.

## Validation

- `uv run ruff check src/` and on both edited tests: clean. `ruff format --check` on the edited
  sample and test: clean.
- `pytest tests/flow tests/qa/test_callback_failure_carries_the_whole_envelope.py
  tests/qa/test_run_records_survive_and_race.py -q`: **193 passed, 5 deselected** (376 s; the
  record race tests dominate).
- `uv run vulture`: 22 candidates, all previously classified.
- The shifted sample, installed into a scratch project: judgments found nothing and blocked
  nothing; `execute` reported 1468 occurrences, account version 729, run-state version 2927.
- `test_all` (`uv run pytest tests/ -q -m ""`, the thirteen slow journeys and the real-data sample
  tests included, data/DW present): **1451 passed, 0 failed, 0 skipped** in 928 s. The shifted
  sample's new counts and the new acceptance test passed inside that run.
