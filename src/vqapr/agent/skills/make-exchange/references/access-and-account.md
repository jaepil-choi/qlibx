# `ListingAccess` and the account's mode must agree

## The pairing nothing refuses

`--profile krx` builds every listing through `krx_listings`, which sets
`access=ListingAccess.LONG_ONLY`.

Pair that with `initial_account.mode: SIGNED` and you get a run that **scaffolds cleanly,
registers cleanly, and cannot hold a position**: the account permits the short and the venue
declines it, on every attempt. Nothing refuses the combination when it is written, because neither
half is wrong on its own.

**Check the pair explicitly** before running, and say which way you resolved it:

| the book is | venue `access` | account mode |
|---|---|---|
| long-only | `LONG_ONLY` (or `--profile krx`) | long-only |
| signed | `SIGNED` on your own listings | `SIGNED` |

## There is no shipped costed signed profile

`--profile krx` is costed and long-only. `--profile academic` is signed-capable and free.

**A costed long/short book is a venue you write.** Set `access=ListingAccess.SIGNED` — the member
for a rule that may be held either way — and declare the costs yourself, subclassing
`AcademicExchange`. Start from `krx_rules` for the cost shapes if the venue is Korean, but do not
start from `--profile krx` itself: you would be removing its access rule from every listing.

## Two things that look like one switch and are not

| what | decided by |
|---|---|
| fractional allowed, lot / quantity step, rounding, price source, cost, fill timing | **the execution profile**, per instrument listing at that venue |
| whether a negative position is allowed | **the account's state-transition validity**, frozen when the run starts |

Merging them creates the false inference *"academic, therefore fractional"*, and makes it
impossible to treat the same instrument differently at two venues — which is the whole point of
having a venue as a separate component.

## Frozen at the start of the run

A run's state-transition validity is fixed when it begins. It cannot move between long-only and
signed mid-run.

A user may run the **same frozen intended portfolio** through different compatible profiles — that
is supported and is how a realism comparison is done. Swapping the profile does not silently
rewrite what the intended portfolio meant; each run records its own supported instruments,
permitted direction, quantity semantics, fill timing, cost, cash treatment and limitations.

## What a local Exchange may not do

It cannot redefine **account authority, valuation, or the run lifecycle**. Those define what a
result means, and a project that redefined them would produce results no other run can be compared
with.

Built-in and project-local venues go through the same registration and the same validation. A
capability the built-ins use is available to yours — otherwise the built-in would be an example
nobody can reproduce.
