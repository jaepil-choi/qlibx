# Universe, listing and tradability

## Contents

- Not every dataset needs these
- Two different questions that share a word
- The investment universe belongs to the strategy
- Deriving halts when there is no halt history
- "Unknown" is not a value

## Not every dataset needs these

Universe and tradability are **not** registration requirements. The operation that needs them
declares them: a cross-sectional comparison needs coverage, a benchmark-relative construction
needs membership. A plain signal study must not be blocked by market fields it never reads.

The converse is the part to hold firm on: **real order generation must not proceed on estimated
defaults** for price, lot or tradability.

## Two different questions that share a word

| question | when | who asks | answered from |
|---|---|---|---|
| is this name a candidate? | decision time | StrategyModel | a registered dataset |
| may I change its weight? | decision time | StrategyModel | a registered dataset |
| **did this order actually fill?** | **execution time** | execution | the venue's fill table |

The third is evaluated at a **different instant** from the other two. A name can halt between the
decision and the fill. That is not a defect — it is why decision and execution are separate — and
the mismatch is recorded as unfilled quantity with a reason.

## The investment universe belongs to the strategy

Narrowing the research population is an economic judgement, not a market fact, so the StrategyModel
owns it. It can be computed at every decision, or precomputed (top 100 by liquidity, say) and
stored as an ordinary registered dataset.

**The user does not have to build one.** Without it, orders are generated for names that cannot
trade and are recorded unfilled with a reason. That is a normal result — the strategy did not know
and the market said so. vqapr neither requires a universe nor invents one.

## Deriving halts when there is no halt history

Most projects do not have a halt history. The package does not guess; the user declares a
derivation rule, you explain the candidates and their risks, and the chosen rule is recorded in
the frozen input and in the result's limitations.

| rule | risk |
|---|---|
| an explicit halt history | none — if it exists, use it |
| turnover or volume is zero | cannot distinguish a halt from a thin day |
| high, low and close are all equal | approximates a limit-price day; false positives on illiquid names |
| **no observation row at all** | **collapses halt, collection gap, pre-listing and truncation into one** — highest risk |

Offer the last one too. It is the only route a user with nothing else actually reaches, so
forbidding it just gets it done silently; declared, it is reproducible and auditable, which is the
opposite of a quiet assumption.

The profiler's per-name coverage is the evidence for this conversation: it reports which names
start late and which end early, so an unbalanced panel is visible before anyone reasons about it.

## "Unknown" is not a value

Tradability is two-valued. There is no third "unknown" state, and it does not differ by direction —
a name that can be sold but not bought is out of current scope.

If there is no observation at all for a name and instant, that is a **coverage** problem, not a
value problem, and the operation that required it fails before computing. The package does not read
a missing observation as tradable or as non-tradable. Which way to treat it is an economic
judgement: the user fills the data or excludes the name explicitly.

## Related

- [point-in-time.md](point-in-time.md) — when a membership fact became knowable is its own question
