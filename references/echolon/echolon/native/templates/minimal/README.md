# Example 01: Minimal Strategy

A minimal working Echolon strategy. TODO comments mark customization points.

## Next Steps

1. Edit entry.py to define your entry signal
2. Edit exit.py to define exits
3. Run: `echolon validate .`
4. Run: `echolon backtest single .` (ctx recovered from workspace marker, or pass `--instrument cu --start ... --end ...` explicitly)

See the patterns skill for more complex patterns.

## Background

This is the starter skeleton used for every Echolon strategy. The five components
(`strategy.py`, `entry.py`, `exit.py`, `risk.py`, `sizer.py`) map 1:1 to the five
objects `BaseStrategy` expects. None of them make trading decisions — the entry
returns `HOLD`, the exit holds forever, the risk manager always allows trading,
and the sizer returns a fixed size of 1 lot.

Use this template when you want a clean surface to implement a novel idea. Run
a backtest against it first to confirm the wiring works end-to-end, then edit
the entry/exit logic incrementally.

## Expected Behavior

Because the entry always returns `HOLD`, a backtest over any date range will
produce zero trades and zero PnL. That's intentional — it's a baseline to
verify that the engine, data pipeline, and contracts are wired correctly.
