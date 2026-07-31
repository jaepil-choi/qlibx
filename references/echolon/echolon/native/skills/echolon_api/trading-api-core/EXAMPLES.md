# Trading API Code Examples

## Entry Component Example

```python
from echolon.strategy.component import BaseComponent
from echolon.strategy.interfaces import ITradingEngine, OrderIntent
from echolon.strategy.schemas import EntrySignalOutput

class entry_rule(BaseComponent):
    def __init__(self, trading_engine: ITradingEngine, **params):
        super().__init__(trading_engine, **params)
        # Extract parameters (NO .get() with defaults!)
        self.rsi_period = self.params['rsi_period']
        self.rsi_oversold = self.params['rsi_oversold']
        self.adx_period = self.params['adx_period']
        self.adx_threshold = self.params['adx_threshold']

    def generate_signal(self) -> EntrySignalOutput:
        """Generate entry signal."""
        # Tier 1 indicators: use period suffix
        rsi = self.get_indicator(f'rsi_{self.rsi_period}')
        adx = self.get_indicator(f'adx_{self.adx_period}')

        # Market context: use frequency-specific method
        regime = self.get_market_regime()  # INTERDAY ONLY

        signal = 'HOLD'
        intent = None
        strength = 0.0
        reason = ''

        if not self.has_position():
            if rsi < self.rsi_oversold and adx > self.adx_threshold:
                signal = 'LONG'
                intent = OrderIntent.ENTRY_LONG
                strength = 1.0
                reason = f'RSI {rsi:.2f} oversold, ADX {adx:.2f} strong'

        # SINGLE OUTPUT PATTERN: Create once, log once, return same
        output = EntrySignalOutput(
            signal=signal,
            strength=strength,
            type='entry_long' if signal == 'LONG' else 'hold',
            entry_reason=reason,
            intent=intent,
            regime=regime,
            # Strategy-specific fields via extra='allow'
            rsi_value=rsi,
            adx_value=adx
        )

        self.log_entry_output(output)  # Same instance
        return output  # Same instance
```

## Exit Component Example

```python
from echolon.strategy.component import BaseComponent
from echolon.strategy.interfaces import ITradingEngine, OrderIntent
from echolon.strategy.schemas import ExitSignalOutput

class exit_rule(BaseComponent):
    def __init__(self, trading_engine: ITradingEngine, **params):
        super().__init__(trading_engine, **params)
        self.atr_period = self.params['atr_period']
        self.atr_stop_multiplier = self.params['atr_stop_multiplier']

    def should_exit(self) -> ExitSignalOutput:
        """Check exit conditions."""
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

        # Calculate stop distance
        atr = self.get_indicator(f'atr_{self.atr_period}')
        current_price = self.get_current_price()
        stop_distance = atr * self.atr_stop_multiplier

        is_long = position.direction == 'LONG'
        entry_price = position.avg_price

        should_exit = False
        intent = None
        reason = ''

        if is_long:
            stop_price = entry_price - stop_distance
            if current_price <= stop_price:
                should_exit = True
                intent = OrderIntent.EXIT_LONG
                reason = f'Stop loss hit: price {current_price:.2f} <= stop {stop_price:.2f}'
        else:
            stop_price = entry_price + stop_distance
            if current_price >= stop_price:
                should_exit = True
                intent = OrderIntent.EXIT_SHORT
                reason = f'Stop loss hit: price {current_price:.2f} >= stop {stop_price:.2f}'

        if not should_exit:
            reason = f'No exit condition met (current: {current_price:.2f})'

        output = ExitSignalOutput(
            should_exit=should_exit,
            exit_reason=reason,
            position_size=abs(position.size),
            # Simplified scaffold — real implementations track bars via
            # self.bars_in_position state, incremented in should_exit(); see
            # INTERDAY.md's exit example for the full pattern.
            bars_since_entry=0,
            intent=intent,
            # Strategy-specific fields
            atr_value=atr,
            stop_distance=stop_distance
        )

        self.log_exit_output(output)
        return output
```

## Position Sizer Example

**CRITICAL: For futures, MUST use contract multiplier in risk calculation!**

```python
from echolon.strategy.component import BaseComponent
from echolon.strategy.interfaces import ITradingEngine
from echolon.strategy.schemas import SizerOutput, EntrySignalOutput

class position_sizer(BaseComponent):
    def __init__(self, trading_engine: ITradingEngine, frequency_context=None, market_adapter=None, **params):
        super().__init__(trading_engine, frequency_context, market_adapter, **params)
        self.risk_per_trade_pct = self.params['risk_per_trade_pct']  # e.g., 2.0 for 2%
        self.atr_period = self.params['atr_period']
        self.stop_atr_multiplier = self.params['stop_atr_multiplier']

    def calculate_size(self, signal_data: EntrySignalOutput) -> SizerOutput:
        """
        Calculate position size based on risk percentage.

        CRITICAL FORMULA (for futures with multiplier):
            stop_distance = ATR × stop_multiplier
            risk_per_contract = stop_distance × contract_multiplier  # ← MUST include multiplier!
            position_size = (equity × risk_pct) / risk_per_contract
        """
        signal_direction = signal_data.signal

        if signal_direction == 'HOLD':
            output = SizerOutput(
                calculated_size=0,
                signal_direction='HOLD',
                sizing_reason='No sizing for HOLD signal',
                raw_size=0.0
            )
            self.log_sizer_output(output)
            return output

        # Get portfolio and market data
        portfolio_value = self.portfolio.get_total_value()
        atr = self.get_indicator(f'atr_{self.atr_period}')
        current_price = self.get_current_price()

        # Calculate stop distance
        stop_distance = atr * self.stop_atr_multiplier

        # CRITICAL: Get contract multiplier from market adapter.
        # Multiplier is mandatory for futures. If the market_adapter doesn't
        # expose it (e.g. misconfigured), that's a configuration error — let
        # the exception propagate (No Error Handling Policy in SKILL.md).
        if self.market_adapter is not None:
            contract_spec = self.market_adapter.get_contract_spec(self.market_adapter.symbol)
            multiplier = contract_spec.multiplier
        else:
            multiplier = 1.0  # Spot/no-leverage default — explicit, not fallback

        # Calculate risk per contract WITH multiplier
        risk_per_contract = stop_distance * multiplier

        # Avoid division by zero
        if risk_per_contract <= 0:
            output = SizerOutput(
                calculated_size=0,
                signal_direction=signal_direction,
                sizing_reason=f'Invalid risk per contract: {risk_per_contract:.2f}',
                raw_size=0.0
            )
            self.log_sizer_output(output)
            return output

        # Calculate position size
        risk_amount = portfolio_value * (self.risk_per_trade_pct / 100.0)
        raw_size = risk_amount / risk_per_contract

        # MANDATORY: Validate to non-negative integer
        validated_size = self.validate_and_convert_position_size(raw_size)

        output = SizerOutput(
            calculated_size=validated_size,
            signal_direction=signal_direction,
            sizing_reason=(
                f'Risk-based sizing: {validated_size} contracts. '
                f'Risk ${risk_amount:.2f} ({self.risk_per_trade_pct}%) / '
                f'${risk_per_contract:.2f} per contract '
                f'(stop {stop_distance:.2f} × multiplier {multiplier})'
            ),
            raw_size=raw_size,
            # Strategy-specific fields
            portfolio_value=portfolio_value,
            risk_amount=risk_amount,
            risk_per_contract=risk_per_contract,
            multiplier=multiplier,
            atr_value=atr
        )

        self.log_sizer_output(output)
        return output
```

### Position Sizing Formula Summary

| Market Type | Risk per Contract Formula | Example |
|-------------|---------------------------|---------|
| **Futures** | `stop_distance × multiplier` | SHFE AL: $35 × 5 = $175/contract |
| **Crypto Perp** | `stop_distance × multiplier` | BTC-PERP: $500 × 1 = $500/contract |
| **Spot/Stock** | `stop_distance × 1` | No multiplier needed |

**Common Bug**: Forgetting multiplier results in **5x-10x oversized positions!**

## Risk Manager Example

```python
from echolon.strategy.component import BaseComponent
from echolon.strategy.interfaces import ITradingEngine
from echolon.strategy.schemas import RiskOutput

class risk_manager(BaseComponent):
    def __init__(self, trading_engine: ITradingEngine, **params):
        super().__init__(trading_engine, **params)
        self.max_drawdown = self.params['max_drawdown']
        self.adx_period = self.params['adx_period']
        self.adx_min_threshold = self.params['adx_min_threshold']

    def can_trade(self) -> RiskOutput:
        """Check if trading is allowed."""
        adx = self.get_indicator(f'adx_{self.adx_period}')

        trading_allowed = True
        reason = 'Trading allowed'

        # Check trend strength
        if adx < self.adx_min_threshold:
            trading_allowed = False
            reason = f'Weak trend: ADX {adx:.2f} < {self.adx_min_threshold}'

        # Check portfolio drawdown
        portfolio_value = self.portfolio.get_total_value()
        # (Add drawdown check logic here)

        output = RiskOutput(
            trading_allowed=trading_allowed,
            risk_reason=reason,
            # Strategy-specific fields
            adx_value=adx,
            portfolio_value=portfolio_value
        )

        self.log_risk_output(output)
        return output
```

## Indicator Usage Examples

### Tier 1 (with lookback period)
```python
# CORRECT: Use period suffix
adx = self.get_indicator(f'adx_{self.adx_period}')
rsi = self.get_indicator(f'rsi_{self.rsi_period}')
ema_fast = self.get_indicator(f'ema_{self.ema_fast_period}')
atr = self.get_indicator(f'atr_{self.atr_period}')
highest = self.get_indicator(f'highest_high_{self.channel_period}')

# WRONG: Missing period
adx = self.get_indicator('adx')  # KeyError!
```

### Tier 2 (special parameters)
```python
# CORRECT: Bare name only
macd_line = self.get_indicator('macd_line')
macd_signal = self.get_indicator('macd_signal')
stoch_k = self.get_indicator('stoch_k')
bbands_upper = self.get_indicator('bbands_upper')

# WRONG: Adding parameters
macd = self.get_indicator('macd_line_12_26_9')  # KeyError!
```

### Tier 3 (no lookback)
```python
# CORRECT: Bare name
ad = self.get_indicator('ad')
obv = self.get_indicator('obv')
# Market context: use frequency-specific method
regime = self.get_market_regime()    # INTERDAY ONLY
# OR for intraday:
# session_phase = self.get_session_phase()  # INTRADAY ONLY
```
