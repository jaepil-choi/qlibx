# Intraday Trading Patterns

## Overview

This document covers patterns specific to **intraday trading** (sub-daily bars like 5m, 15m, 1h).
Session-aware methods are injected via hooks at runtime:
- `SessionAwareStrategyHook` → BaseStrategy (DAY + SESSION helpers)
- `SessionAwareComponentHook` → BaseComponent (SESSION helpers only)

**When to use**: Any strategy where `TradingContext.frequency == "intraday"` (set when the host calls `MarketFactory.create(..., frequency="intraday", ...)`).

---

## Strategy-Level Methods (SessionAwareStrategyHook)

The `SessionAwareStrategyHook` injects these methods into BaseStrategy:

### DAY-Level Helpers (use mandatory bar count indicators)

| Method | Return Type | Description |
|--------|-------------|-------------|
| `get_bar_of_day()` | `int` | Bar position in trading DAY (0-indexed) |
| `get_bars_remaining()` | `int` | Bars until DAY end (holiday-aware) |
| `get_total_bars_today()` | `int` | Total bars for the trading day |
| `get_has_night_session()` | `bool` | Whether night session exists (False after holidays) |

### SESSION-Level Helpers (use mandatory bar count indicators)

| Method | Return Type | Description |
|--------|-------------|-------------|
| `get_session_context()` | `Optional[SessionContext]` | Complete session context object |
| `get_bar_of_session()` | `int` | Bar position in SESSION (0-indexed) |
| `get_bars_remaining_in_session()` | `int` | Bars until SESSION end (not day end) |
| `get_session_bars_total()` | `int` | Total bars for current session |
| `get_session_index()` | `int` | Session index (0-based) |
| `is_first_session()` | `bool` | First session of trading day |
| `is_last_session()` | `bool` | Last session of trading day |
| `is_session_break()` | `bool` | Currently in break period |
| `is_opening_phase()` | `bool` | Opening phase check |
| `is_closing_phase()` | `bool` | Closing phase check |
| `get_minutes_since_session_open()` | `int` | Minutes since session open |
| `get_minutes_to_session_close()` | `int` | Minutes until session close |

### Price-Level Helpers (use market_data, NOT mandatory indicators)

| Method | Return Type | Description |
|--------|-------------|-------------|
| `get_vwap()` | `Optional[float]` | Session VWAP |
| `get_opening_range()` | `Tuple[Optional[float], Optional[float]]` | (OR high, OR low) |

---

## Component-Level Methods (SessionAwareComponentHook)

The `SessionAwareComponentHook` injects both DAY-level and SESSION-level methods into BaseComponent subclasses.

### DAY-Level Helpers (use mandatory bar count indicators)

| Method | Return Type | Description |
|--------|-------------|-------------|
| `get_bar_of_day()` | `int` | 0-indexed bar position in trading DAY |
| `get_bars_remaining()` | `int` | Bars until DAY end (holiday-aware) |
| `get_total_bars_today()` | `int` | Total bars for the trading day |
| `get_has_night_session()` | `bool` | Whether night session exists |

### SESSION-Level Helpers

| Method | Return Type | Description |
|--------|-------------|-------------|
| `get_session_context()` | `Optional[SessionContext]` | Complete session context object |
| `get_bar_of_session()` | `int` | 0-indexed bar position in session |
| `get_bars_remaining_in_session()` | `int` | Bars until SESSION end (not day end) |
| `get_session_bars_total()` | `int` | Total bars for current session |
| `get_session_index()` | `int` | 0-based session index for day |
| `is_first_session()` | `bool` | First session of trading day |
| `is_last_session()` | `bool` | Last session of trading day |
| `is_session_break()` | `bool` | Currently in break period |
| `is_opening_phase()` | `bool` | Opening phase check |
| `is_closing_phase()` | `bool` | Closing phase check |
| `get_minutes_since_session_open()` | `int` | Minutes since session open |
| `get_minutes_to_session_close()` | `int` | Minutes until session close |

### Price-Level Helpers

| Method | Return Type | Description |
|--------|-------------|-------------|
| `get_vwap()` | `Optional[float]` | Session VWAP |
| `get_opening_range()` | `Tuple[Optional[float], Optional[float]]` | (OR high, OR low) |

---

## Frequency-Agnostic Code Pattern (CRITICAL)

Since session methods are injected via hooks **only for intraday**, code MUST use `hasattr()` guards to work across all frequencies:

```python
# CORRECT: Works for both interday and intraday
if hasattr(self, 'is_closing_phase') and self.is_closing_phase():
    # Intraday closing logic - only executes when hook is applied
    pass

# WRONG: Will raise AttributeError in interday mode
if self.is_closing_phase():  # AttributeError when hook not applied!
    pass
```

**Why this pattern?**
- Hooks inject methods at runtime based on frequency configuration
- Interday strategies don't have session hooks applied
- Code must gracefully handle both cases

---

## Session Phase String Conversion (CRITICAL)

**Problem**: The `session_phase` indicator is stored as numeric codes at runtime. Strategy code needs string comparison.

**Solution**: Use `get_session_phase()` method which handles numeric-to-string conversion:

```python
# CORRECT: Use infrastructure method for string conversion
session_phase = self.get_session_phase()  # Returns phase name (bar-size-dependent)
# Check against TradingContext.tradeable_phases for valid phase names

# WRONG: Direct indicator access returns numeric
session_phase = self.get_indicator('session_phase')  # Returns numeric code
if session_phase == 'some_phase':  # FAILS - comparing int to string
```

**Numeric Encoding Source of Truth**: `config/markets/shfe/phases.py::PHASE_ENCODING`
- Do NOT hardcode phase mappings in strategy code
- Use `get_session_phase()` for string comparison (INTRADAY ONLY)
- Use `from config.markets.shfe.phases import PHASE_ENCODING` if numeric codes are needed

**Frequency-Specific Methods**:
- **Intraday**: Use `get_session_phase()` → Returns phase name (varies by bar size - see below)
- **Interday**: Use `get_market_regime()` → Returns 'trending_up', 'ranging', 'volatile', etc.

**IMPORTANT**: These methods are frequency-validated. Calling the wrong method raises `RuntimeError`:
- `get_session_phase()` in interday → RuntimeError (use `get_market_regime()` instead)
- `get_market_regime()` in intraday → RuntimeError (use `get_session_phase()` instead)

---

## Session Phases by Market

### SHFE (Shanghai Futures Exchange)

SHFE has two sessions (night + day) with breaks. **Phase names vary by bar size:**

#### Bar-Size-Aware Phase System (CRITICAL)

| Bar Size | Phase System | Tradeable Phases | Source of Truth |
|----------|--------------|------------------|-----------------|
| 5m, 15m | **Granular** | `night`, `morning`, `afternoon` | `TradingContext.tradeable_phases` |
| 30m, 1h | **Aggregated** | `night_session`, `day_session` | `TradingContext.tradeable_phases` |

**Why two systems?**
- Granular (5m/15m): Enough bars per phase for meaningful phase-specific logic
- Aggregated (30m/1h): Fewer bars → phases combined for statistical significance

**Source of Truth**: `config/markets/shfe/phases.py`
- `PHASES` dict: Granular phase definitions
- `PHASES_AGGREGATED` dict: Aggregated phase definitions
- `is_aggregated_bar_size(bar_size)`: Returns True for 30m/1h
- `granular_to_aggregated_phase(phase)`: Maps granular → aggregated

#### Granular Phase System (5m, 15m bars)

| Phase Name | Time Range | Duration | Trading Status |
|------------|------------|----------|----------------|
| `night` | 21:00-01:00 | 4 hours | TRADEABLE (with buffers) |
| `morning` | 09:00-11:30 | 2.5 hours | TRADEABLE (with opening buffer) |
| `morning_break` | 10:15-10:30 | 15 min | NON-TRADEABLE |
| `lunch_break` | 11:30-13:30 | 2 hours | NON-TRADEABLE |
| `afternoon` | 13:30-15:00 | 1.5 hours | TRADEABLE (with closing buffer) |

#### Aggregated Phase System (30m, 1h bars)

| Phase Name | Time Range | Duration | Trading Status |
|------------|------------|----------|----------------|
| `night_session` | 21:00-01:00 | 4 hours | TRADEABLE (with buffers) |
| `day_session` | 09:00-15:00 | 6 hours | TRADEABLE (includes lunch gap) |

**Note**: In aggregated mode, `day_session` spans both morning and afternoon. Lunch break is a gap WITHIN `day_session` - positions are HELD through lunch (not flattened).

#### Timing Buffers (in minutes, convert to bars at runtime)

**Granular phases:**
| Phase | Opening Buffer | Closing Buffer | Rationale |
|-------|----------------|----------------|-----------|
| `night` | 30 min | 30 min | Gap reaction; position squaring |
| `morning` | 30 min | 0 min | Overnight gap; break follows |
| `afternoon` | 0 min | 15 min | After break; settlement squaring |

**Aggregated phases:**
| Phase | Opening Buffer | Closing Buffer | Rationale |
|-------|----------------|----------------|-----------|
| `night_session` | 30 min | 30 min | Gap reaction; position squaring |
| `day_session` | 30 min | 15 min | Overnight gap; settlement squaring |

#### Entry Pattern with Buffers (Bar-Size-Aware)

```python
from config.markets.shfe.phases import get_phase_buffer_bars

bar_size_minutes = self.ctx.bar_size_minutes
session_phase = self.get_session_phase()  # Returns bar-size-appropriate phase name
tradeable_phases = self.ctx.tradeable_phases  # ['night', 'morning', 'afternoon'] or ['night_session', 'day_session']

opening_buffer = get_phase_buffer_bars(session_phase, 'opening', bar_size_minutes)
closing_buffer = get_phase_buffer_bars(session_phase, 'closing', bar_size_minutes)

if session_phase in tradeable_phases:
    if bar_of_session > opening_buffer and bars_remaining > closing_buffer:
        # Entry allowed - apply indicator logic
```

**Bars per day** (5-min): ~93 bars
**Bars per day** (15-min): ~31 bars
**Bars per day** (30-min): ~16 bars
**Bars per day** (1h): ~8 bars

### Crypto (24/7 Markets)

Crypto sessions are continuous:

| Phase Name | Description |
|------------|-------------|
| `opening` | First bars of session |
| `active` | Main trading period |
| `closing` | End of session |

**Bars per day** (15-min): 96 bars
**No breaks**: 24/7 trading

---

## Indicator Period Guidelines (Intraday)

### Indicator Naming Convention (CRITICAL)

**All indicator names MUST be lowercase with underscores:**
- Correct: `rsi_28`, `atr_14`, `session_phase`, `vwap_distance_pct`
- Wrong: `RSI_28`, `ATR_14`, `SESSION_PHASE`

The infrastructure converts to lowercase internally, but consistent lowercase naming prevents confusion.

### Period Semantics

Intraday indicator periods are specified in **bars**, not days:
- `rsi_period: 28` = 28 bars (~2.3 hours for SHFE 5-min)
- `atr_period: 60` = 60 bars (~5 hours for SHFE 5-min)

**Time conversion**: `hours = bars × bar_size_minutes / 60`
- 5-min bars: 12 bars = 1 hour
- 15-min bars: 4 bars = 1 hour

### Period Caps

Maximum periods for intraday (prevents NaN with ~4000+ bars history):

| Indicator Type | Max Period | Reason |
|----------------|------------|--------|
| TEMA/TRIX/ADXR | 500 bars | 3x lookback requirement |
| ADX/DEMA | 750 bars | 2x lookback requirement |
| Standard (RSI, ATR, etc.) | 1000 bars | General cap |

### Recommended Ranges for SHFE 5-min (~93 bars/day)

| Indicator | Typical Range | Time Equivalent |
|-----------|---------------|-----------------|
| RSI | 24-72 bars | 2-6 hours |
| CCI | 36-120 bars | 3-10 hours |
| ATR | 24-72 bars | 2-6 hours |
| ADX | 24-72 bars | 2-6 hours |
| EMA fast | 12-36 bars | 1-3 hours |
| EMA slow | 36-96 bars | 3-8 hours |
| MACD fast | 12-24 bars | Intraday calibrated |
| MACD slow | 24-52 bars | Intraday calibrated |

---

## Component Examples

### Entry with Session Context

```python
class entry_rule(BaseComponent):
    def __init__(self, trading_engine: ITradingEngine, **params):
        super().__init__(trading_engine, **params)
        self.rsi_period = self.params['rsi_period']
        self.or_breakout_threshold = self.params['or_breakout_threshold']

    def generate_signal(self) -> EntrySignalOutput:
        # Avoid entries during opening volatility (intraday only)
        if hasattr(self, 'is_opening_phase') and self.is_opening_phase():
            output = EntrySignalOutput(
                signal='HOLD',
                strength=0.0,
                type='hold_opening',
                entry_reason="Waiting for opening volatility to settle",
                intent=None
            )
            self.log_entry_output(output)
            return output

        # Opening range breakout (intraday only)
        if hasattr(self, 'get_opening_range'):
            or_high, or_low = self.get_opening_range()
            price = self.get_current_price()

            if or_high is not None and price > or_high * (1 + self.or_breakout_threshold):
                output = EntrySignalOutput(
                    signal='LONG',
                    strength=0.8,
                    type='entry_long',
                    entry_reason=f"Opening range breakout: {price:.2f} > OR high {or_high:.2f}",
                    intent=OrderIntent.ENTRY_LONG,
                    or_high=or_high,
                    or_low=or_low
                )
                self.log_entry_output(output)
                return output

        # Standard entry logic (works for all frequencies)
        rsi = self.get_indicator(f'rsi_{self.rsi_period}')
        # ... rest of entry logic
```

### Exit with EOD Close

```python
class exit_rule(BaseComponent):
    def __init__(self, trading_engine: ITradingEngine, **params):
        super().__init__(trading_engine, **params)
        self.eod_bars_threshold = self.params['eod_bars_threshold']  # e.g., 3
        self.atr_period = self.params['atr_period']

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

        # End-of-day close: Use get_bars_remaining() helper (DAY-level)
        bars_remaining = self.get_bars_remaining()
        if bars_remaining <= self.eod_bars_threshold:
            intent = OrderIntent.EXIT_LONG if position.direction == 'LONG' else OrderIntent.EXIT_SHORT
            output = ExitSignalOutput(
                should_exit=True,
                exit_reason=f"EOD close: {bars_remaining} bars remaining until day end",
                position_size=abs(position.size),
                bars_since_entry=self.bars_in_position,
                intent=intent
            )
            self.log_exit_output(output)
            return output

        # Skip trading during session breaks
        if self.is_session_break():
            output = ExitSignalOutput(
                should_exit=False,
                exit_reason='In session break - no exit action',
                position_size=abs(position.size),
                bars_since_entry=self.bars_in_position,
                intent=None
            )
            self.log_exit_output(output)
            return output

        # Standard exit logic (works for all frequencies)
        atr = self.get_indicator(f'atr_{self.atr_period}')
        # ... rest of exit logic
```

### Risk Manager with Session Awareness

```python
class risk_manager(BaseComponent):
    def __init__(self, trading_engine: ITradingEngine, **params):
        super().__init__(trading_engine, **params)
        self.block_opening_minutes = self.params['block_opening_minutes']  # e.g., 15

    def can_trade(self) -> RiskOutput:
        # Block new trades in first N minutes of session
        minutes_open = self.get_minutes_since_session_open()
        if minutes_open < self.block_opening_minutes:
            output = RiskOutput(
                trading_allowed=False,
                risk_reason=f"Opening period: {minutes_open} min < {self.block_opening_minutes} min threshold"
            )
            self.log_risk_output(output)
            return output

        # Block new trades during session breaks
        if self.is_session_break():
            output = RiskOutput(
                trading_allowed=False,
                risk_reason="Session break - no new trades"
            )
            self.log_risk_output(output)
            return output

        # Standard risk checks (works for all frequencies)
        output = RiskOutput(
            trading_allowed=True,
            risk_reason="All risk checks passed"
        )
        self.log_risk_output(output)
        return output
```

### Position Sizer with VWAP Reference

```python
class position_sizer(BaseComponent):
    def __init__(self, trading_engine: ITradingEngine, **params):
        super().__init__(trading_engine, **params)
        self.risk_per_trade = self.params['risk_per_trade']
        self.vwap_discount = self.params['vwap_discount']  # e.g., 0.8

    def calculate_size(self, signal_data: EntrySignalOutput) -> SizerOutput:
        if signal_data.signal == 'HOLD':
            output = SizerOutput(
                calculated_size=0,
                signal_direction='HOLD',
                sizing_reason='No sizing for HOLD signal',
                raw_size=0.0
            )
            self.log_sizer_output(output)
            return output

        portfolio_value = self.portfolio.get_total_value()
        current_price = self.get_current_price()

        # Reduce size when price is far from VWAP (intraday only)
        size_multiplier = 1.0
        if hasattr(self, 'get_vwap'):
            vwap = self.get_vwap()
            if vwap is not None:
                price_to_vwap = current_price / vwap
                if price_to_vwap > 1.02 or price_to_vwap < 0.98:
                    size_multiplier = self.vwap_discount

        risk_amount = portfolio_value * self.risk_per_trade
        raw_size = (risk_amount / current_price) * size_multiplier
        validated_size = self.validate_and_convert_position_size(raw_size)

        output = SizerOutput(
            calculated_size=validated_size,
            signal_direction=signal_data.signal,
            sizing_reason=f'Risk-based sizing with VWAP adjustment: {validated_size} contracts',
            raw_size=raw_size
        )
        self.log_sizer_output(output)
        return output
```

---

## Intraday-Specific Parameters

When generating `strategy_params.py` for intraday, include these parameter categories:

### Session Control Parameters

```python
# Opening phase control
'block_opening_minutes': ParameterSpec(
    min_value=5, max_value=30, default=15,
    description="Minutes to block new entries after session open"
),
'or_breakout_threshold': ParameterSpec(
    min_value=0.001, max_value=0.01, default=0.003,
    description="Opening range breakout threshold (0.3% = 0.003)"
),

# EOD control
'eod_bars_threshold': ParameterSpec(
    min_value=1, max_value=10, default=3,
    description="Bars before session end to flatten positions"
),
```

### VWAP Parameters

```python
'vwap_discount': ParameterSpec(
    min_value=0.5, max_value=1.0, default=0.8,
    description="Size multiplier when price deviates from VWAP"
),
```

---

## Best Practices

1. **CRITICAL: Always check has_pending_orders()** before submitting orders (see below)
2. **Always use hasattr() guards** for session methods
3. **Flatten positions before session end** to avoid overnight risk
4. **Respect session breaks** (SHFE) - no new entries during breaks
5. **VWAP is a key institutional benchmark** - use vwap_distance_pct for relative positioning
6. **Opening range is powerful** for breakout signals (or_breakout indicator)
7. **Consider session-specific behavior** (night vs day sessions differ)
8. **Period values are in BARS** - convert from time if needed (e.g., 1 hour = 12 bars for 5-min, 4 bars for 15-min)

---

## CRITICAL: Risk Flow & Exit Evaluation (Intraday Specific)

**Two critical bugs to avoid in intraday strategies:**

### Bug 1: Pending Order Accumulation

**Backtrader market orders execute at NEXT bar's open, not immediately.**

For intraday strategies with frequent bars (5m, 15m), this causes a critical bug if not handled:

```
Bar 1 (09:30): Entry signal → order submitted (PENDING)
Bar 2 (09:45): has_position()=False → ANOTHER order submitted
Bar 3 (10:00): has_position()=False → ANOTHER order submitted
... (orders accumulate)
Bar N: All orders execute → MASSIVE unintended position
```

**Solution**: Always check `has_pending_orders()` before submitting orders.

### Bug 2: Exit Logic Never Evaluated (Position Stuck Open)

**When `trading_allowed=False` due to position limits, exit logic MUST still run!**

```
FLAWED PATTERN (positions never close):
    if not risk_output.trading_allowed:
        return  ← EARLY RETURN - EXIT LOGIC NEVER REACHED!

    if not self.has_position():  # Entry
        ...
    elif self.has_position():    # Exit - NEVER REACHED when position limit!
        ...

Result: Position opened, position limit reached, exit logic skipped,
        position stays open forever (3+ years in backtest!)
```

**Solution**: Only return early for circuit breakers. For position limits, fall through to exit logic.

### Correct Risk Flow Pattern

```python
def _execute_bar(self):
    risk_output = self.risk_manager.can_trade()

    # CRITICAL: Circuit breaker handling - flatten positions if required
    # When drawdown or session loss limits are exceeded, MUST close existing positions
    if not risk_output.trading_allowed:
        constraint_type = getattr(risk_output, 'constraint_type', None)
        circuit_breaker_types = {'drawdown_limit', 'session_loss_circuit_breaker'}

        if constraint_type in circuit_breaker_types:
            # Circuit breaker triggered - flatten existing position immediately
            if self.has_position() and not self.has_pending_orders():
                if self.is_long_position():
                    self.exit(intent=OrderIntent.EXIT_LONG, size=abs(self.get_position_size()))
                elif self.is_short_position():
                    self.exit(intent=OrderIntent.EXIT_SHORT, size=abs(self.get_position_size()))
                self.log(f"Circuit breaker flatten: {constraint_type}")
            return  # Halt all activity after circuit breaker

        # Non-circuit-breaker (e.g., position_limit): block new entries but ALLOW exits
        # Fall through to exit logic below - exit component MUST still evaluate!

    # Entry: NO position AND NO pending orders AND trading allowed
    if risk_output.trading_allowed and not self.has_position() and not self.has_pending_orders():
        entry_signal = self.entry_rule.generate_signal()
        if entry_signal.signal != 'HOLD':
            sizer_output = self.position_sizer.calculate_size(entry_signal)
            if sizer_output.calculated_size > 0:
                self.entry(entry_signal.intent, sizer_output.calculated_size)

    # Exit: HAS position AND NO pending orders (ALWAYS evaluate, regardless of trading_allowed)
    elif self.has_position() and not self.has_pending_orders():
        exit_decision = self.exit_rule.should_exit()
        if exit_decision.should_exit:
            self.exit(exit_decision.intent)
```

**Risk Check Flow:**

| Scenario | New Entry | Exit Evaluation |
|----------|-----------|-----------------|
| `trading_allowed=True` | ✅ Allowed | ✅ Run exit rule |
| `trading_allowed=False` (position_limit) | ❌ Blocked | ✅ **Still run exit rule** |
| `trading_allowed=False` (circuit breaker) | ❌ Blocked | ⚡ **Force flatten immediately** |

**Circuit Breaker Types and Actions:**

| constraint_type | Action | Reason |
|-----------------|--------|--------|
| `drawdown_limit` | Flatten position + halt | Max drawdown exceeded - catastrophic risk |
| `session_loss_circuit_breaker` | Flatten position + halt | Session loss limit exceeded |
| `position_limit` | Block entries, allow exits | Already at max positions - exit rules still apply |

**Why interday strategies don't have this issue:**
- Daily bars = only 1 bar per day
- Order submitted Day 1 fills at Day 2 open
- By Day 2, `has_position()=True`, preventing duplicates

---

## CRITICAL: Position Sizing with Contract Multiplier

**For futures markets (SHFE, CME, etc.), position sizing MUST account for contract multiplier!**

### The Problem

Forgetting the multiplier causes **massive oversizing**:

```
SHFE Aluminum Example:
- Entry price: 17,855 CNY
- Stop distance: 35 CNY (ATR-based)
- Contract multiplier: 5 tons/contract

WRONG (missing multiplier):
  risk_per_contract = 35 CNY
  position_size = $2,000 / $35 = 57 contracts ← DANGEROUS!

CORRECT (with multiplier):
  risk_per_contract = 35 × 5 = 175 CNY
  position_size = $2,000 / $175 = 11 contracts ← CORRECT
```

### Correct Position Sizing Formula

```python
def calculate_size(self, signal_data: EntrySignalOutput) -> SizerOutput:
    # Get contract multiplier from market adapter
    multiplier = 1.0
    if self.market_adapter is not None:
        contract_spec = self.market_adapter.get_contract_spec(self.market_adapter.symbol)
        multiplier = contract_spec.multiplier

    # Calculate stop distance
    atr = self.get_indicator(f'atr_{self.atr_period}')
    stop_distance = atr * self.stop_atr_multiplier

    # CRITICAL: Include multiplier in risk calculation!
    risk_per_contract = stop_distance * multiplier

    # Calculate position size
    risk_amount = equity * (risk_pct / 100.0)
    raw_size = risk_amount / risk_per_contract

    # Validate
    validated_size = self.validate_and_convert_position_size(raw_size)
```

### Infrastructure Safety Net

The infrastructure (`BaseStrategy.entry()`) now includes a **margin-based position cap**:

```python
# In BaseStrategy.entry():
max_size = self.get_max_position_by_margin(current_price)
if size > max_size:
    self.log(f"POSITION SIZE CAPPED: {size} → {max_size}")
    size = max_size
```

This prevents catastrophic oversizing even if the sizer has bugs.

### Contract Multipliers by Market

| Market | Instrument | Multiplier | Example |
|--------|------------|------------|---------|
| SHFE | Aluminum (al) | 5 | 5 tons/contract |
| SHFE | Copper (cu) | 5 | 5 tons/contract |
| SHFE | Gold (au) | 1000 | 1000 grams/contract |
| Crypto | BTC-PERP | 1 | 1 BTC/contract |
| Crypto | ETH-PERP | 1 | 1 ETH/contract |
