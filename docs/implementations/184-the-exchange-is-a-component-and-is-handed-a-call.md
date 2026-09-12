# 184 — The Exchange is a Component, and is handed a call

**Date:** 2026-09-08. **Branch:** `redesign/component-eventloop` (campaign M4a; plan
`.agent/plans/active/component-eventloop-redesign.md`). **Review:**
`docs/code-review/2026-09-08-four-readers-one-loop-and-the-missing-shapes.md` §1 ②, §8-2.

## Why

Of the four authored kinds the Exchange was the one that wrote the shared pattern in a foreign
spelling: a `Protocol` rather than the base the other three share, three positional arguments
rather than a `Call`, and the project's roster planted on it by the framework with
`object.__setattr__(venue, "_registry", ...)` because `execute`'s signature "was not ours to
change" (`flow/execution.py`, `bind_registry_to_venue`). The owner's ruling (2026-09-08) named
what the four have in common -- objects called back on an event with that event's time -- and
what makes the Exchange different: not that it reads one instant (a strategy can read one row
too) but that **it is handed the order batch it must execute** beside the data.

## What

- `exchange/venue.py`: `Exchange(Component)` is an ABC with an abstract `rules` property,
  `execution_requirements()` (default empty) and an abstract `execute(call: ExecutionCall) ->
  FillBatch`. `ExecutionCall` is a frozen value: `at` (the fill instant), `orders`, `account`,
  `snapshot` (the execution table read exactly at `at`) and `rules` (the venue's own view, bound
  to the roster when the run registered one). `ExecutionCall.of(venue, orders, account,
  snapshot, registry=None)` builds one the way the handler does.
- `AcademicExchange` is a plain (`eq=False`) dataclass rather than a frozen one -- a Component
  carries `memory` the engine restores and commits, and a frozen instance could not receive it
  -- and its `rules` view is unbound: the roster arrives through the call. `KrxExchange` is an
  `Exchange` and reads `call.rules` instead of its cached `_rules`.
- `flow/execution.py`: the handler builds one bound `ExchangeRulesView` and hands it to both
  `plan_orders` and the venue's `ExecutionCall`. `bind_registry_to_venue` is deleted; nothing
  writes into a venue.
- **Component memory is committed for the venue too.** The constraint plumbing of record `181`
  generalised: `AcceptedRunState.component_state_refs` (was `constraint_state_refs`),
  `RunStateRepository(initial_component_memory=...)`, `prepare_callback` /
  `prepare_monitoring` / `prepare_account_commit(component_memory=...)`. `FlowContext.
  stateful_components()` is every constraint plus the venue when it is a `Component`; the
  execution handler restores the venue's memory before `execute` and commits what it left with
  the fills. A test double that only offers `execute` carries no memory and is left alone.
- `vqapr.public` exports `ExecutionCall`.
- Tests: every `venue.execute(orders, account, snapshot)` became
  `venue.execute(ExecutionCall.of(venue, orders, account, snapshot))`; the flow tests seed the
  academic venue's memory beside the constraint's.

## Trade-offs

- **`execute`'s signature changed** for every registered venue subclass. Allowed (fast
  development stage), and small in practice: `load_exchange` refuses a subclass that overrides
  `execute`, so a user's venue only ever added listings and costs.
- **`ExecutionCall.snapshot` is still an `ExactExecutionSnapshot`** read from a separately
  registered execution input. M4b makes the execution table a registered dataset and the run
  the owner of `trade_price`; the call is the seam that change lands on.
- **The venue's `memory` has no payload.** Same as a constraint's (record `181`).

## Validation

- `uv run pytest tests/ -q` (fast set): 1576 passed.
- `uv run ruff check src/`: clean. `uv run pyright`: 180 errors (181 before).
