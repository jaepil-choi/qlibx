# 010 Optional portfolio construction

## Intent

Start M6 with the part that does not depend on unresolved benchmark or sector publication timing.
UC-PORTFOLIO-001 requires one immutable signed alpha result to support more than one compatible
portfolio use without rewriting the alpha into a physical-instrument meaning.

## Implementation

- `PortfolioConstructionInput` accepts only a unique, finite, non-zero signed-alpha axis.
- `HYPOTHETICAL_SIGNED` preserves long and short directions and scales gross exposure to the
  explicitly requested budget.
- `EQUITY_LONG_ONLY` removes negative entries, scales the remaining positive entries to the
  requested physical budget, and fails explicitly when no long candidate exists.
- `PortfolioConstructionResult` preserves original and target weights separately and records
  requested budget, realized gross/net exposure, cash residual, profile, scale, and source identity.
- `PortfolioConstructionFlow` loads the typed StrategyResult, publishes a separate versioned
  portfolio artifact, and records alpha/config dependencies. It has no Account or Memory port and
  therefore cannot mutate either authority.

## Real-data evidence

The acceptance uses unchanged rows from `data/DW/fng_stock_daily_prices.csv` for A005930 and
A000660 on 2024-01-02. Their close-to-base returns are imported as one external signal and converted
once to signed alpha weights A000660 -0.5 and A005930 +0.5.

- The hypothetical profile preserves -0.5/+0.5, gross 1.0, and net 0.0.
- The equity long-only profile produces A005930 +1.0, gross 1.0, and net 1.0.
- Both result envelopes depend on the same source StrategyResult artifact.
- The source StrategyResult serialization is identical before and after both constructions.

The executable case is registered in `tests/scenarios/current_scope.yaml`; the separate
`tests/scenarios/data_sources.yaml` audit prevents K200 membership, sector, or ETF data from being
claimed PIT-safe before their availability semantics are resolved.

## Trade-offs and limitations

This slice is a deterministic direction/budget transform, not an enhanced-index optimizer. It does
not infer a benchmark, ETF constituent mapping, sector binding, cost model, or settlement behavior.
Those are invocation-specific requirements and must not be guessed from ticker names or the
presence of a dataset. Real short and perpetual construction remain unsupported current scope.

## Validation

- UC-PORTFOLIO-001 real-DW acceptance and scenario/architecture guards: 4 passed.
- Full pytest: 63 passed.
- Ruff and public import smoke: passed.
- `uv build`: built qlibx 0.1.0 sdist and wheel.
