# Trading API Interfaces Reference

## Common pitfalls — read this BEFORE writing any component code

These are real mistakes seen in agent-generated components. Every one of
them looks like a confident match against common Python patterns from
training data, but each one crashes at runtime. Verify against the
signatures below; if uncertain, call the `describe_component_api` MCP
tool for the live signature.

| ❌ Wrong | ✅ Right | Why |
|---|---|---|
| `self.current_bar` | `self.get_current_bar()` | `current_bar` is **not an attribute**. The interface exposes a method. |
| `bar.close`, `bar.high` | `bar['close']`, `bar['high']` | `get_current_bar()` returns a `Dict[str, float]`, not an object. Keys: `'open'`, `'high'`, `'low'`, `'close'`, `'volume'`. |
| `self.bar_index` | Track manually with a per-trade counter you maintain | **No `bar_index` attribute exists.** If you need bars-held, increment a counter inside your component and reset it on flat. |
| `self.indicators['rsi_14']` | `self.get_indicator('rsi_14')` | Indicators are accessed via a method, never via a dict on `self`. |
| `self.params.get('foo', 0)` | `self.get_param('foo')` or read `self.params['foo']` directly | Defensive `.get()` with defaults is a framework violation (PRM-004). Params are guaranteed present per the contract. |
| `try/except` around any framework call | Let it raise | The "no error handling" policy is enforced by validators. |

The `describe_component_api` MCP tool returns the live `BaseComponent` /
`IMarketData` API via Python `inspect`, so it cannot drift from the
codebase — useful when this table doesn't cover your specific question.

## Complete Interface Specifications

### ITradingEngine

Main interface providing access to all trading system components.

```python
class ITradingEngine(ABC):
    """Main trading engine interface that combines all components."""

    @abstractmethod
    def get_market_data(self) -> IMarketData:
        """Get market data interface."""

    @abstractmethod
    def get_portfolio(self) -> IPortfolio:
        """Get portfolio interface."""

    @abstractmethod
    def get_order_manager(self) -> IOrderManager:
        """Get order manager interface."""

    @abstractmethod
    def get_logger(self) -> ILogger:
        """Get logger interface."""

    @abstractmethod
    def get_strategy_logger(self) -> Optional[IStrategyLogger]:
        """Get strategy logger interface."""
```

### IMarketData

```python
class IMarketData(ABC):
    """Interface for accessing market data."""

    @abstractmethod
    def get_current_price(self) -> float:
        """Get current price for the main trading symbol."""

    @abstractmethod
    def get_current_bar(self) -> Dict[str, float]:
        """Get current OHLCV bar: {'open', 'high', 'low', 'close', 'volume'}."""

    @abstractmethod
    def get_indicator(self, name: str, index: int = 0) -> float:
        """Get indicator value by name and index (0=current, 1=previous, etc.)."""

    @abstractmethod
    def get_current_datetime(self) -> datetime:
        """Get current market datetime."""
```

### IPortfolio

```python
class IPortfolio(ABC):
    """Interface for portfolio and account information."""

    @abstractmethod
    def get_total_value(self) -> float:
        """Get total portfolio value."""

    @abstractmethod
    def get_cash(self) -> float:
        """Get available cash."""

    @abstractmethod
    def get_position(self) -> Optional[Position]:
        """Get the current position (single position only)."""
```

### IOrderManager

```python
class IOrderManager(ABC):
    """Interface for order management."""

    @abstractmethod
    def submit_entry_order(self, direction: str, size: float, price: Optional[float] = None) -> OrderResult:
        """Submit an order to enter a new position.

        Args:
            direction: 'LONG' or 'SHORT'
            size: Number of contracts/shares
            price: Limit price (None for market order)
        """

    @abstractmethod
    def submit_exit_order(self, direction: str, size: float, price: Optional[float] = None) -> OrderResult:
        """Submit an order to exit/reduce current position.

        Args:
            direction: 'LONG' or 'SHORT' (the position direction being exited)
            size: Number of contracts/shares to exit
            price: Limit price (None for market order)
        """
```

### IStrategyLogger

```python
class IStrategyLogger(ABC):
    """Interface for systematic strategy and component logging."""

    @abstractmethod
    def log_strategy_state(self, strategy_state: Dict[str, Any]) -> None:
        """Log current strategy state."""

    @abstractmethod
    def log_component_output(self, component_name: str, output_data: Dict[str, Any]) -> None:
        """Log component output (entry signals, exit decisions, etc.)."""

    @abstractmethod
    def log_portfolio_state(self, portfolio_state: Dict[str, Any]) -> None:
        """Log current portfolio state."""

    @abstractmethod
    def log_order_event(self, order_data: Dict[str, Any]) -> None:
        """Log order submission or status change."""

    @abstractmethod
    def finalize_logging(self) -> Optional[str]:
        """Finalize logging and return output file path if applicable."""
```

## Order Enums

```python
class OrderIntent(Enum):
    ENTRY_LONG = "ENTRY_LONG"     # Open a new long position
    ENTRY_SHORT = "ENTRY_SHORT"   # Open a new short position
    EXIT_LONG = "EXIT_LONG"       # Close/reduce existing long position
    EXIT_SHORT = "EXIT_SHORT"     # Close/reduce existing short position

class OrderStatus(Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"

@dataclass
class OrderResult:
    order_id: str
    status: OrderStatus
    message: Optional[str] = None
    intent: Optional[OrderIntent] = None
```

## Position Object

```python
@dataclass
class Position:
    symbol: str           # Trading symbol
    size: float          # Position size (positive=long, negative=short)
    avg_price: float     # Average entry price
    market_value: float  # Current market value
    unrealized_pnl: float # Unrealized profit/loss
    realized_pnl: float  # Realized profit/loss
    direction: str       # 'LONG' or 'SHORT'
```

## Output BaseModels

All schemas use **Pydantic v2** with `model_config = ConfigDict(extra="allow",
arbitrary_types_allowed=True)`. Strategy-specific diagnostic fields
(e.g., `cci_value`, `rsi_value`, `atr_value`) are accepted on every output
type — see echolon commit `8d64c43` for the schema fix that restored this
after a silent-failure regression (`extra='forbid'` was blocking legitimate
diagnostic extras emitted by real strategies).

### EntrySignalOutput

```python
class EntrySignalOutput(BaseModel):
    """Entry component output. signal, strength, type, entry_reason are REQUIRED."""
    signal: Literal['LONG', 'SHORT', 'HOLD']        # required
    strength: float                                  # required, 0.0 <= x <= 1.0
    type: str                                        # required, e.g., 'entry_long'
    entry_reason: str                                # required
    intent: Optional[OrderIntent] = None             # optional (None for HOLD)
    regime: Optional[str] = None                     # optional: TRS-paradigm strategies populate
                                                     # via self.get_market_regime() / get_session_phase();
                                                     # TSMOM and other paradigms typically leave None.

    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)
```

### ExitSignalOutput

```python
class ExitSignalOutput(BaseModel):
    """Exit component output."""
    should_exit: bool
    exit_reason: str
    position_size: float  # Current position size
    bars_since_entry: int  # Bars since entry
    intent: Optional[OrderIntent] = None

    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)
```

### RiskOutput

```python
class RiskOutput(BaseModel):
    """Risk manager output."""
    trading_allowed: bool
    risk_reason: str

    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)
```

### SizerOutput

```python
class SizerOutput(BaseModel):
    """Position sizer output."""
    calculated_size: int  # Auto-validates: >= 0
    signal_direction: Literal['LONG', 'SHORT', 'HOLD']
    sizing_reason: str
    raw_size: float  # Pre-validation float value

    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)
```

## BaseComponent Methods

```python
class BaseComponent(ABC):
    """Platform-agnostic base component class."""

    # Helper methods
    def get_current_price(self) -> float: ...
    def get_current_bar(self) -> Dict[str, float]: ...
    def get_indicator(self, name: str, index: int = 0) -> float: ...
    def get_market_regime(self, index: int = 0) -> str: ...  # INTERDAY ONLY
    def get_session_phase(self, index: int = 0) -> str: ...  # INTRADAY ONLY
    def has_position(self) -> bool: ...

    # Position size validation (for Sizer)
    def validate_and_convert_position_size(self, calculated_size: float) -> int:
        """Validate and convert to non-negative integer."""

    # Logging methods (type-specific)
    def log_entry_output(self, output_data: EntrySignalOutput): ...
    def log_exit_output(self, output_data: ExitSignalOutput): ...
    def log_sizer_output(self, output_data: SizerOutput): ...
    def log_risk_output(self, output_data: RiskOutput): ...
```

## BaseStrategy Methods (Strategy Coordinator)

```python
class BaseStrategy:
    """Platform-agnostic base strategy class."""

    # Position state
    def has_position(self) -> bool: ...
    def has_pending_orders(self) -> bool:
        """
        CRITICAL: Check before submitting orders (especially intraday).
        Backtrader orders execute at NEXT bar's open, not immediately.
        Without this guard, consecutive bars submit multiple orders.
        """
    def is_long_position(self) -> bool: ...
    def is_short_position(self) -> bool: ...
    def get_position_size(self) -> float: ...

    # Order submission
    def entry(self, intent: OrderIntent, size: float, price: float = None) -> OrderResult: ...
    def exit(self, intent: OrderIntent, size: float = None, price: float = None) -> OrderResult: ...
```

## State Persistence Pattern

Exit and other stateful components should track state for live trading:

```python
class exit_rule(BaseComponent):
    def __init__(self, trading_engine: ITradingEngine, **params):
        super().__init__(trading_engine, **params)
        # State variables for persistence
        self.stop_price = None
        self.take_profit_price = None
        self.bars_in_position = 0

    def _get_component_specific_state(self) -> Dict[str, Any]:
        """Return exit-specific state for persistence."""
        return {
            'stop_price': self.stop_price,
            'take_profit_price': self.take_profit_price,
            'bars_in_position': self.bars_in_position
        }

    def _restore_component_specific_state(self, state: Dict[str, Any]) -> None:
        """Restore exit-specific state from persistence."""
        self.stop_price = state['stop_price']
        self.take_profit_price = state['take_profit_price']
        self.bars_in_position = state['bars_in_position']

    def _reset_state(self) -> None:
        """Reset all per-trade state to initial values.
        MUST reset every variable from _get_component_specific_state()."""
        self.stop_price = None
        self.take_profit_price = None
        self.bars_in_position = 0
```

### State Management Trio

Stateful components (especially exit_rule) must implement three methods:

| Method | Purpose |
|--------|---------|
| `_get_component_specific_state()` | Save per-trade state to dict |
| `_restore_component_specific_state()` | Load per-trade state from dict |
| `_reset_state()` | Clear per-trade state to initial values |

**Rule**: `_reset_state()` resets **per-trade** state only (stop prices, take-profit levels, bar counters, entry tracking). **Cross-trade** state (consecutive_losses, circuit_breaker, equity high-water marks) must NOT be reset — these persist across trades.

**Usage in exit components**: Call `self._reset_state()` inside `should_exit()` when position is None or size == 0. This ensures clean state for the next trade in both backtest and deploy modes. The deploy infrastructure also calls it externally after exit fills for state file consistency.
