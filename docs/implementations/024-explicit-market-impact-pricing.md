# 024 Explicit market-impact pricing

## Why

The exchange treated market impact as an addition to the exact transaction-cost rate. This mixed
an execution-price model with fee and tax policy, and it silently substituted the configured
impact coefficient whenever total market volume was absent. The resulting fill could therefore
claim an exact cost rule while embedding an unrelated liquidity penalty in `total_cost`.

## Outcome

Non-zero market impact now requires positive finite `total_market_volume` for every quote in the
batch. Missing volume returns `EXECUTION_MARKET_VOLUME_MISSING` during batch preflight, before any
candidate account state changes. Impact changes the fill price in the adverse direction: buys pay
above the reference quote and sells receive below it. `Fill.total_cost` remains exclusively the
result of the selected effective-dated cost rule.

Each Fill and daily evidence record carries both `reference_price` and `price_impact_rate` so the
price transformation is explicit and portable. The daily real-DW profile currently supplies no
total-market-volume role, so an impact-enabled exchange is rejected instead of inventing volume.

## Responsibility and flow

Exchange preflight owns required market-input validation. Its sizing loop first applies declared
volume, holding, and lot constraints. Buy affordability is solved against the quantity-dependent
impacted price, and the final impact is recomputed from the actual dealt quantity. Exchange then
applies the exact cost rule to the impacted trade value. Account receives only the resulting Fill
and does not reconstruct either impact or cost policy.

## Alternatives and trade-offs

Keeping the old fallback coefficient was rejected because the coefficient is not a market-volume
estimate. Adding impact to `CostRule.rate` was rejected because it destroys the distinction between
market impact and fees or taxes required by the architecture contract. Computing impact before
cash, holding, and lot clipping was also rejected because the recorded rate would describe a
quantity that did not execute.

The current quadratic participation model remains deliberately simple. This change makes its
inputs and output truthful; it does not claim the formula is a calibrated production impact model.

## Validation

- Focused exchange, Account, and daily execution suite -> 27 passed.
- Full suite -> 91 passed.
- Ruff on the six changed source and test files -> passed.
- `git diff --check` -> passed.

Regression coverage verifies missing-volume preflight with `CommitStatus.NONE`, separation of fill
price from transaction costs, and impact recomputation after cash clipping.

## Remaining limitations

No current canonical daily data role provides total market volume. Enabling non-zero impact in that
profile requires an explicit registered data capability and PIT-safe mapping. Calibration,
temporary impact, and cross-instrument impact remain future model choices.
