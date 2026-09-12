# 035 — A cost band names a category

## Why this exists

A `CostRule` matched on side alone, so **every instrument on a venue paid the same rate**. That is
wrong on the only real venue this package ships. KRX charges a securities transaction tax on share
sales and **exempts ETFs**, and the research being reproduced declares exactly that split:

```yaml
stock:  buy_bps: 3.0   sell_bps: 23.0
etf:    buy_bps: 3.0   sell_bps: 3.0
```

An enhanced-index fund holds an ETF sleeve precisely so it can track the index cheaply. With a
side-only band the sleeve was charged 23bp instead of 3bp on every sale — **0.20 to 0.40 percentage
points a year** at 1x to 2x sleeve turnover, against a reported net excess of **+1.47%**. The error
was 14–27% of the number being reproduced, so the fund could not be expressed, let alone measured.
The workaround was to hold the sleeve as idle cash, which is worse: it costs the sleeve's entire
market return (measured at −4.30%/yr in the reproduction).

Canon 6.2 had already decided this and the code had not implemented it:

> **CostRule — 종목이 아니라 종류에 건다.** 비용 정책의 선택자는 `(kind, side, 적용 기간)`이다.
> 3,000종목을 거래해도 주식 규칙 하나와 ETF 규칙 하나면 된다.

The `kind` that selector needs lives on `Instrument`, and **`Instrument` had never been built**.
`docs/issues/archive/003` proposed hanging a `costs` tuple off `ListingRule` instead. That would have
worked for one sleeve and been wrong in the same way the original code was: it puts a rate on a
ticker, so a tax change edits three thousand lines, and it contradicts canon 2.8's placement of
`kind` as a venue-independent fact. The missing type, not the missing field, was the defect.

## What changed

**`domain/instruments.py` is new.** `InstrumentKind` is a closed discriminator and each category is
its own class:

```python
class Instrument:            instrument_id; kind: ClassVar[InstrumentKind]
class StockInstrument:       kind = STOCK
class EtfInstrument:         kind = ETF
```

It carries **no `exchange_id`** — the same instrument lists on many venues under different quantity
rules, and stamping a venue here would force it to be re-declared per venue (canon 6.2).

**`CostRule` gained `kinds: frozenset[InstrumentKind]`.** Empty means venue-wide. Ambiguity is
blocked in two layers, and both are load-bearing:

```text
declaration   validate_cost_declaration refuses overlapping (kind, side, window) bands,
              so a contradictory venue cannot be constructed at all
resolution    select_cost_rule still requires exactly one match, so a gap in the
              declaration fails loudly instead of charging zero
```

An empty `kinds` is deliberately **not a fallback**. Declaring a venue-wide band *and* a category
band on the same side is an overlap and is refused, because a silent precedence rule is exactly how
a sleeve ends up paying the wrong rate with nobody noticing.

**`ExchangeRulesView` joins the two declarations** by `instrument_id`: `listings` says how this
venue trades a ticker, `instruments` says what that ticker is. If any band names a category, every
listing must have a declared instrument — enforced when the view is built, not on the one fill
whose instrument happened to be missing.

**`krx_cost_rules_by_kind()`** declares the four real bands. `krx_cost_rules()` is unchanged and
still venue-wide, so every venue that exists today charges exactly what it charged.

**Both venues and `plan_orders` now name the instrument when they charge.** That last one matters
independently: planning reserves the cash a buy needs and releases what a sell yields, so pricing
a sale venue-wide there clips buys against money that was never going to leave the account.

### A second, latent bug fixed on the way

`ExchangeRulesView.at()` narrowed the band tuple but **discarded the instant**. A dated band that
survived the filter was still dated, so a later `charge()` without an explicit instant re-tested it
against `None`, matched zero, and raised. Order planning charges before a fill time exists, so
**a venue with effective-dated bands could not be planned at all**:

```
ValueError: exactly one CostRule must match side 'buy' at any instant; matched 0
```

`at()` now keeps the instant it bound and `charge()` falls back to it. This was never reported
because no shipped venue ships dated bands — the KRX tax rate has changed more than once, so the
first person to declare the real history would have hit it.

## Why this is the right place

**The selector is finite.** A venue trading three thousand names declares one stock band and one
ETF band. A tax change edits one line. Per-ticker rates would make canon's effective-dated bands a
time series *per instrument*, which is unmaintainable and is why canon refused it.

**The category is a domain fact, not a venue fact.** "삼성전자는 주식이다" does not change when the
venue changes; "주식 매도세는 20bp다" is KRX's rule. Canon 2.8's two axes put the first in `domain`
and the second in `exchange`, and this change is what makes that split real rather than aspirational.

**Nothing infers a category from a name.** Whether an instrument is tax-exempt is a declaration. An
id-prefix heuristic would put a jurisdiction rule inside the matching engine.

## Designed for the categories that are coming

> **Superseded in part by record 036.** `Index` and `Factor` landed there, completing the four
> categories `UC-ACADEMIC-001` names. **Crypto perpetuals are out of MVP scope** at the user's
> direction — funding, margin and inverse denomination are a larger problem than the categories
> that have near-term use. The seams below are unchanged and still describe how `FUTURE` arrives.

Two seams exist so a new category is additive rather than a rewrite:

**1. `kind` is a closed discriminator.** A new category is: add the enum member, add the class,
register it. Nothing existing is edited. Category-specific facts land on the category that has
them — `FUTURE` gets expiry and contract multiplier, `BOND` gets maturity and coupon.

**2. `notional`/`quantity_for` are declared on `Instrument` and routed through the venue.** Today
they are the identity `abs(qty) * price`, and every money-to-quantity conversion in the package —
`plan_orders`' weight-to-quantity step, its cash clipping, and both venues' fill construction —
already goes through them. A KOSPI 200 future has a 250,000 multiplier; without this seam that
factor would have to be threaded through order planning and each venue separately, and every one
of those sites is a place to get it wrong by five orders of magnitude.

Measured, by declaring a category that overrides exactly those two methods and nothing else — 1bn
KRW of NAV against an index at 350 points:

```text
multiplier-aware contracts   11
multiplier-blind would be    2,857,142        <- 259,740x too large
true notional                962,500,000      <- fits inside NAV
commission charged           28,875 = notional * 0.3bp
```

Order planning sized it and the venue charged it, neither having any knowledge of a multiplier.
The override site exists before it is needed, which is the cheap half of the work.

Costs scale the same way: a category's own rate is a band with `kinds={THAT_KIND}`, and a rate that
changes on a date is a dated band — `effective_from`/`effective_to` already exist.

**What is deliberately not built, and therefore not claimed.** Margin and collateral,
mark-to-market settlement, and expiry rollover. Whether a position consumes its full
notional or a margin deposit is an **account** fact — canon 2.8 puts negative cash under the
account type, not the venue — so a derivative category needs an `AccountMode` alongside its class.
Neither exists, and `domain/instruments.py` says so in its docstring rather than implying a
completeness it does not have. `Fill.notional` likewise stays `qty * price`: a `Fill` carries no
instrument reference, and inventing one to half-support a multiplier would be the speculative half.

The precise consequence, stated so nobody discovers it by surprise: for a multiplied contract the
**sizing and the charged cost are correct**, but `Fill.cash_delta` — `-(qty * price) - cost` —
would move cash as if the contract were unlevered. That is the account-side work, and a derivative
category is not usable end to end until it lands. Nothing in this change claims otherwise, and no
shipped category is multiplied.

## Trade-offs

**A venue-wide band and a category band cannot coexist on one side.** Declaring an ETF exemption
means declaring the stock band too — four bands where two would do. That is the price of refusing
an implicit precedence rule, and it is the right price: the alternative silently charges the wrong
rate.

**Declaring categories makes instrument declaration mandatory for that venue.** A venue using
`krx_cost_rules_by_kind()` must declare an `Instrument` for every listing or it will not build.
This is a real cost at the call site and is the point — the failure happens once, at construction,
instead of per fill.

## Validation

- `uv run pytest -q` — **618 passed**, including 9 new tests in
  `tests/exchange/test_instrument_cost_bands.py`.
- **Both fixes were proven to discriminate**, not merely to pass:
  - reverting the `at()` binding fails `test_an_effective_dated_venue_can_be_planned` with the
    original `matched 0` error, and restoring it passes 9/9;
  - the sleeve rotation plans **1213** shares under the category bands against **1211** venue-wide,
    on identical real prices — the exempt tax stays in the account and buys shares.
- Charged on real KRX closes: a 60-unit sale prices at `notional * 0.002` tax for the share
  category and **exactly zero** for the ETF, with identical commission, and the account's cash
  after `prepare_fill` equals `cash + notional - cost.total`.
- Every pre-existing venue is unmoved: `KrxExchange([...])` still charges 3bp/23bp venue-wide,
  `AcademicExchange` still charges zero, and both report no declared instruments.
- The extension seam was exercised, not just asserted: a category overriding `notional` and
  `quantity_for` sized 11 futures contracts where a multiplier-blind package sizes 2,857,142, and
  the venue charged commission on the true 962.5m notional.
- `uv run ruff check src tests` — clean.
- `tests/test_workspace_concurrency.py` flaked once on a Windows file lock and passes 3/3 on
  rerun; unrelated to this change.
