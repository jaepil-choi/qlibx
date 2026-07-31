# Interday Trading Patterns

## Overview

This document covers patterns specific to **interday trading** (daily bars).
For SHFE futures, this includes contract expiry awareness via `ForcedExitStrategyHook`.

**When to use**: Any strategy where `TradingContext.frequency == "interday"` (set when the host calls `MarketFactory.create(..., frequency="interday", ...)`).

---

## Indicator Naming Convention (CRITICAL)

**All indicator names MUST be lowercase with underscores:**
- Correct: `rsi_14`, `atr_20`, `market_regime`, `adx_14`
- Wrong: `RSI_14`, `ATR_20`, `MARKET_REGIME`

The infrastructure converts to lowercase internally, but consistent lowercase naming prevents confusion.

---

## Key Differences from Intraday

| Aspect | Interday | Intraday |
|--------|----------|----------|
| Bar frequency | Daily (1 bar/day) | Sub-daily (multiple bars/day) |
| Session methods | NOT available | Available via hook |
| Overnight gap | Must handle | Within session |
| Contract expiry | Yes (SHFE futures) | No (flatten EOD) |
| Indicator periods | Days | Bars |
| Position holding | Multi-day | Same-day (usually) |

---

## Valid `market_regime` values (interday only)

The `market_regime` indicator emits **exactly these 4 string values** — via
`self.get_market_regime()`, NOT via `self.get_indicator('market_regime')`
(which returns numeric codes). Source of truth:
`echolon/indicators/calculators/interday/market_regime.py`.

| Value | Numeric code | Meaning |
|---|---|---|
| `trending_up` | 1 | Strong upward trend |
| `trending_down` | -1 | Strong downward trend |
| `ranging` | 0 | No directional trend |
| `volatile` | 2 | High-volatility mean-reversion regime |

**No other values exist.** There is no `strong_trending_up`, no
`strong_trending_down`, no `strong_*` variant of any kind. Branch logic
against these exact 4 strings only.

---

## Session Methods NOT Available

Interday strategies do NOT have session methods. The following will NOT be available:
- `get_session_phase()`
- `is_opening_phase()`, `is_closing_phase()`
- `get_bar_of_session()`, `get_bars_remaining_in_session()`
- `get_vwap()`, `get_opening_range()`
- `is_first_session()`, `is_last_session()`, `is_session_break()`

**Code Pattern**: Use `hasattr()` guards so code works across frequencies:

```python
# This block never executes in interday (hasattr returns False)
if hasattr(self, 'is_closing_phase') and self.is_closing_phase():
    pass  # Skipped in interday mode

# Standard daily bar logic (always executes)
atr = self.get_indicator(f'atr_{self.atr_period}')
```

---

## Contract Expiry Awareness (SHFE Futures)

### ForcedExitStrategyHook

For SHFE futures with interday frequency, the `ForcedExitStrategyHook` automatically handles:
- Detection of approaching contract expiry
- Automatic position close before expiry
- Rollover timing signals

**Infrastructure Handling**: The hook is applied in `backtrader_strategy.py` and processes forced exits BEFORE `on_bar()` is called. **Components do NOT need special handling**.

### Hook-Injected Methods (Strategy Level Only)

The following methods are injected into `BaseStrategy` (NOT components):

```python
# Available on BaseStrategy when ForcedExitStrategyHook is applied
check_and_process_forced_exits() -> bool  # Called automatically
signal_forced_exit() -> None              # Internal use
check_contract_expiry() -> bool           # Internal use
```

**IMPORTANT**: These methods are called by infrastructure. Do NOT call them manually in `on_bar()`.

### Code Pattern in strategy.py

```python
class strategy_main(BaseStrategy):
    def _execute_bar(self):
        """
        Override target — NOT ``on_bar()``. ``BaseStrategy.on_bar()`` is a
        Template Method that orchestrates hook lifecycle; strategies must
        override ``_execute_bar()`` only (echolon/strategy/base.py:934).

        For SHFE interday futures, contract-expiry forced exits run in
        BacktraderStrategyBridge.next() BEFORE this method fires. DO NOT
        call check_and_process_forced_exits() manually.
        """
        # 1. Check risk constraints
        risk_output = self.risk_manager.can_trade()
        if not risk_output.trading_allowed:
            return

        # 2. Generate entry signals (if no position)
        if not self.has_position():
            entry_signal = self.entry_rule.generate_signal()
            if entry_signal.signal != 'HOLD':
                sizer_output = self.position_sizer.calculate_size(entry_signal)
                self.entry(entry_signal.intent, sizer_output.calculated_size)

        # 3. Manage exits (if has position)
        else:
            exit_decision = self.exit_rule.should_exit()
            if exit_decision.should_exit:
                self.exit(exit_decision.intent)
```

---

## Indicator Period Guidelines (Interday/Daily)

### Period Semantics

Interday indicator periods are specified in **days** (daily bars):
- `rsi_period: 14` = 14 daily bars (14 trading days)
- `atr_period: 20` = 20 daily bars

### Period Caps

Maximum periods for interday (SHFE contracts have ~186 bars minimum):

| Indicator Type | Max Period | Reason |
|----------------|------------|--------|
| TEMA/TRIX/ADXR | 62 days | 3x lookback requirement |
| ADX/DEMA | 93 days | 2x lookback requirement |
| Standard (RSI, ATR, etc.) | 180 days | Contract data limit |

### Recommended Ranges

| Indicator | Typical Range | Standard |
|-----------|---------------|----------|
| RSI | 7-30 days | 14 |
| CCI | 10-40 days | 20 |
| ATR | 7-30 days | 14 |
| ADX | 10-30 days | 14 |
| EMA fast | 5-20 days | 10 |
| EMA slow | 20-60 days | 50 |

---

## Component Examples

### Entry Component (Interday)

```python
class entry_rule(BaseComponent):
    def __init__(self, trading_engine: ITradingEngine, **params):
        super().__init__(trading_engine, **params)
        self.rsi_period = self.params['rsi_period']
        self.rsi_oversold = self.params['rsi_oversold']
        self.rsi_overbought = self.params['rsi_overbought']
        self.adx_period = self.params['adx_period']
        self.adx_threshold = self.params['adx_threshold']

    def generate_signal(self) -> EntrySignalOutput:
        # Standard daily bar entry logic
        rsi = self.get_indicator(f'rsi_{self.rsi_period}')
        adx = self.get_indicator(f'adx_{self.adx_period}')
        regime = self.get_market_regime()  # INTERDAY ONLY

        signal = 'HOLD'
        intent = None
        strength = 0.0
        reason = ''

        if not self.has_position():
            # Trend-following with momentum confirmation
            if regime == 'trending_up':
                if rsi < self.rsi_overbought and adx > self.adx_threshold:
                    signal = 'LONG'
                    intent = OrderIntent.ENTRY_LONG
                    strength = min(1.0, adx / 50)  # Strength based on ADX
                    reason = f'Uptrend entry: RSI {rsi:.1f}, ADX {adx:.1f}, regime {regime}'

            elif regime == 'trending_down':
                if rsi > self.rsi_oversold and adx > self.adx_threshold:
                    signal = 'SHORT'
                    intent = OrderIntent.ENTRY_SHORT
                    strength = min(1.0, adx / 50)
                    reason = f'Downtrend entry: RSI {rsi:.1f}, ADX {adx:.1f}, regime {regime}'

        output = EntrySignalOutput(
            signal=signal,
            strength=strength,
            type=f'entry_{signal.lower()}' if signal != 'HOLD' else 'hold',
            entry_reason=reason if reason else f'No entry condition met (RSI: {rsi:.1f})',
            intent=intent,
            regime=regime,
            rsi_value=rsi,
            adx_value=adx
        )

        self.log_entry_output(output)
        return output
```

### Exit Component (Interday)

```python
class exit_rule(BaseComponent):
    def __init__(self, trading_engine: ITradingEngine, **params):
        super().__init__(trading_engine, **params)
        self.atr_period = self.params['atr_period']
        self.atr_stop_multiplier = self.params['atr_stop_multiplier']
        self.atr_profit_multiplier = self.params['atr_profit_multiplier']
        self.max_holding_days = self.params['max_holding_days']
        # State for persistence
        self.stop_price = None
        self.take_profit_price = None
        self.bars_in_position = 0

    def should_exit(self) -> ExitSignalOutput:
        position = self.portfolio.get_position()

        if position is None or position.size == 0:
            output = ExitSignalOutput(
                should_exit=False,
                exit_reason='No position to exit',
                position_size=0.0,
                bars_since_entry=0,
                intent=None
            )
            self.log_exit_output(output)
            return output

        # Increment position holding counter
        self.bars_in_position += 1

        atr = self.get_indicator(f'atr_{self.atr_period}')
        current_price = self.get_current_price()
        entry_price = position.avg_price
        is_long = position.direction == 'LONG'

        # Initialize stops on first check
        if self.stop_price is None:
            if is_long:
                self.stop_price = entry_price - (atr * self.atr_stop_multiplier)
                self.take_profit_price = entry_price + (atr * self.atr_profit_multiplier)
            else:
                self.stop_price = entry_price + (atr * self.atr_stop_multiplier)
                self.take_profit_price = entry_price - (atr * self.atr_profit_multiplier)

        should_exit = False
        intent = None
        reason = ''

        # Check time-based exit (max holding period)
        if self.bars_in_position >= self.max_holding_days:
            should_exit = True
            intent = OrderIntent.EXIT_LONG if is_long else OrderIntent.EXIT_SHORT
            reason = f'Max holding period: {self.bars_in_position} days >= {self.max_holding_days}'

        # Check stop loss
        elif (is_long and current_price <= self.stop_price) or \
             (not is_long and current_price >= self.stop_price):
            should_exit = True
            intent = OrderIntent.EXIT_LONG if is_long else OrderIntent.EXIT_SHORT
            reason = f'Stop loss: price {current_price:.2f} hit stop {self.stop_price:.2f}'

        # Check take profit
        elif (is_long and current_price >= self.take_profit_price) or \
             (not is_long and current_price <= self.take_profit_price):
            should_exit = True
            intent = OrderIntent.EXIT_LONG if is_long else OrderIntent.EXIT_SHORT
            reason = f'Take profit: price {current_price:.2f} hit target {self.take_profit_price:.2f}'

        if not should_exit:
            reason = f'Holding (day {self.bars_in_position}): price {current_price:.2f}, stop {self.stop_price:.2f}'

        # Reset state if exiting
        if should_exit:
            self.stop_price = None
            self.take_profit_price = None
            self.bars_in_position = 0

        output = ExitSignalOutput(
            should_exit=should_exit,
            exit_reason=reason,
            position_size=abs(position.size),
            bars_since_entry=self.bars_in_position,
            intent=intent,
            atr_value=atr,
            stop_price=self.stop_price,
            take_profit_price=self.take_profit_price
        )

        self.log_exit_output(output)
        return output

    def _get_component_specific_state(self) -> Dict[str, Any]:
        """Return state for live trading persistence."""
        return {
            'stop_price': self.stop_price,
            'take_profit_price': self.take_profit_price,
            'bars_in_position': self.bars_in_position
        }

    def _restore_component_specific_state(self, state: Dict[str, Any]) -> None:
        """Restore state from persistence."""
        self.stop_price = state['stop_price']
        self.take_profit_price = state['take_profit_price']
        self.bars_in_position = state['bars_in_position']
```

### Risk Manager (Interday)

```python
class risk_manager(BaseComponent):
    def __init__(self, trading_engine: ITradingEngine, **params):
        super().__init__(trading_engine, **params)
        self.adx_period = self.params['adx_period']
        self.adx_min_threshold = self.params['adx_min_threshold']
        self.max_drawdown = self.params['max_drawdown']

    def can_trade(self) -> RiskOutput:
        # Check trend strength
        adx = self.get_indicator(f'adx_{self.adx_period}')

        if adx < self.adx_min_threshold:
            output = RiskOutput(
                trading_allowed=False,
                risk_reason=f'Weak trend: ADX {adx:.1f} < {self.adx_min_threshold}'
            )
            self.log_risk_output(output)
            return output

        # Standard risk check passed
        output = RiskOutput(
            trading_allowed=True,
            risk_reason=f'Trading allowed: ADX {adx:.1f} >= {self.adx_min_threshold}',
            adx_value=adx
        )
        self.log_risk_output(output)
        return output
```

---

## Interday-Specific Parameters

When generating `strategy_params.py` for interday, include these parameter categories:

### Time-Based Exit Parameters

```python
'max_holding_days': ParameterSpec(
    min_value=5, max_value=60, default=20,
    description="Maximum days to hold a position"
),
```

### Volatility Parameters (Daily ATR)

```python
'atr_stop_multiplier': ParameterSpec(
    min_value=1.0, max_value=4.0, default=2.0,
    description="ATR multiplier for stop loss"
),
'atr_profit_multiplier': ParameterSpec(
    min_value=2.0, max_value=6.0, default=3.0,
    description="ATR multiplier for take profit"
),
```

---

## Overnight Gap Considerations

Daily bars include overnight gaps. Consider:

1. **Gap risk**: Position can open significantly above/below previous close
2. **Stop slippage**: Stops may be triggered at gap open, not stop price
3. **ATR calculation**: Daily ATR includes gap volatility
4. **Weekend/holiday gaps**: Longer gaps after market closures

### Mitigation Strategies

```python
# Example: Wider stops to account for gaps
def calculate_stop_with_gap_buffer(self, entry_price, atr, gap_buffer=0.2):
    """Add gap buffer to stop calculation."""
    base_stop = atr * self.atr_stop_multiplier
    gap_adjusted_stop = base_stop * (1 + gap_buffer)
    return entry_price - gap_adjusted_stop  # For long position
```

---

## Best Practices

1. **Use longer indicator periods** (14+ days) for noise reduction
2. **Account for overnight gaps** in risk management
3. **Consider weekend/holiday gaps** (wider stops before long breaks)
4. **State persistence is critical** for live trading
5. **Max holding period** helps avoid stuck positions
6. **Contract expiry is automatic** - don't handle manually
7. **Period values are in DAYS** - each bar = 1 trading day
