# 017 — A target is a weight, because the callback cannot see the price

## Why this exists

`PortfolioTarget` carried `weight | quantity` and required exactly one of them. Architecture §5.4
explained the pair as two economic meanings with different behaviour under price movement:

> quantity target은 금액이 아니라 수량을 고정하므로 갭 노출이 남는다 — 결함이 아니라
> *"정확히 이만큼 보유하고 싶다"*는 그 target의 의미다

The meaning was coherent. The problem is that **no Strategy could express it.**

## What the measurement showed

A callback sees exactly this:

```
StrategyModelContext: ['occurrence', 'window', 'account', 'constraint_bounds']
AccountSnapshot     : ['version', 'cash', 'positions']
```

There is no execution price and no NAV; `positions` is a share count, not a valuation. So a
Strategy naming a quantity had to derive it from an earlier price — and `plan_orders` then required
`cash_target` to equal the resulting cash fraction *exactly*:

```
전략 판단(08:00, 전일종가 100): 추정 NAV 20000, 목표 150주 -> cash_target 0.25 선언
  체결가 100: OK
  체결가 101: 거부 -> complete desired positions do not produce the declared cash_target
  체결가 110: 거부
```

A one percent move rejected the whole batch. The option was not merely awkward; it was unusable
from the only place that was allowed to produce it.

Usage agreed. Across `src`, `tests`, and `showcases`, Strategy files held 40 weight targets and 4
quantity targets, and all four were in `tests/acceptance/test_time_002.py` as fixture values for
tests about the frozen instrument universe and timing — never about quantity economics.

## The deeper correction

Architecture §6.1 already stated the real boundary:

> 갈라놓은 것은 **델타를 언제 계산하는가**다 — 목표는 체결 시점의 포트폴리오에 대한 진술인데, 판단
> 시점의 계좌는 이전 가격으로 평가되어 있다.

That is the whole reason `plan_orders` exists: the Strategy states a weight one evaluation earlier,
and the conversion to a share count happens later, at the price the fill actually uses. Letting the
Strategy name a quantity **inverts that** — it moves the conversion back to decision time and does
it with a stale price. The same document that justified the quantity option describes the split
that the option breaks.

## What changed

- `PortfolioTarget` is `instrument_id` plus a required `weight`. The `quantity` field is gone, so
  the "exactly one of" rule disappears with it.
- `validate_economic_intent` no longer branches on target kind. Every intent satisfies
  `Σw + cash_target = 1`; the mixed-economics error is deleted because mixing is unrepresentable.
- `plan_orders` drops the `quantity_targets` parameter, the weight/quantity overlap check, and the
  post-trade cash reconciliation that only quantity targets needed. Its docstring now states that
  it is the single place a weight becomes a quantity.
- Architecture §5.3, §5.4 and §6.1 are corrected. §5.4 previously presented the two kinds as a
  design choice; it now records why a target cannot be a quantity and points at `plan_orders`.

## Trade-offs

**An exact share count is no longer expressible as an intent.** That is the intended loss. A share
count is meaningful only to someone who knows the fill price — an operator or an OMS — and not to
an alpha callback. If a future workflow needs it, it belongs to a surface that has the price, not
to `StrategyModel`.

**Tests that used quantity as a convenient fixture were rewritten as weights.** In every case the
test's subject (frozen universe, timing, KRX lot rounding, budget bounds) was unrelated to the
target kind, so the assertions are unchanged in meaning.

## Validation

- `uv run pytest -q` — 507 passed.
- `uv run ruff check src tests` — clean.
- `showcases/show_008_alpha_family_ensemble` and `show_005_enhanced_index` regenerate and their
  determinism checks still pass.
- A new planning test pins the property this change protects: an unchanged weight target produces
  `delta_quantity == 0` after a price move, so drift alone never manufactures an order.
