# The six sections of a `StrategyReport`

## Contents

- performance
- book
- attribution
- trading
- intent
- compliance
- Omissions, and what a `RunReport` adds

Each section is a pydantic document. Each is `None` with a reason in `omitted` when the record
cannot give it — read `omitted` before concluding a strategy did nothing.

Every series is `instants` beside `values`, which is the whole bridge to a frame:

```python
pd.Series(s.values, index=pd.DatetimeIndex(s.instants)).astype(float)
```

## `performance`

NAV, period returns and drawdown as series. Total and annualised return, volatility, Sharpe,
Sortino, Calmar, max drawdown and when it happened, positive-period share. `by_year` and
`by_month`.

**`periods_per_year` is inferred from the valuation grid** and the document says so (`inferred`).
Pass it to `strategy_report` to override. Every annualised number in this section depends on it,
so it belongs in any caption.

**Sharpe is against `risk_free_annual`**, zero unless given — the record holds no rate.

## `book`

Held, long and short counts; gross, net, long and short exposure; cash share; max weight; HHI —
per valuation, from the marked positions.

This is the section that answers "was it actually long-short", and it answers it from what was
held, not from what was intended.

## `attribution`

P&L per period by name and by side (long / short), and **`residual`**: the part of the NAV change
that no marked name explains.

Zero when every held name was marked. **A non-zero residual is a finding, not noise** — report it
rather than rounding past it.

`position_hit_rate` is the share of name-periods with a positive P&L.

## `trading`

One-way realised turnover (from fills) beside one-way intended turnover (from weights). The gap
between them is the size of what did not execute.

Costs summed from `vqapr.fill`: commission, tax, basis points of notional, share of mean NAV per
year, and by roster kind. `fills` is the same summary `vqapr run` prints, including
`never_filled`. Holding periods.

**Cost is summed from fills, never read off a venue's rate.** Commission and tax are per fill and
per side, so a category's true cost is a sum over the table.

## `intent`

Each decision's weights against the book at the first valuation after it: `gap`
(Σ |realised − intended|) and `weight_sign_hit_rate`.

This is the section that says whether the strategy got the book it asked for. A large `gap` with a
good `weight_sign_hit_rate` is a sizing or liquidity story; a poor sign hit rate is a different
one.

## `compliance`

Per compliance rule: `checked` split into `held` / `within_tolerance` / `breached` / `unmeasured`, the
worst excess and when, the offending names by count.

`within_tolerance` is not a breach and not a clean hold. A book executes in whole lots and is
marked after its fills, so a realised weight lands a little off target; the framework judges each
excess against `max(bound × 1%, 10bp of NAV)` in one place. Only `breached` makes the contract
`ok: false`, and all three counts are reported so nothing is hidden.

## Three hit rates, three names

| name | section | what it measures |
|---|---|---|
| `positive_period_share` | performance | share of periods with positive return |
| `position_hit_rate` | attribution | share of name-periods with positive P&L |
| `weight_sign_hit_rate` | intent | share of decisions whose realised weight had the intended sign |

Never report any of them as "hit ratio" without saying which.

## What a `RunReport` adds

A run holds one strategy, so its finished records are that strategy's versions — one per
fingerprint, one per tweak. A `RunReport` lines them up:

- `headline` — one row per record
- `correlation` — of period returns, on the instants **all** records share
- `relative` — active return, tracking error, information ratio against the record you name as
  `benchmark`

The benchmark must be a record of the same run. Two different strategies are two runs; read a
`strategy_report` for each. An index level is not in the record, and `run_report` will not invent
one.
