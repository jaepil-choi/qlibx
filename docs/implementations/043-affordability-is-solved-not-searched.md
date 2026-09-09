# 043 — Affordability is solved, not searched

Closes `docs/issues/archive/005-affordability-is-searched-one-lot-at-a-time.md`.

## Why this exists

A ₩100bn enhanced-index book on a **fractional** academic venue could not complete two sessions in
fifteen minutes. Repeated stack dumps landed in the same frame every time:

```text
File "vqapr/orders/planning.py", line 112 in _apply_venue_rules
File "vqapr/orders/planning.py", line 190 in plan_orders
File "vqapr/flow/simulation.py", line 824 in <lambda>
```

When rounded buys cost more than the cash on hand, `_apply_venue_rules` clips them. The clip
guessed `available / price` and then walked the overshoot off one lot at a time:

```python
affordable = rules.quantize(instrument_id, rules.quantity_for(instrument_id, available, price))
while affordable > 0:
    notional = rules.notional(instrument_id, affordable, price)
    required = notional + rules.charge(Side.BUY, notional, instrument_id).total
    if required <= available:
        break
    affordable = rules.quantize(
        instrument_id, affordable - rules.listing(instrument_id).quantity_step
    )
```

The guess ignores the commission, so it *always* overshoots by the charge on itself. The walk is
therefore `affordable × rate / step` iterations — proportional to the money being spent and
inversely proportional to the lot:

| leftover cash | `step = 1` (shares) | `step = 1e-6` (fractional) |
|---|---|---|
| ₩1,000,000 | 0 | 5,522 |
| ₩100,000,000 | 0 | 552,262 |
| ₩1,000,000,000 | 5 | 5,522,625 |
| ₩10,000,000,000 | 55 | **55,226,256** |

at 3bp and a ₩54,322 price.

## Why record 041 measured this loop and cleared it

041 profiled the same code and reported:

> The worst path was checked too: with cash short enough to clip 149 of 3,000 buys, the
> step-decrement loop still ran in 0.022s.

That measurement was correct and its conclusion did not generalise, because it was taken on a
**whole-share** venue. Both shipped KRX profiles trade in whole units, and `step = 1` bounds the
walk at `affordable × rate` — 55 iterations, not 55 million. The blow-up needs a fine lot, and the
only profile that declares one is an academic venue, which is exactly what alpha research uses:
an alpha's weights are a research statement, not a lot a broker fills.

So the defect was invisible to every test, every showcase, and one deliberate worst-case
measurement. It is a reminder worth keeping: a hot-path measurement inherits the declarations of
the venue it was taken on, and "worst case" means worst over the *declarations* too, not only over
the data.

It is also not the O(N²) identity hashing fixed in `d1a9a92`. That one scales with run length;
this one scales with money, and survived it untouched.

## What changed

`_affordable_quantity` solves for the quantity instead of searching for it. A cost band is a rate
on notional — `SideCost` carries `commission_rate` and `tax_rate`, both multiplying it — so

```
required(q) = notional(q) × (1 + commission_rate + tax_rate)
```

and the affordable notional is `available / (1 + rate)`. The conversion back into a quantity goes
through `rules.quantity_for`, not through a bare division by price, so a category whose contract is
not one unit of the quoted price — a future with a multiplier — keeps sizing correctly.

`MAX_AFFORDABILITY_STEPS = 8` corrective lots remain after the closed form, because `quantize`
floors and a venue may define `notional` however it likes. Past that the planner **raises**. That
boundary is deliberate: a bounded correction can never silently decay back into the unbounded walk
it replaced, and a venue whose cost is not monotone in quantity is a declaration error that should
say so rather than hang.

## Trade-offs

- **The refusal is reachable only by a venue that overcharges what it declares.** A profile whose
  `charge` disagrees with its own `TradeRule` rates hits it. That is the intended reading: the
  planner reserves cash from the declared band, and a venue that then charges more has broken the
  contract that makes planning payable at all.
- **The rate is read from the listing, not from a trial charge.** Reading it means the closed form
  is exact for every shipped band and approximate for a hypothetical non-linear one, which the
  bounded correction then fixes. Calling `charge` twice to infer a rate would be exact for linear
  bands too and would still need the correction, at the cost of pretending the rate is unknowable.

## Verification

```text
uv run pytest -q                      648 passed (2 new)
uv run pytest tests/orders/           13 passed in 0.05s   (was 82.09s)
showcases/show_005_enhanced_index     final NAV 1168064370.53, dealt fills 62,
                                      commission 225672.87, tax 269156.60, artifacts identical
```

`tests/exchange/test_instrument_cost_bands.py::test_the_exempt_sleeve_funds_more_of_the_buy_it_pays_for`
is the strongest check that nothing moved: it asserts the clip produces exactly 1,213 shares on an
exempt sleeve against 1,211 priced venue-wide, and both numbers are unchanged.

Two tests were added to `tests/orders/test_planning.py`:

- `test_an_unaffordable_buy_is_clipped_by_arithmetic_not_by_walking_lots` plans the same ₩10bn book
  on lots spanning six orders of magnitude and asserts each is payable, leaves under one lot
  unspent, and does not shrink as the lot gets finer. Behaviour, not a timing — a timing assertion
  would be flaky and would not say what went wrong.
- `test_a_venue_whose_cost_outruns_the_lot_is_refused_rather_than_searched` pins the refusal.

Measured on the reproduction's own venue, ₩10bn of leftover cash:

```text
step 1          0.0001s
step 0.001      0.0000s
step 0.000001   0.0000s      <- did not complete before
```

all three returning the identical quantity.
