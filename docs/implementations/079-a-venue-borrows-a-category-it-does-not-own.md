# 079 — A venue borrows a category, it does not own one

`docs/issues/archive/013` filed a defect: a fill could record `kind: stock` while the tax charged followed
the venue's own `etf`. It offered three defensible repairs and asked which statement should win.

The question that collapsed them was shorter than any of the three: **why does a venue have a
universe at all?**

## The design already said so

`KrxExchange.__init__`'s own docstring, written when issue 008 moved identity to the project:

> **It no longer accepts `instruments`.** What an id IS belongs to the project, not to a venue:
> `kind` does not vary by venue, so a venue declaring it was declaring a fact that was never its
> own (issue 008). […] The bare-sequence form is consequently no longer a bypass. […] Now it says
> only "these are the ids I trade", the categories come from the roster.

That last sentence was false. `KrxExchange(["A005930", "A069500"])` built every listing from the
**stock** terms, and `charge` read the listing — so an ETF paid a sale tax KRX exempts, on a venue
whose docstring said the categories came from the roster.

`ExchangeRulesView.stamped_kind` reads the registry and its docstring states the rule the charging
side was supposed to follow:

> Keeping them apart is what lets a run with no roster still execute on a venue that charges one
> flat rate, while a venue whose rate depends on the category still refuses.

Both promises were written down. Only the identity half was implemented.

## The roster is already there

The decisive measurement is that nothing had to be plumbed. `flow/simulation.py`'s
`_bind_registry_to_venue` binds the roster **onto the venue itself** — its docstring says why:
*"so every reader of its rules sees it"*, after handing a bound view to `plan_orders` alone proved
insufficient in a testbed journey.

So at the moment `charge` runs, on the same object, in the same call:

- `stamped_kind(id)` reads `self.registry` and gets the category right.
- `charge(side, notional, id)` read `self.listings` and got it from construction.

One object reading from two sources. Not two sources the design needed.

## What changed

`ExchangeRulesView` gains `terms_by_kind`. When present, `charge` resolves the category through
`_declared` — the same door `stamped_kind` uses — and picks the terms from there. When absent, the
listing's own `buy`/`sell` are charged, which is right for a venue whose rate does not vary.

`KrxExchange` passes `KRX_TERMS` and holds no category. `krx_listings(ids, *, price_limits)`
replaces `krx_rules` for building one: a rule still says how an instrument **trades** — whole
shares, a minimum of one, long-only, the limit band — and those are the venue's own facts,
identical across every category KRX lists. `KRX_TERMS`' two entries differ **only** in `buy`/`sell`,
which is measured, not assumed.

`krx_rules` remains for callers holding a `{id: kind}` mapping, with its docstring now stating that
the categories it takes no longer decide what a run charges.

## An unbound KRX venue refuses

This is the visible consequence, and it is the rule `stamped_kind` already stated: there is no
honest rate for an instrument nobody described, so charging one anyway is the silent default the
design exists to remove. A flat-rate venue still runs unbound, because it never asks.

Twelve tests failed on this. Every one of them was charging without a roster and receiving stock
terms by accident — including one named
`test_a_bare_universe_gets_stock_terms`, which pinned the defect while its own neighbouring comment
admitted *"which is how an ETF came to pay a share's sale tax"*. They now bind a roster, which is
what the Flow does at run assembly, and the assumption they were relying on is visible in the
fixture instead of hidden in the venue.

Two of them drew a contrast between "a venue that declares categories" and "a venue that does not".
That pair no longer exists. The contrast is now the same venue under two rosters, which is the
comparison that means something: what the sleeve **is** decides what its sale costs, and the venue
has no say in it.

## The scaffold names nothing

`vqapr new exchange --profile krx` emitted a `UNIVERSE` mapping with every id defaulting to
`"stock"`, and a docstring warning the author to keep it in step with the registered roster.

A scaffold that needs that warning is telling you the shape is wrong. Record `072` wrote the
warning and did not read it — it built `--profile krx` around `krx_rules`' existing signature
rather than asking why the signature wanted a universe.

It emits ids now. The KRX journey test asserts the emitted file contains none of the four category
names, and runs it **unedited** — the previous version had to flip the ETF's category by hand
before the exemption appeared.

## Validation

```
uv run pytest tests/ -q -m ""    # 1331 passed, clean
uv run pytest tests/ -q          # 1317 passed, 14 deselected
uv run ruff check src/vqapr/ tests/ showcases/   # 15, compared entry by entry against the
                                                 # committed tree: none introduced
```

- `tests/cli/test_krx_cost_journey.py` — the end-to-end journey now runs the scaffold's output with
  no edit at all, and asserts the emitted source names no category.
- `tests/exchange/test_instrument_cost_bands.py::test_an_unbound_krx_venue_refuses_to_charge_rather_than_assuming_a_share`
  — refuses on both `charge` and `kind`; bound to a roster calling the id a stock it charges the
  sale tax, and bound to one calling the same id an ETF it charges none. Same venue, same id.
- `::test_a_rosterless_run_is_refused_by_a_categorised_venue_and_served_by_a_flat_one` — both halves
  of the rule `stamped_kind` states, pinned together so neither can drift.

The refusal-code baseline gains codes and removes none.

## What this does not close

`docs/issues/archive/013` also observes that nothing compares a venue's categories against the roster. That
comparison is now unnecessary for KRX, because the venue has no categories to compare. A venue
that still resolves cost from construction-time rules — any user-authored one — can still disagree
with the roster, and `check` has no judgment for it. The issue stays open for that.
