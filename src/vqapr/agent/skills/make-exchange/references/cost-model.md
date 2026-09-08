# Declaring cost

## Two ways, and the choice is not cosmetic

**A per-instrument fee.** Each listing gets its own `buy` / `sell` `SideCost`. Right when the rate
genuinely belongs to that instrument.

**A rate that follows the category.** The class attribute `terms_by_kind` maps `InstrumentKind` to
`TradeTerms`, and the charge is resolved per fill from the registered roster.

## Do not express a category rate as per-instrument costs

It keeps a second copy of what the roster already declares, and the two can disagree: the fill
records the **roster's** category while the money follows **yours**.

Nothing detects this, because per-instrument rates are legitimate whenever they are not standing in
for a category. So the guard has to be the author's — if the rate is "what an ETF pays", declare it
by kind.

The same asymmetry runs the other way: a fill's `kind` is what the roster said, and what it was
**charged** as comes from the venue's terms. Those are two statements and nothing compares them, so
keep a venue's declared categories in step with the registered roster by hand.

## Buy and sell differ, and so do instrument kinds

Both sides need their own policy. On a Korean venue the shape is: equity SELL tax 15bp, ETF SELL
tax an explicit 0bp, and BUY policy different from SELL.

**Exactly one policy applies to each order**, chosen by instrument kind and direction, and the fill
preserves both the total cost and **the identity of the policy that was applied**. That identity is
what makes a cost number auditable later — without it, a total is a number nobody can reproduce.

## Effective dating

Cost policies can differ by period. Two economically identical orders in 2024 and 2025 pick up the
policy in force at each execution, not the latest one.

If the user's venue has a rate that changed, say when, and register both — silently applying
today's rate to a five-year backtest understates or overstates cost for most of it.

## Where cost is read back

**From `vqapr.fill`, summed** — commission and tax are per fill and per side, so a category's true
cost is a sum over that table, never a rate read off the venue. `trading.costs` in a
`StrategyReport` does that summation, including by roster kind.

If the roster was not registered, `kind` is null on every fill and cost by kind collapses to one
`unknown` bucket. The numbers are still right; the breakdown is gone.

## The academic case

Zero, explicitly, on all of it — and turnover recorded separately, so the quantity the cost would
have applied to is still there. That is what makes an academic run comparable with a costed one
rather than merely cheaper.
