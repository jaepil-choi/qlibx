# 081 — A category-driven rate has a channel to go through

Record `080` removed the venue's copy of the roster's categories for every venue this package
ships. What was left of issue `013` was the same defect available to anyone writing their own.

## The obvious repair was the wrong one

The issue proposed a `check` judgment comparing a venue's declared categories against the roster.
That cannot work, and the reason is worth stating rather than discovering later.

A per-instrument rate is **legitimate** when it is not standing in for a category. A venue may
charge one name more than another because of a genuine instrument-specific fee, and nothing on the
outside can tell that apart from a category schedule written out by hand. A judgment would have to
guess the author's intent, and it would be wrong in whichever direction it guessed.

So the defence is not a check. It is that the correct channel exists and is reachable.

## It existed and was not reachable

`ExchangeRulesView.terms_by_kind` — record `080`'s mechanism — was passed by `KrxExchange` and by
nothing else:

- `rules_view()`, the public helper, did not accept it.
- `AcademicExchange.rules` did not pass it, and that class is the documented base for a
  user-authored venue.

Meanwhile `AcademicExchange.rules`' own docstring promised the extension path: *"A subclass may
declare one. `execute` charges whatever this returns."* The only way to keep that promise was a
rate per `TradeRule` — which for a category-driven venue means holding a second copy of what the
roster declares. The package documented the path that produces the defect and hid the one that does
not.

## The channel

`rules_view(..., terms_by_kind=...)` accepts it, and `AcademicExchange` declares it as a
`ClassVar` that `rules` passes through. So a subclass writes:

```python
class MyVenue(AcademicExchange):
    terms_by_kind = {
        InstrumentKind.STOCK: TradeTerms(..., sell=SideCost(commission, tax)),
        InstrumentKind.ETF:   TradeTerms(..., sell=SideCost(commission)),
    }
```

and holds no category of its own.

A class attribute rather than a constructor parameter, because it is a property of the venue
**type**: what a venue charges an ETF is not something one instance decides differently from
another. The default is `None`, so the academic profile is unchanged and still answers without a
roster — it never asks a category, so it never needs one.

## Written where an author will read it

`SKILL.md` now states the choice and why it matters: a per-instrument fee goes on the listing, a
rate that follows the category goes in `terms_by_kind`, and expressing the second as the first
keeps a duplicate of the roster's answer that nothing will detect.

That sentence is the actual fix. The mechanism was two lines; the reason `013` stayed open after
`080` was that an author had no way to find it.

## Validation

```
uv run pytest tests/ -q -m ""    # 1333 passed, clean
uv run pytest tests/ -q          # 1319 passed, 14 deselected
uv run ruff check src/vqapr/ tests/ showcases/   # 15, compared entry by entry: none introduced
```

`tests/exchange/test_academic.py::test_a_subclass_prices_by_category_from_the_roster_and_not_from_its_own_copy`
drives a user-authored subclass under two different rosters and asserts the charge follows the
roster both times — the same venue, the same ids, the categories swapped. It sits beside
`_CostedAcademic`, which prices per instrument and is left exactly as it was, because that is the
legitimate case the new channel must not crowd out. The base profile is asserted unchanged in the
same test: no `terms_by_kind`, no registry, still free.
