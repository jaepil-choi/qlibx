# 090 — `invested` states its ceiling, and what the ceiling costs

**Closes:** `docs/issues/archive/018-a-gross-exposure-parameter-cannot-reach-textbook-scale.md`.
**Branch:** `fix/018-invested-bound`.

## Why this change exists

`Rebalance.of`'s docstring frames `invested` as GROSS exposure and points out that cash can exceed 1
and is never `1 - invested`. The reporter's reading, and it is a fair one:

> A quantity that is explicitly not `1 - cash`, and whose companion sentence points out that cash
> can exceed 1, does not read as capped at 1.

It is capped at 1. And the two sides split it evenly on top, so `invested=1` on a signed book is
0.5 long and 0.5 short. The consequence landed on the deliverable: every number in that journey's
report is exactly half a textbook $1-long/$1-short SMB+HML, and the headline must be doubled before
it can be compared to anything published.

## The open question, and how it was settled

The issue asked whether the ceiling is an accounting invariant or a leftover from a one-minus-cash
reading. The plan flagged it as a design-intent question the code could not settle. **It could.**

A `Rebalance` with weights `+1`/`-1` and cash `1` was constructed directly and satisfies every
downstream invariant: the signed budget admits positions in `[-1, 1]` (`authoring.py`, the `shorts`
branch) and cash in `[-1, 2]`, the latter widened deliberately because short-sale proceeds raise
cash above 1.

So the representation supports the standard scale, and the accounting accepts it. **The ceiling
belongs to `Rebalance.of` alone** — it is a property of the relative-conviction constructor, not a
protection around the account. That is now stated in the docstring rather than left for the next
reader to rediscover by experiment.

**No behaviour changed.** Lifting the cap is a product decision with a blast radius well past this
issue's "docs + code?" scope, and the issue itself only asks that the surface stop implying
something it does not deliver. An author who needs the standard scale now has a documented way
through — build the `Rebalance` directly — rather than a dead end.

## What changed

- **The refusal** (`src/vqapr/authoring.py`) now names the legal range, says what was actually
  passed, and states the halving: *"It is GROSS exposure and both sides split it evenly, so the most
  a signed book can reach through this constructor is 0.5 long and 0.5 short."* It also names the
  way past it. Previously it stated the bound and stopped, leaving the more surprising half — that
  the bound is halved again — to be discovered.
- **The docstring** states the bound `0 < invested <= 1` alongside GROSS, states that each side takes
  `invested / 2`, states the consequence in the reader's own terms (a published series quoted at
  $1-long/$1-short is twice what comes out of here; read a factor return built this way as
  half-scale or double it before comparing), and records that neither the bound nor the split is an
  accounting invariant.

### The `explain` and `fix` halves came free from 088

The merge condition also required the failure to carry an `explain` topic and a `fix`. This is a
bare `ValueError` raised inside the callback, so it is exactly the shape `docs/implementations/088`
repaired one branch earlier. Verified by composing them: the refusal now arrives as
`simulation.callback.intent.ValueError` with `requirement: the strategy callback must return without
raising`, `explain: component-contract`, a `fix` naming the exception and the repair loop, and the
enriched message in `observed`. This is what the campaign's ordering was for — 016 before 018 makes
018's message half free, and only the cap question remains.

## Validation

**Gate:** `test_all`, unconditionally. The plan set this deliberately: the earlier "fast, or
`test_all` if the bound moves" left an executor unable to know its own merge gate before the
question settled, and one extra suite run is cheaper than that ambiguity.

| check | result |
|---|---|
| `tests/models/test_invested_states_its_ceiling.py` (new) | 4 passed |
| **full suite, all marks** | **1372 passed, 0 failed**, 408.05s |

The four tests pin: the refusal names the range, what was passed, and the halving; `invested=1` on a
signed book really is 0.5/-0.5 with cash 1; a `+1/-1` book is valid, which is the evidence settling
the open question; and the docstring states the bound, the halving, the cost, and the invariant
finding — asserted on `__doc__`, because a reader who never learns about the halving publishes a
number half the size they think it is.
