# 097 — `flow/engine/loop.py` is an abstract loop with one subclass, and the two assemblies are classes that only construct

**Status: OPEN 2026-09-10 -- owner-filed, from the 0.11.0 spine trace
(`experiments/exp_230_the_spine_trace/`). Plan: `.agent/plans/active/one-door-campaign.md`, milestone L.**

| | |
|---|---|
| vqapr version | `0.11.0` (develop `05dbc1f5`) |
| reported | 2026-09-10 |
| reporter | owner, asking what `flow/run/loop` and `flow/engine/loop` differ in |
| evidence | `grep` of `EventLoop` subclasses; record `227`'s docstring |

## What the owner asked

> flow/run/loop 랑 flow/engine/loop 는 또 무슨 차이야?

## What the code is

- `flow/engine/loop.py` -- `EventLoop`, an `ABC` with three type parameters and abstract
  `handle`/`finish`; `run()` is the walk (start, sort events, handle each, finish). Written when
  there were two loops (record `182`) so the walk would be shared.
- `flow/run/loop.py` -- `RunLoop(EventLoop)`, the **only** subclass in `src/` (one `grep`, one
  hit). It adds the one thing the walk needs: an event is the part's or the market clock's.
  Beside it: `Part`, `MarketClock`, `StrategyPart`, `DataModelPart`, and two subclasses of
  `RunLoop` -- `StrategyEventLoop` and `DataModelEventLoop` -- whose whole body is `__init__`
  (authority checks, handler construction, `super().__init__(...)`).

So the answer to the owner's question is "one is the abstract walk, the other its only
implementation", and that is the finding: after record `227` the abstraction has nothing left to
abstract over. A reader meets three loop classes and two files to understand one loop. The
owner's bar (2026-09-10): OOP를 위한 OOP는 overengineering이야.

## Proposed fix (milestone L of the plan)

- Fold `EventLoop.run` into `RunLoop`; delete the `ABC`. `flow/engine/loop.py` keeps only the
  events (`Event`, `OccurrenceEvent`, `MarketEvent`) and the sort rule (market before decision at
  one instant), which is a fact about events, not about a loop.
- `StrategyEventLoop` and `DataModelEventLoop` become two functions, `strategy_loop(...) ->
  RunLoop` and `datamodel_loop(...) -> RunLoop`: a subclass whose only method is `__init__` is a
  factory. Twelve call sites in `src/` and `tests/` (13 test files import the names).
- `RunLoop`'s docstring says the three sentences a reader needs: one walk, a part on the strategy
  clock, a market clock when the run has one. `docs/vqapr-architecture.md` §3 and the
  `two-clocks-and-the-wiring-table` design name the one class.

Small enough to be one record. It goes first in the plan because P and V both touch the run path
and should land on the folded loop.
