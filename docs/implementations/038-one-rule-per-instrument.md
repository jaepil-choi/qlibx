# 038 — One rule per instrument

## Why this exists

`ListingRule` and `CostRule` were two types answering one question. The user asked why, and the
honest answer was that **only one thing separated them, and nothing used it.**

Canon separated the venue's facts by how fast each changes:

```text
안 변함     ListingRule     수량 단위, 허용 방향
기간별      CostRule        요율          ← the entire basis for the split
매 시점     체결 테이블      거래 가능 여부, 가격
```

Take away period-dependent rates and both types sit on the same row, at which point they are one
fact wearing two names. And nothing ever declared a dated rate:

- `effective_from` / `effective_to` appeared **only inside `costs.py` and the tests of `costs.py`**.
- Both shipped KRX declarations were flat.
- The dated path was in fact **broken**: record 035 found that a venue with dated bands could not
  be planned at all, because `at()` narrowed the tuple and discarded the instant. Nobody had
  noticed, because nobody had one.

The user's other observation lands the same way: `minimum_quantity` and `fractional_allowed` are
"may this trade" facts every bit as much as a rate is a "what does it cost" fact. A venue that
lists an instrument knows both, at the same time, and they never change independently.

## What changed

**`ListingRule` + `CostRule` become `TradeRule`** — everything one venue will do with one
instrument:

```python
TradeRule(instrument_id, quantity_step, minimum_quantity, fractional_allowed,
          access=ListingAccess.LONG_ONLY, buy=SideCost(...), sell=SideCost(...))
```

`SideCost` is a commission rate and a tax rate. Declaring cost as a **pair of sides** rather than a
selector is the shape the research itself uses:

```yaml
stock:  buy_bps: 3.0   sell_bps: 23.0
etf:    buy_bps: 3.0   sell_bps: 3.0
```

**The matching engine is deleted.** A rate is now a dictionary lookup on `instrument_id`, so
"matched 0" and "matched 2" are not failure modes that can occur — the guard against them is
unnecessary because the situation is unconstructible. Gone with it:

```text
CostRule  select_cost_rule  charge_fill  effective_rules  validate_cost_declaration
declared_kinds  effective_at  always_effective  venue_wide  applies_to  overlaps
_windows_intersect  ExchangeRulesView.at()  ExchangeRulesView.costs
```

`costs.py` went from **271 lines to 96**. `ExchangeRulesView` lost a constructor argument and a
whole binding concept: `charge(side, notional, instrument_id)`, no instant, no narrowing.

**`TradeTerms` + `trade_rules_by_kind()`** declare one set of terms per category and expand it, so
a 200-name K200 venue writes two declarations. `krx_rules({"A005930": "stock", "A069500": "etf"})`
returns both the rules and the instruments, and is the one call that gets the ETF exemption right.

## What was given up, stated plainly

**Effective-dated rates are gone, and that is a real loss.** The KRX securities transaction tax has
changed more than once, and a 2018–2026 backtest crosses those changes; it now runs at one flat
rate. Three things make that the right trade today:

1. Nothing declared one, so no result moves.
2. The feature did not work, so no result *could* have moved.
3. The research being reproduced also uses a flat 23bp, so the reproduction stays comparable.

**It can come back without undoing this.** Dating belongs *above* a flat rule, not underneath every
charge: a venue expands a different `TradeRule` set for a different period. That is a change to how
a roster is built, not a matcher re-entering the fill path.

## Trade-offs

**A cost now travels with the rule, so reusing a rule inherits its rates.** `AcademicExchange`
built from `krx_listing(...)` is no longer free — it is KRX's rule, and KRX's rule costs what KRX
costs. This is the correct reading (cost is a property of what the venue will do, not of which
profile class holds it) but it is a genuine behaviour change, and the test that asserted the old
reading was rewritten to assert both halves explicitly.

**`TradeRule` has seven fields where two types had four and six.** A caller that only cares about
quantity still carries the cost fields. That is the cost of one fact in one place, and it is
cheaper than two types whose join had to be maintained.

## Validation

- `uv run pytest -q` — **624 passed**; `uv run ruff check src tests` clean.
- The ETF exemption, which motivated all of this, is unchanged end to end:
  `stock sell tax 12000.000` against `etf sell tax 0` on identical notional.
- `krx_rules` builds 2 categories into a full roster; a category with no terms is simply not
  listed, verified with a factor against `KRX_TERMS`.
- Deleted-machinery tests were replaced rather than dropped: the guarantee is now *"a listed
  instrument has exactly one rate per side"*, plus an unlisted instrument raising rather than
  charging zero.
