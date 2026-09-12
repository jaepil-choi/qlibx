# 155 — the affordability estimate reads the channel that bills, and leaves cash instead of refusing

**Closes:** `docs/issues/archive/078`. **Branch:** `fix/078-size-down-and-leave-cash`, off
`develop @ 71747774`. **Campaign:** none — this is spine-adjacent (`orders/planning.py`) and the
one-shape campaign explicitly does not touch it. **Authority:** the owner, 2026-09-05, for the
second half; the first half is a defect on its own.

## Why this exists

A real session (`kwam-enhanced-index/vqapr-enhanced-index-3`, three ensemble books on a costed
venue at `0.4.1`) could not place a large order. The venue was written the way `venue.py:66` says
a category-driven venue must be written:

> This is the channel a category-driven venue should use instead of baking a rate into each
> `TradeRule`. Baking it in means holding a second copy of a fact the project owns, and the two
> can then disagree (issue `013`).

So it declared `terms_by_kind` and left every `TradeRule`'s `buy`/`sell` at the default `SideCost`
— zero on both fields. `ExchangeRulesView.charge` honours `terms_by_kind`; `_affordable_quantity`
did not. It built its closed-form estimate from `rules.listing(id).cost(Side.BUY)`, which on such a
venue is those zeros, so the estimate was `available / price` — the guess record `083` replaced
because it "always overshoots by the charge on itself". The eight-lot correction then could not
close a gap that is a fraction of the whole order, and the run ended on

    affordable quantity for 'A005930' on 'krx' did not converge within 8 lots of the closed-form
    estimate; the venue's notional or cost is not monotone in quantity

which is `013` one layer up: there a fill said one category and was charged as another, here the
planner sizes on one rate while the fill charges another. The correct spelling was ten files away
and had always been there — `KrxExchange._affordable` reads `rules.charge(side, price, id).total /
price`.

The message was the worse half. It named a cause — non-monotone cost — that nothing in the
function had measured, which is the defect `077` closed one layer up in the judgment stage.

## What changed

`src/vqapr/orders/planning.py`, one function and one new helper.

- **`_gross_rate(rules, instrument_id, notional)`** reads `ExchangeRulesView.charge`, the member
  that honours `terms_by_kind`, and returns `1 + charge/notional`. `_affordable_quantity` probes it
  with `available` itself, so the rate is measured at the order's own order of magnitude.
- **The correction re-solves instead of stepping one lot.** Each attempt scales the notional by
  `available / required` — what the venue just billed — and quantises. For a rate on notional that
  lands in one attempt; for anything monotone it descends geometrically. The one-lot step survives
  only as the floor's fixed point, so the descent stays strict.
- **It does not refuse.** Owner ruling, 2026-09-05: leaving cash is fine, a real fund runs with
  cash on hand. When no payable size is found the function returns zero, the caller keeps the
  existing position, and the cash stays in the account — the same answer it already gave when one
  lot costs more than the cash on hand. The batch still carries a `ZeroDeltaDiagnostic` for the
  name, so the untraded instrument is evidence rather than a silence.

`MAX_AFFORDABILITY_STEPS` keeps its value of 8 and changes meaning: corrective *attempts*, not
corrective lots.

## What did not change

`_settle_payable`'s walk and its two refusals are untouched. That one shaves whole lots to absorb a
last-digit `Decimal` disagreement between the planner's sum and the account's, and its exhaustion
is a genuine "planning and the account disagree by more than rounding" — a different fact from
"this order does not fit in the cash", and not what the ruling was about.

`listing(id).cost(side)` has no other reader outside `exchange/`, so this was the only site.

## Validation

- `uv run pytest tests/orders/ -q` — 18 passed.
- `uv run pytest tests/ -q -m ""` — **1,440 passed** in 798s, the full suite including the thirteen
  slow journeys and the eight showcase gates. The baseline was 1,439 (fast 1,417 + 22 deselected);
  the one added test is the second of the two below, which replaces a single test with two.
- `uv run ruff check src/` — clean.

Two tests carry the change, both in `tests/orders/test_planning.py`:

- `test_a_category_driven_venue_sizes_a_large_buy_from_the_channel_that_bills` builds a venue with
  `terms_by_kind` and untouched zero listing costs, and plans a full-cash buy. It asserts the
  planned quantity is payable, that no whole affordable lot was left unspent, and that the quantity
  is strictly below `cash / price` — the number sizing on the listing's zeros would have produced.
- `test_a_venue_whose_cost_never_shrinks_leaves_the_cash_rather_than_refusing` replaces
  `test_a_venue_whose_cost_outruns_the_lot_is_refused_rather_than_searched`. That test's premise is
  gone twice over: its `Runaway` venue charged 1000x what it quoted, which is exactly the
  disagreement this record removes by reading the charge, and the ruling says an unpayable venue
  leaves cash rather than refusing. The replacement bills a flat fee larger than the account, so no
  size is payable, and asserts a zero delta plus the diagnostic that records it.
