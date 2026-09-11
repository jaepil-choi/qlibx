# `Rebalance.of` refuses a zero weight that `Rebalance.signed` keeps, and the refusal does not say how to hold a name at zero

**Status: UNTRIAGED — reported by testbed, not yet judged by the owner.**

| | |
|---|---|
| vqapr version | `0.14.4` |
| installed from | `vqapr-0.14.4-py3-none-any.whl` built in `vqapr/dist/` from develop `b8b47e6c`, copied into each run directory |
| reported | 2026-09-11 |
| reporter | `kwam-enhanced-index/vqapr-incr-testbed`, run `B-3` (haiku 4.5), agent session |
| python / OS | 3.12.13 / Windows 11 |

## What I was doing

An enhanced index on KRX. The strategy holds KOSPI200 at index weight and underweights a name by
0.5%p, floored at zero. So zero is a legitimate target, and it means "hold none of this name".

## What I expected

A zero weight to mean "hold none", or a refusal that says how to express it.

## What happened

The strategy returned `Rebalance.of(long={..., "A000100": 0, ...}, invested=...)`, and the run
stopped mid-run:

```text
strategy.callback.intent (502)
  long['A000100'] must be positive: a side is chosen by which mapping the name appears in, not by
  the sign of its weight
```

- **The two constructors disagree.** `Rebalance.signed` keeps a zero weight "as a flat position
  rather than dropped", in its own docstring's words. `Rebalance.of` refuses the same weight.
- **The message answers a different question.** It explains how sides are chosen, which was not
  the problem. It does not say that leaving the name out sells it to zero on the next fill.
- **Another agent had to decide the same thing unaided.** B-1 (opus) removed zero-weight names
  from the mapping and wrote that down as a decision it had to make. B-3 learned it from this
  refusal.

## Reproduction

Return `Rebalance.of(long={"A": 1, "B": 0})` from a strategy's `decide` and run it.

## Impact

One failed run for the haiku agent. The fix is small once known, but a zero target is a common
outcome of any tilt that floors at zero.

## What would have prevented it

- **Accept zero in `of` as `signed` does.** A zero weight would mean a flat position.
- **Or say in the refusal how to hold none.** For example: "to hold none, leave the name out; a held
  name absent from the targets is sold to zero".
