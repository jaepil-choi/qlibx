# Example 02: Momentum Breakout

Enters LONG when close breaks above N-day high. Exits when close breaks below M-day low.

Classic trend-following pattern for futures.

## Intuition

This is a textbook Donchian-channel / turtle-trading idea: trends persist,
and the strongest signal of a trend is price making a new extreme. If
today's close exceeds the highest close of the last 20 bars, we interpret
that as a breakout and enter long. To exit, we wait for the trend to
reverse — a close below the last 10 bars' low.

Trend-following systems typically have:
- Low hit rate (35-45%)
- Large average winner vs. average loser
- Long flat periods followed by bursts of profit
- High correlation with volatility expansion regimes

## Suggested Backtest

```
# Inside a workspace produced by `echolon init` (instrument/start/end recovered from marker):
echolon backtest single .

# Or pass the ctx explicitly if no marker is present:
echolon backtest single . --instrument cu --start 2015-01-01 --end 2023-12-31
```

CU (Shanghai copper) has multiple multi-year trends in this window, giving
the breakout logic meaningful opportunities. Try rotating through `ag`,
`au`, `rb`, or `i` to see how the same logic behaves on different
underlyings.

## Tuning

`strategy_params.py` declares an Optuna search space over entry lookback
(10-50) and exit lookback (5-20). Typically shorter lookbacks trade more
often and have lower edge per trade; longer lookbacks trade rarely but
with higher average edge.
