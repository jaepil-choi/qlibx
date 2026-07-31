# Example 03: RSI Mean Reversion

Enters LONG when RSI < oversold threshold. Exits when RSI > overbought threshold.

Classic mean-reversion pattern.

## Intuition

RSI (Relative Strength Index) compares the average magnitude of recent gains
to the average magnitude of recent losses. Values below 30 are considered
"oversold" (too many losses relative to gains) and values above 70 are
"overbought". The bet: oversold markets overshoot and revert, overbought
markets exhaust and revert.

Mean-reversion systems typically have:
- High hit rate (55-70%)
- Small average winner vs. small average loser
- Poor performance in trending regimes (you fade breakouts into losers)
- Best in range-bound, mean-stationary markets

## Suggested Backtest

```
# Inside a workspace produced by `echolon init` (instrument/start/end recovered from marker):
echolon backtest single .

# Or pass the ctx explicitly if no marker is present:
echolon backtest single . --instrument rb --start 2018-01-01 --end 2022-12-31
```

RB (rebar) in this window has oscillated within a broad range, which is
mean-reversion's preferred environment. Avoid running on instruments in
strong secular trends (like gold during 2024-2025) — reversion logic is
structurally wrong there.

## Tuning

`strategy_params.py` declares an Optuna search space over the RSI period
(10-20), oversold threshold (20-35), and overbought threshold (65-80).
Tighter thresholds trade more often but with less edge; wider thresholds
trade rarely but with higher edge per trade.
