# The two profiles, and what each one claims

## What a profile declares

Fill timing, tradability, direction, per-instrument quantity granularity, and cost capability —
each profile declares its own.

`AcademicExchange` and `KrxExchange` are the only two a registered Exchange may be. Your own venue
subclasses one of them.

## `academic` — free fills, and that is the point

Cost, tax, slippage, market impact and borrow cost are **explicitly zero**, and turnover is
recorded separately so the thing the costs would have bitten is still visible.

It is not a lesser simulation. It follows the **same order → fill → commit → valuation lifecycle**
as a physical profile: the frozen intended portfolio is settled first, then execution uses the
committed hypothetical account state and a point-in-time reference price. The account, the NAV and
the feedback are all real; only the friction is zero.

The scaffold names `buy=` / `sell=` `SideCost` as the fields it deliberately leaves out, so adding
cost later is filling in a blank rather than restructuring.

A rebalance is refused **whole, before any mutation**, if any of these is missing: a listing, an
exact-time price, positive NAV, a compatible signed state transition, or a supported quantity rule.

Its results are marked `hypothetical`. They must not be reported as broker-confirmed production
state, or as evidence of borrow, locate, collateral, margin, or an executable real short.

## `krx` — costed, and long-only

Built from `krx_rules`, which gets the ETF sale-tax exemption right: a share pays the sale tax and
an ETF does not. That distinction is the reason to use the builder rather than typing rates.

Every listing gets `access=ListingAccess.LONG_ONLY`. See
[access-and-account.md](access-and-account.md) before pairing it with an account.

**A venue names no categories at all.** `KrxExchange` takes instrument ids; what each one *is*
comes from the registered roster at fill time. No strategy run starts without a roster
(`roster.absent`), and an order for an id the roster never described fails the run
(`instrument.undeclared`) rather than charging it as a share — the roster names what is ordered,
not the whole execution table.

## The name is not the claim

*"KRX"* does not mean the exchange is reproduced. Only the rules actually implemented and the
limitations actually stated are claimed, and the result records them.

When reporting to a user, say what the profile did: which rules applied, what was zero, and what
was not modelled. A realism claim that comes from the label rather than from the record is the
thing this section exists to prevent.

## Comparing profiles

Running the same frozen intended portfolio through two compatible profiles is supported, and it is
how the cost of realism is measured. Each run records its own semantics independently, and
**daily-physical and academic semantics never mix inside one result.**
