# 005 — Affordability is searched one lot at a time

**Status:** closed 2026-08-21 by `docs/implementations/043-affordability-is-solved-not-searched.md`.
Found 2026-08-21 reproducing an enhanced-index fund on a fractional venue, where it stopped a
2,095-session run from finishing at all.
**Touches:** `src/vqapr/orders/planning.py`

> **Resolved as proposed.** `_affordable_quantity` divides by `(1 + commission_rate + tax_rate)`
> and converts back through `rules.quantity_for`, keeping the multiplier seam. The bounded
> correction is `MAX_AFFORDABILITY_STEPS = 8` and **raises** past it, so it cannot decay back into
> the walk. 82.09s -> 0.05s on `tests/orders/`; every planned quantity, NAV, fill count and
> artifact digest unchanged, including the 1,213-vs-1,211 exempt-sleeve assertion.
>
> Worth keeping from the diagnosis: record 041 profiled this exact loop and cleared it, because it
> measured on a **whole-share** venue where `step = 1` bounds the walk at 55 iterations. A
> hot-path measurement inherits the declarations of the venue it was taken on.

## What happens

When rounded buys cost more than the cash available, `_apply_venue_rules` clips them. The clip is
a linear search that walks down one `quantity_step` per iteration:

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

The first guess is `available / price`, which ignores the commission, so it always overshoots by
the charge on itself. The loop then removes that overshoot one lot at a time. The iteration count
is therefore `affordable x rate / step` — proportional to the *cash* being spent and inversely
proportional to the *unit size*:

| leftover cash | `step = 1e-6` (fractional) | `step = 1` (whole shares) |
|---|---|---|
| ₩1,000,000 | 5,522 | 0 |
| ₩100,000,000 | 552,262 | 0 |
| ₩1,000,000,000 | 5,522,625 | 5 |
| ₩10,000,000,000 | **55,226,256** | 55 |

at a 3bp commission and a ₩54,322 price. Each iteration runs three `Decimal` multiplications, a
`quantize`, and a `charge`, so 55 million of them is minutes for **one instrument on one
session** — and the loop can be entered by every instrument in the batch.

A whole-share venue hides this: `step = 1` bounds the walk at `affordable x rate`, which is 55
iterations rather than 55 million. Both shipped KRX profiles trade whole shares, so nothing in
the test suite or the showcases exercises the case that hurts. A fractional venue — an academic
profile, which is what alpha research uses, where a weight is a research statement rather than a
lot a broker fills — is where it bites.

## How it was found

A ₩100bn enhanced-index book on a fractional academic venue, targeting zero cash so that mass
clipped off the no-short floor is restored into the book rather than parked. Two sessions did not
complete in 15 minutes; a stack dump landed in `_apply_venue_rules` every time. The first session
alone is fine — the account holds nothing, buys are funded by the opening cash, and the clip is
never entered. It is the *second* callback, the first one that has to fund buys out of sell
proceeds, that hangs.

This is not the O(N²) identity hashing fixed in `d1a9a92`; it survives that fix, because it is
not proportional to run length. It is proportional to money.

## Shape of the fix

The quantity that exactly exhausts `available` has a closed form, because `SideCost.charge` is
linear in notional: `commission_rate` and `tax_rate` both multiply it. So

```
required(q) = notional(q) * (1 + commission_rate + tax_rate)
```

and the affordable quantity is `quantity_for(available / (1 + rate), price)`, quantized down.
One division replaces the walk, and the existing `while` becomes a bounded correction — one or
two iterations for the rounding, not millions.

Two details worth deciding deliberately:

- **`notional` is routed through the instrument** so a category whose contract is not one unit of
  the quoted price — a future with a multiplier — can override it. The closed form should be
  expressed through `quantity_for` rather than by dividing by `price` directly, so a multiplier
  keeps working.
- **Keep a bounded loop after the division.** `quantize` floors, and a venue could in principle
  make `notional` non-linear. A closed-form guess followed by *at most a few* corrective steps is
  both fast and still correct if an instrument does something unusual; a hard-coded iteration cap
  that raises rather than silently returning a wrong quantity would say so.

## What not to do

Do not make the caller avoid the loop by leaving a cash buffer. That is real drag — 10bp of NAV
held idle against a reported net excess of 1.47% is 7% of the number being measured — and it
makes a framework performance defect into a research parameter. The planner is the right place
to know that a commission is linear.
