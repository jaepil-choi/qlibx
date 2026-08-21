# 036 — Four categories, and one place tradability lives

## Why this exists

Record 035 built `InstrumentKind` with two members because the ETF sale-tax exemption needed
exactly two. `UC-ACADEMIC-001` has always required four, and they are the two an academic study
actually uses:

> 선택한 academic venue는 **Stock, ETF, tracking-only Index, synthetic-unit-price Factor**의
> listing과 instrument별 fractional/lot 규칙을 판정한다.

A factor study builds a book out of factors the way an equity study builds one out of shares. A
benchmark index is what every relative number in the enhanced-index work is measured against.

**Crypto perpetuals are out of MVP scope** at the user's direction; funding, margin and inverse
denomination are a larger problem than the categories with near-term use. Record 035's roadmap
section is annotated accordingly.

## The mistake this record corrects

The first draft of this work put `tradable: ClassVar[bool]` on `Instrument` and set it `False` on
`IndexInstrument`. That is wrong, and canon 6.2 says so in one line:

> **거래 가능 여부를 넣지 않는 이유** | `permitted_sides`가 이미 표현한다. **같은 사실을 두 곳에
> 두지 않는다**

Two independent reasons, and the second is the one that actually bites:

1. **It duplicates a fact.** `permitted_sides` already answers "may this be traded here".
2. **The answer is not a property of the instrument.** Canon 2.8's test is *"venue를 바꾸면
   달라지는가?"*, and tradability plainly does. The draft's own `FactorInstrument` proved it:
   marked globally tradable, yet a factor is not tradable on KRX at all. One instrument, two
   venues, two answers — so the fact belongs to the venue.

The draft also refused a cost band naming `INDEX`, on the reasoning that an index never fills.
That reasoning does not survive either: whether a venue fills an index product is the venue's
business, and a venue that lists one would need exactly that band.

## What changed

**Two categories added, and nothing about trading on any of them.**

```python
class IndexInstrument(Instrument):   kind = INDEX     # referenced rather than held
class FactorInstrument(Instrument):  kind = FACTOR    # held against a synthetic unit price
```

**Tradability is expressed once, by the venue.** `ListingRule.permitted_sides` may now be empty,
and an empty set is a venue saying *listed, never fillable* — it publishes and quotes the
instrument but will not trade it. `ListingRule.tradable` reads that set; `ExchangeRulesView.
tradable(id)` is the lookup consumers use.

Three layers now answer three different questions, and none of them repeats another:

| question | where | example answer |
|---|---|---|
| what is this thing? | `Instrument.kind` | an index |
| will this venue ever fill it? | `ListingRule.permitted_sides` | no side permitted |
| can it be filled right now? | execution table | halted today → typed `NONTRADABLE` |

**Order planning refuses a target on an untradable listing** where the instruction is still
visible, rather than letting the venue refuse the whole batch with a message about a side.
Preflight reports it under its own code, `preflight.universe.untradable_listing`, separately from
`unlisted_instrument` — a published benchmark in the traded universe is not a missing registration,
and saying so would invite registering a listing that already exists.

## Why an index is still an instrument

The doubt is fair: an index level is data, canon 4.1 registers it as an ordinary series under a
synthetic id, and nothing holds it. Two things make the category earn its place anyway.

**A portfolio system must name things it does not hold.** A benchmark is compared against; a
derivative's underlying is referenced by its contract. Naming it is what lets a venue state a
judgement about it at all — including "I publish this and will not fill it".

**Priceable and fillable are different properties, and the package needs both.** An index level is
a perfectly good price; there is simply no venue that will give you that price for a quantity. The
KTB 3-year futures basket is the cleanest illustration: the standardised 3-year bond is *priced*
and never *held*, the future written on it is fully tradable, and the deliverable bonds are
separately tradable. One economic object, three different answers — and none of them is settled by
asking whether the price is synthetic.

**Synthetic is never a category axis here.** An ETF's NAV is computed from a basket, a KTB futures
settlement price is computed from a deliverable basket, an index level is computed from
constituents. Synthetic describes *how a price is formed*, not whether the thing can be filled, so
the package never branches on it.

## Trade-offs

**An empty `permitted_sides` is now legal.** The invariant loosened from "non-empty" to "a
frozenset of `Side`". Everything downstream already handled it correctly — `permits()` returns
`False`, both venues refuse the order, preflight refuses the holding — so no path had to learn a
new case. The cost is that a typo producing an empty set is no longer caught by the constructor;
it surfaces at preflight or at the first target instead.

**A cost band may name a kind the venue never fills.** That band is dead rather than wrong, and
refusing it would mean the category, not the venue, deciding what is tradable — the exact error
this record corrects. A shared declaration like `krx_cost_rules_by_kind()` legitimately names kinds
a given venue may not list.

## Validation

- `uv run pytest -q` — **627 passed**, `uv run ruff check src tests` clean.
- **Discriminating, not merely passing**: replacing `ListingRule.tradable` with a constant `True`
  fails **5 tests**; restoring it passes 15/15.
- One venue tradable, another not, same instrument — the assertion that the first draft could not
  have made:

  ```python
  academic.tradable("HML") is True
  research.tradable("HML") is False
  academic.instrument("HML") == research.instrument("HML")   # one instrument, two venues
  ```

- A four-category academic roster reports `{A005930: True, A069500: True, HML: True,
  KOSPI200: False}`, with `KOSPI200` fully listed and carrying its quantity unit.
- Categories carry no tradability at all: `hasattr(category("A"), "tradable")` is `False` for all
  four.
