# 003 — A cost band cannot name an instrument

**Status:** open. Found 2026-08-20 reproducing an enhanced-index fund that holds an index ETF
alongside its direct stock book.
**Touches:** `src/vqapr/exchange/costs.py`, `src/vqapr/exchange/listings.py`,
`src/vqapr/exchange/venue.py`, `src/vqapr/exchange/venues/krx.py`

## What is missing

A venue charges one band per side, for every instrument it lists:

```python
CostRule  fields: rule_id, side, commission_rate, tax_rate, effective_from, effective_to
ExchangeRulesView.charge(self, side, notional, at)      # no instrument
ListingRule  fields: instrument_id, quantity_step, minimum_quantity,
                     fractional_allowed, permitted_sides      # no cost
```

`ListingRule` is where per-instrument venue facts already live, and it carries no cost. Both
shipped profiles call `rules.charge(side, notional, ...)` without saying *what* was traded, so
two instruments on one venue cannot be charged differently.

## Why it matters

This is not hypothetical. KRX charges a securities transaction tax on stock sales and **exempts
ETFs**. The research being reproduced declares exactly that:

```yaml
stock:  buy_bps: 3.0   sell_bps: 23.0
etf:    buy_bps: 3.0   sell_bps: 3.0
```

Its cost model is built around the split — `AsymmetricCostContract` carries four rates and
`evaluate_netted_orders` takes `stock_target` and `etf_target` as separate arguments.

An enhanced-index fund holds an ETF sleeve precisely so it can track the index cheaply. Charging
its sleeve trades 23bp instead of 3bp overstates cost by 20bp of ETF turnover — **0.20 to 0.40
percentage points a year** at 1x to 2x sleeve turnover. The report's whole net excess is +1.47%,
so the error is 14–27% of the number being reproduced. A framework that cannot express the
exemption cannot reproduce the fund.

The current workaround is to not hold the ETF at all and treat the sleeve as cash, which is worse:
it costs the sleeve's entire market return.

## Shape of the fix

`ListingRule` is the natural home — it is already the per-instrument venue declaration, and a cost
band is a venue fact about an instrument in the same way a quantity step is.

```
ListingRule(..., costs: tuple[CostRule, ...] = ())     # empty means "use the venue band"
ExchangeRulesView.charge(side, notional, at, instrument=None)
```

Resolution order: the instrument's own band if it declares one, otherwise the venue's. That keeps
every existing venue and result unchanged — nothing declares a per-listing band today — and lets a
profile say "this ETF is exempt" without inventing a second venue.

Two details worth deciding deliberately:

- **A per-listing band should be additive, not a full override**, or a listing that declares only
  a tax rate silently loses its commission. Simplest honest rule: a listing's band replaces the
  venue's entirely, and the docstring says so.
- **`effective_from` / `effective_to` already exist on `CostRule`**, so a per-listing band inherits
  dated bands for free. The KRX tax rate has changed more than once; an ETF exemption that started
  on a date is expressible without new machinery.

## What not to do

Do not special-case an instrument id prefix, or infer "this is an ETF" from a name. Whether an
instrument is tax-exempt is a venue declaration, not a naming convention, and inferring it would
put a jurisdiction rule inside the matching engine.
