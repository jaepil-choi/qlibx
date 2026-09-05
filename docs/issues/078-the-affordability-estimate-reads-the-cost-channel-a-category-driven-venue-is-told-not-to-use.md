# 078 — the affordability estimate reads the cost channel a category-driven venue is told not to use, and then blames the venue for it

**Status:** **OPEN -- second half ruled 2026-09-05 by owner: the walk does not refuse.**
Leaving cash is fine; a real fund runs with cash on hand. When the closed-form estimate and the
charge that bills do not meet, the planner sizes down and keeps the remainder as cash instead of
raising `did not converge`. A refusal is the wrong answer to arithmetic that cannot land exactly:
the order that can be paid for is the order to place. **The first half stands as filed and is the
heavier one** -- the estimate must read `rules.charge`, the channel that bills, which is the `013`
recurrence. Whatever message survives must still not assert monotonicity.

**Status when filed:** OPEN. Found 2026-09-04 by `kwam-enhanced-index/vqapr-enhanced-index-3` (C4), running
three ensemble books on a hand-written `AcademicExchange` subclass at `0.4.1`. Reproduced here
against this branch, twice, on both a fractional and a whole-share listing. The reporter diagnosed
the tolerance (true, and the second half of this file); the cause underneath it is that
`_affordable_quantity` and `KrxExchange._affordable` compute the same number from two different
sources, and only one of them is the source that bills.

**Touches:** `src/vqapr/orders/planning.py:88-104` (`_affordable_quantity`, which reads
`rules.listing(id).cost(side)`), against `src/vqapr/exchange/venues/krx.py:452`
(`KrxExchange._affordable`, which reads `rules.charge(side, price, id).total / price` — the correct
spelling, ten files away); `src/vqapr/exchange/venue.py:66-79` (`terms_by_kind`, the channel this
defect punishes); `src/vqapr/orders/planning.py:47` (`MAX_AFFORDABILITY_STEPS`).

## What happens

A venue whose rate depends on the category declares `terms_by_kind` and leaves each `TradeRule`'s
`buy`/`sell` alone. That is not a style choice — `venue.py:66` states it as the rule:

> This is the channel a category-driven venue should use instead of baking a rate into each
> `TradeRule`. Baking it in means holding a second copy of a fact the project owns, and the two
> can then disagree (issue `013`).

`ExchangeRulesView.charge` honours it: with `terms_by_kind` set, the rate comes from the roster's
category. `_affordable_quantity` does not. It builds its closed-form estimate from

```python
cost = rules.listing(instrument_id).cost(Side.BUY)
rate = Decimal(1) + cost.commission_rate + cost.tax_rate
```

which on such a venue is the **default `SideCost`, zero on both fields**. The estimate is therefore
`available / price` — the very guess the record `083` docstring says was replaced because it
"always overshoots by the charge on itself". The loop that follows corrects at most
`MAX_AFFORDABILITY_STEPS = 8` quantity steps, and the overshoot is a fraction of the whole order,
not eight lots of it. The planner then refuses:

```
[simulation.due.order_planning.ValueError]
observed: affordable quantity for 'A006650' on 'academic' did not converge within 8 lots of the
          closed-form estimate; the venue's notional or cost is not monotone in quantity
```

Reproduced on this branch, a venue declaring `terms_by_kind` with a 0.0003 buy commission and
listings carrying no cost of their own:

```
listing.buy (what the planner reads): SideCost(commission_rate=0, tax_rate=0)
charge on 1e10 (what actually bills):  FillCost(commission=3E+6, tax=0)

fractional, step 1e-6:  price 100000, cash 2e10  -> REFUSED
fractional, step 1e-6:  price   5000, cash 1e9   -> REFUSED
whole shares, step 1:   price 100000, cash 3.33e8 -> converged (3329)
whole shares, step 1:   price   5000, cash 3.33e8 -> REFUSED
whole shares, step 1:   price  50000, cash 2e9    -> REFUSED
```

**The reporter's workaround — whole shares — is not a fix, it is a coincidence.** It held because
their per-name budget divided by their price landed inside eight shares of the missing commission.
Row 4 above is the same venue at a cheaper price and refuses.

## Why the message is the worse half

It names a cause the framework never tested. `MAX_AFFORDABILITY_STEPS`' docstring reasons that a
venue needing more than eight corrective lots "is not merely non-linear but non-monotone", and the
refusal states that inference as fact. It is false here: this venue's cost is `q × price × rate`,
strictly monotone, and there is no way for it not to be. The reader is pointed at the one file that
is correct.

The reporter spent 15 minutes auditing their cost function before doubting the message. This is the
same failure shape as `079` and the one `077` closed: **where the framework does not know the
cause, a confident structured cause is worse than none.**

## Two defects, in order

1. **The estimate must read the channel that bills.** `KrxExchange._affordable` already does:
   `rules.charge(side, row.price, id).total / row.price`. One rule, one place — the campaign's own
   standing rule. This is `013` again, one layer up: `013` was a fill charging one category while
   recording another; this is the planner sizing on one rate while the fill charges another.
2. **The tolerance is in lots and does not scale.** Even with the estimate corrected, eight
   `quantity_step`s is 8e-6 of a share on a fractional venue and a meaningless tolerance next to a
   target millions of lots away. Express it as a relative error or a notional, and if a bounded
   walk stays, say the units in `observed`: *"tolerance is 8 × quantity_step = 8e-06; the estimate
   is 1.2e+06 lots from affordable"*.

Whatever replaces the message must not assert monotonicity. The honest statement is that the
estimate did not converge and what the two numbers were.

## Related

`013` (charge and record reading different sources — the same defect one layer down), record `081`
(the `terms_by_kind` channel), record `083` (the affordability solver this regressed from), `002`
(the missing rule `083` closed), `079` and `077` (a diagnosis stating an untested cause).
