# 025 — An academic venue charges what it declares

## Why this exists

`load_exchange` states the contract for a user execution profile:

> A user subclass may add listings **and costs**, but it may not silently replace `execute` with
> its own matching behaviour, because the resulting realism claim would be unverified.

`AcademicExchange` did not honour the first half. Its `execute` built every `Fill` without a
`cost`, so a subclass that declared a cost band got it ignored — and the only way to price a trade
was to override `execute`, which `load_exchange` then refused. The two shipped profiles left no
combination that both permits shorting and charges:

| profile | 공매도 | 비용 |
|---|---|---|
| `AcademicExchange` | 가능 | **부과 안 함** |
| `KrxExchange` | **거부** (long positions only) | 부과 |

A dollar-neutral alpha therefore could not be costed at all. That is not an academic restriction:
the report this framework is reproducing prices its long-short families at 3bp to buy and 23bp to
sell, and there was no way to express it.

## What changed

`AcademicExchange.execute` charges `self.rules` on each dealt fill, exactly as `KrxExchange`
already does:

```python
side = side_of(request.delta_quantity)
cost=rules.charge(side, abs(request.delta_quantity) * row.price, snapshot.target_at)
```

`ExchangeRulesView.charge` returns an empty `FillCost` when no rule is declared, so the base
profile still charges nothing and every existing result is unmoved. The matching is untouched:
absent, non-tradable and zero-delta requests take the same paths and produce the same typed
zero-dealt evidence they did before.

The docstring on `rules` now says a subclass may declare a band and that `execute` will apply it,
rather than describing the empty band as a property of the profile.

## Why this is the right place

Cost belongs to the fill, not to a layer above it. A `Fill` carries its own `FillCost`, and
`Account.prepare_fill` takes the money out of cash in the same transition that moves the position —
measured on a 1000 buy at 3bp:

```
체결 전 현금 100000  ->  체결 후 98999.7000
```

So a NAV read from `mark_history` is already net of costs. Return and cost cannot disagree about
which book they describe, which is the failure this framework exists to avoid: the research being
reproduced computes return from a daily-rebalanced book and cost from a held one, and the two are
never the same portfolio.

## Trade-offs

**The academic profile is still not a market.** It fills everything at the selected price with no
liquidity, participation, borrow or margin model. Declaring a cost band prices the trade; it does
not make the fill more realistic, and the profile's name should keep being read as the warning it
is.

## Validation

- `uv run pytest -q` — 529 passed, including a subclass that declares a band and is charged
  3bp/23bp, and the base profile still charging zero.
- `uv run ruff check src tests` — clean.
- `show_005_enhanced_index` and `show_008_alpha_family_ensemble` regenerate byte-identical
  manifests: no shipped profile declares costs, so nothing existing moved.
