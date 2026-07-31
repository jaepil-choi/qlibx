"""
Trading Interfaces
==================

Core trading interfaces that define contracts between strategy and platform.

Interfaces defined:
- ITradingEngine: Main engine interface combining all components
- IMarketData: Market data access (OHLCV, indicators, current bar)
- IPortfolio: Portfolio and position information
- IOrderManager: Order submission and management
- ILogger: Basic logging interface
- IStrategyLogger: Systematic strategy logging (Excel/CSV output)
- IEventBus: Event publishing for order fills and trade closures
- IStrategyCallbacks: Strategy lifecycle callbacks
- IMarketAdapter: Market-specific rules (SHFE, crypto, etc.)
- IFrequencyContext: Time scaling for different bar sizes

These interfaces are implemented by:
- Backtrader integration (for backtesting)
- MiniQMT integration (for SHFE live trading)
- CCXT integration (for crypto live trading)

The strategy layer only depends on these interfaces, not concrete implementations.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List, Callable, Tuple, TYPE_CHECKING
from datetime import datetime, date, time
from dataclasses import dataclass, field
from enum import Enum

from echolon.config.markets.core.context import TradingContext

if TYPE_CHECKING:
    from .market_adapter import IMarketAdapter
    from .frequency_context import IFrequencyContext
    from .session_context import ISessionContext


# ============================================================================
# Enumerations
# ============================================================================

class OrderSide(Enum):
    """Order side enumeration."""
    BUY = "BUY"
    SELL = "SELL"


class OrderType(Enum):
    """Order type enumeration."""
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    STOP_LIMIT = "STOP_LIMIT"


class OrderIntent(Enum):
    """Order intent enumeration to clarify order purpose."""
    ENTRY_LONG = "ENTRY_LONG"
    ENTRY_SHORT = "ENTRY_SHORT"
    EXIT_LONG = "EXIT_LONG"
    EXIT_SHORT = "EXIT_SHORT"
    ROLLOVER_CLOSE = "ROLLOVER_CLOSE"
    ROLLOVER_OPEN = "ROLLOVER_OPEN"
    FORCED_EXIT = "FORCED_EXIT"


class OrderStatus(Enum):
    """Order status enumeration."""
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    PARTIAL = "PARTIAL"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class PositionSide(Enum):
    """Position side enumeration."""
    LONG = "LONG"
    SHORT = "SHORT"
    FLAT = "FLAT"


# ============================================================================
# Data Classes
# ============================================================================

@dataclass
class Bar:
    """Single OHLCV bar data."""
    datetime: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    open_interest: Optional[float] = None

    def __post_init__(self):
        """Validate bar data."""
        if self.high < self.low:
            raise ValueError(f"High ({self.high}) cannot be less than low ({self.low})")
        if self.high < self.open or self.high < self.close:
            raise ValueError(f"High ({self.high}) must be >= open ({self.open}) and close ({self.close})")
        if self.low > self.open or self.low > self.close:
            raise ValueError(f"Low ({self.low}) must be <= open ({self.open}) and close ({self.close})")


@dataclass
class OrderResult:
    """Result of an order submission."""
    order_id: str
    status: OrderStatus
    message: Optional[str] = None
    intent: Optional[OrderIntent] = None

    @property
    def success(self) -> bool:
        """Convenience property: True if order was accepted/submitted (not rejected/cancelled)."""
        return self.status not in [OrderStatus.REJECTED, OrderStatus.CANCELLED]


@dataclass
class Order:
    """Full order representation."""
    order_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    size: float
    price: Optional[float] = None
    stop_price: Optional[float] = None
    intent: Optional[OrderIntent] = None
    status: OrderStatus = OrderStatus.PENDING
    filled_size: float = 0.0
    filled_price: float = 0.0
    commission: float = 0.0
    created_at: Optional[datetime] = None
    filled_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Position:
    """Current position information."""
    symbol: str
    size: float
    avg_price: float
    market_value: float
    unrealized_pnl: float
    realized_pnl: float
    direction: str  # "LONG", "SHORT", or "FLAT"

    entry_datetime: Optional[datetime] = None
    bars_held: int = 0
    current_price: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_long(self) -> bool:
        return self.direction == "LONG"


@dataclass
class Trade:
    """Completed trade information."""
    trade_id: str
    symbol: str
    side: OrderSide
    size: float
    entry_price: float
    exit_price: float
    entry_time: datetime
    exit_time: datetime
    pnl: float
    commission: float


@dataclass
class AccountInfo:
    """Account information."""
    equity: float
    cash: float
    margin_used: float
    margin_available: float
    unrealized_pnl: float
    realized_pnl: float
    currency: str = "CNY"


# ============================================================================
# Core Interfaces
# ============================================================================

class IMarketData(ABC):
    """Interface for accessing market data."""

    @abstractmethod
    def get_current_price(self) -> float:
        """Get current price for the main trading symbol."""
        pass

    @abstractmethod
    def get_current_bar(self) -> Dict[str, float]:
        """
        Get current OHLCV bar for the main trading symbol.

        Returns:
            Dict with keys: 'open', 'high', 'low', 'close', 'volume'
        """
        pass

    @abstractmethod
    def get_indicator(self, name: str, index: int = 0) -> float:
        """
        Get indicator value by name and index.

        Args:
            name: Indicator name (e.g., 'rsi', 'atr', 'macd')
            index: Bars back (0=current, 1=previous, etc.)

        Returns:
            Indicator value
        """
        pass

    @abstractmethod
    def get_contract_indicator(self, contract_name: str, trading_date: datetime,
                              indicator_name: str) -> Optional[float]:
        """
        Get indicator value for a specific contract on a specific date.

        Used for contract-specific calculations during rollovers.
        """
        pass

    @abstractmethod
    def get_bar_data(self, bars_back: int = 0) -> Dict[str, float]:
        """
        Get OHLCV data for specific bar.

        Args:
            bars_back: Number of bars back (0=current)

        Returns:
            Dict with keys: 'open', 'high', 'low', 'close', 'volume'
        """
        pass

    @abstractmethod
    def get_current_datetime(self) -> datetime:
        """Get current market datetime."""
        pass

    @abstractmethod
    def is_market_open(self) -> bool:
        """Check if market is currently open."""
        pass

    # Extended methods (new, but with default implementations)
    def get_current_date(self) -> date:
        """Get current market date."""
        return self.get_current_datetime().date()

    def get_open(self, index: int = 0) -> float:
        """Get open price, index bars back (0 = current)."""
        return self.get_bar_data(index)['open']

    def get_high(self, index: int = 0) -> float:
        """Get high price, index bars back (0 = current)."""
        return self.get_bar_data(index)['high']

    def get_low(self, index: int = 0) -> float:
        """Get low price, index bars back (0 = current)."""
        return self.get_bar_data(index)['low']

    def get_close(self, index: int = 0) -> float:
        """Get close price, index bars back (0 = current)."""
        return self.get_bar_data(index)['close']

    def get_volume(self, index: int = 0) -> float:
        """Get volume, index bars back (0 = current)."""
        return self.get_bar_data(index)['volume']

    def has_indicator(self, name: str) -> bool:
        """Check if indicator is available. Override in implementations."""
        return True

    def get_indicator_series(self, name: str, length: int) -> List[float]:
        """Get indicator series [oldest, ..., newest]."""
        return [self.get_indicator(name, length - 1 - i) for i in range(length)]

    def get_bars(self, length: int) -> List[Dict[str, float]]:
        """Get historical bars [oldest, ..., newest]."""
        return [self.get_bar_data(length - 1 - i) for i in range(length)]


class IPortfolio(ABC):
    """Interface for portfolio and account information."""

    @abstractmethod
    def get_total_value(self) -> float:
        """Get total portfolio value (cash + positions)."""
        pass

    @abstractmethod
    def get_cash(self) -> float:
        """Get available cash."""
        pass

    @abstractmethod
    def get_position(self) -> Optional[Position]:
        """
        Get the current position.

        Note: Old interface assumes single position trading.
        """
        pass

    @abstractmethod
    def get_all_positions(self) -> List[Position]:
        """Get all current positions (will contain zero or one position)."""
        pass

    @abstractmethod
    def get_realized_pnl(self) -> float:
        """Get total realized PnL."""
        pass

    @abstractmethod
    def get_unrealized_pnl(self) -> float:
        """Get total unrealized PnL."""
        pass

    # Extended methods (aliases and new functionality)
    def get_equity(self) -> float:
        """Alias for get_total_value()."""
        return self.get_total_value()

    def has_position(self, symbol: Optional[str] = None) -> bool:
        """Check if there's an open position."""
        pos = self.get_position()
        return pos is not None and pos.size != 0

    def get_position_size(self, symbol: Optional[str] = None) -> float:
        """Get position size (positive for long, negative for short, 0 for flat)."""
        pos = self.get_position()
        if pos is None:
            return 0.0
        if pos.direction == "SHORT":
            return -abs(pos.size)
        return pos.size

    def get_position_value(self, symbol: Optional[str] = None) -> float:
        """Get position value at current price."""
        pos = self.get_position()
        return pos.market_value if pos else 0.0

    def get_position_contract(self) -> Optional[str]:
        """Return the contract code of the currently held position, or None.

        Default implementation falls back to ``get_position().symbol`` and
        strips any exchange suffix (e.g. ``.SF``) so the returned code is
        directly usable by adapter rollover logic such as
        ``parse_contract(...)`` which expects the bare ``[a-z]+\\d{4}`` form.

        Sufficient for:
          - Crypto perpetuals (``symbol`` = e.g. 'BTC-PERP', no suffix)
          - Deploy SHFE via QMT, where ``Position.symbol`` carries the
            full QMT-formatted contract (``'al2602.SF'``) — this default
            strips ``.SF`` and returns ``'al2602'``.

        Markets where strategy-side ``symbol`` is the base instrument
        (backtest SHFE futures: ``symbol='al'`` while held contract is
        ``'al2602'``) MUST override to read the contract from the broker's
        position record (e.g. ``EnhancedPosition.contract`` via
        ``BacktraderPortfolio.get_position_contract``).
        """
        pos = self.get_position()
        if pos is None or not pos.symbol:
            return None
        sym = pos.symbol
        return sym.split('.', 1)[0] if '.' in sym else sym

    def get_account_info(self) -> AccountInfo:
        """Get account information."""
        return AccountInfo(
            equity=self.get_total_value(),
            cash=self.get_cash(),
            margin_used=0.0,
            margin_available=self.get_cash(),
            unrealized_pnl=self.get_unrealized_pnl(),
            realized_pnl=self.get_realized_pnl()
        )


class IOrderManager(ABC):
    """Interface for order management.

    Strategies submit entry/exit intent via ``submit_entry_order`` /
    ``submit_exit_order``.
    """

    @abstractmethod
    def submit_entry_order(self, direction: str, size: float,
                          price: Optional[float] = None) -> OrderResult:
        """
        Submit an order to enter a new position.

        Args:
            direction: "LONG" or "SHORT"
            size: Position size (contracts)
            price: Limit price (None for market order)

        Returns:
            OrderResult with order_id and status
        """
        pass

    @abstractmethod
    def submit_exit_order(self, size: float,
                         price: Optional[float] = None) -> OrderResult:
        """
        Submit an order to exit/reduce current position.

        Args:
            size: Size to exit (contracts)
            price: Limit price (None for market order)

        Returns:
            OrderResult with order_id and status
        """
        pass

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """Cancel an order."""
        pass

    @abstractmethod
    def get_order_status(self, order_id: str) -> OrderStatus:
        """Get order status."""
        pass

    # Extended methods (new, generic order submission)
    def submit_order(
        self,
        symbol: str,
        side: OrderSide,
        size: float,
        order_type: OrderType = OrderType.MARKET,
        price: Optional[float] = None,
        stop_price: Optional[float] = None,
        intent: Optional[OrderIntent] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Order:
        """
        Extended order submission with full control.

        Default implementation converts to entry/exit orders.
        Override in implementations for full functionality.
        """
        # Map to entry/exit based on intent
        if intent in (OrderIntent.ENTRY_LONG, OrderIntent.ENTRY_SHORT):
            direction = "LONG" if intent == OrderIntent.ENTRY_LONG else "SHORT"
            result = self.submit_entry_order(direction, size, price)
        else:
            result = self.submit_exit_order(size, price)

        return Order(
            order_id=result.order_id,
            symbol=symbol,
            side=side,
            order_type=order_type,
            size=size,
            price=price,
            stop_price=stop_price,
            intent=intent,
            status=result.status,
            metadata=metadata or {}
        )

    def get_order(self, order_id: str) -> Optional[Order]:
        """Get order by ID. Override for full implementation."""
        status = self.get_order_status(order_id)
        return Order(
            order_id=order_id,
            symbol="",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            size=0,
            status=status
        )

    def get_pending_orders(self, symbol: Optional[str] = None) -> List[Order]:
        """Get all pending orders. Override for full implementation."""
        return []

    def cancel_all_orders(self, symbol: Optional[str] = None) -> int:
        """Cancel all pending orders. Override for full implementation."""
        count = 0
        for order in self.get_pending_orders(symbol):
            if self.cancel_order(order.order_id):
                count += 1
        return count

    def close_position(
        self,
        symbol: Optional[str] = None,
        intent: OrderIntent = OrderIntent.EXIT_LONG,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[OrderResult]:
        """Close existing position. Requires position info from portfolio."""
        raise NotImplementedError("Override close_position in implementation")


class ILogger(ABC):
    """Interface for basic logging (info / warning / error / debug)."""

    @abstractmethod
    def info(self, message: str) -> None:
        """Log info message."""
        pass

    @abstractmethod
    def warning(self, message: str) -> None:
        """Log warning message."""
        pass

    @abstractmethod
    def error(self, message: str) -> None:
        """Log error message."""
        pass

    @abstractmethod
    def debug(self, message: str) -> None:
        """Log debug message."""
        pass

    # Extended methods (aliases for new naming convention)
    def log_info(self, message: str, **kwargs) -> None:
        """Alias for info()."""
        self.info(message)

    def log_warning(self, message: str, **kwargs) -> None:
        """Alias for warning()."""
        self.warning(message)

    def log_error(self, message: str, **kwargs) -> None:
        """Alias for error()."""
        self.error(message)

    def log_trade(
        self,
        action: str,
        symbol: str,
        side: OrderSide,
        size: float,
        price: float,
        reason: str,
        **kwargs
    ) -> None:
        """Log trade action."""
        self.info(f"TRADE: {action} {symbol} {side.value} {size}@{price} - {reason}")

    def log_signal(
        self,
        signal_type: str,
        direction: str,
        strength: float,
        reason: str,
        **kwargs
    ) -> None:
        """Log trading signal."""
        self.info(f"SIGNAL: {signal_type} {direction} strength={strength} - {reason}")

    def log_risk_event(
        self,
        event_type: str,
        details: str,
        **kwargs
    ) -> None:
        """Log risk management event."""
        self.warning(f"RISK: {event_type} - {details}")


class IStrategyLogger(ABC):
    """
    Interface for systematic strategy and component logging.

    Provides structured logging to Excel/CSV for detailed analysis.
    """

    @abstractmethod
    def log_strategy_state(self, strategy_state: Dict[str, Any]) -> None:
        """Log current strategy state."""
        pass

    @abstractmethod
    def log_component_output(self, component_name: str, output_data: Dict[str, Any]) -> None:
        """Log component output (entry signals, exit decisions, etc.)."""
        pass

    @abstractmethod
    def log_portfolio_state(self, portfolio_state: Dict[str, Any]) -> None:
        """Log current portfolio state."""
        pass

    @abstractmethod
    def log_order_event(self, order_data: Dict[str, Any]) -> None:
        """Log order submission or status change."""
        pass

    @abstractmethod
    def log_trade_event(self, trade_data: Dict[str, Any]) -> None:
        """Log trade execution."""
        pass

    @abstractmethod
    def finalize_logging(self) -> Optional[str]:
        """Finalize logging and return output file path if applicable."""
        pass


class IEventBus(ABC):
    """Interface for event handling via callback registration."""

    @abstractmethod
    def on_order_filled(self, callback: Callable) -> None:
        """Register callback for order filled events."""
        pass

    @abstractmethod
    def on_trade_closed(self, callback: Callable) -> None:
        """Register callback for trade closed events."""
        pass

    @abstractmethod
    def on_market_data_update(self, callback: Callable) -> None:
        """Register callback for market data updates."""
        pass

    # Extended methods (new subscription pattern)
    def subscribe(self, event_type: str, callback: Callable) -> None:
        """Subscribe to event type."""
        if event_type == "order_filled":
            self.on_order_filled(callback)
        elif event_type == "trade_closed":
            self.on_trade_closed(callback)
        elif event_type == "market_data_update":
            self.on_market_data_update(callback)

    def unsubscribe(self, event_type: str, callback: Callable) -> None:
        """Unsubscribe from event type. Override in implementations."""
        pass

    def publish(self, event_type: str, data: Any) -> None:
        """Publish event. Override in implementations."""
        pass


# ============================================================================
# Strategy Callbacks Interface
# ============================================================================

class IStrategyCallbacks(ABC):
    """
    Interface for strategy lifecycle callbacks.

    Implemented by platform-agnostic strategies.
    """

    @abstractmethod
    def on_start(self) -> None:
        """Called when strategy starts."""
        pass

    @abstractmethod
    def on_bar(self) -> None:
        """Called on each new bar."""
        pass

    @abstractmethod
    def on_order_update(self, order_id: str, status: OrderStatus) -> None:
        """Called when order status changes."""
        pass

    @abstractmethod
    def on_trade_closed(self, trade: Trade) -> None:
        """Called when a trade is closed."""
        pass

    @abstractmethod
    def on_stop(self) -> None:
        """Called when strategy stops."""
        pass


# ============================================================================
# Main Trading Engine Interface
# ============================================================================

class ITradingEngine(ABC):
    """
    Main trading engine interface that combines all components.
    """

    @abstractmethod
    def get_market_data(self) -> IMarketData:
        """Get market data interface."""
        pass

    @abstractmethod
    def get_portfolio(self) -> IPortfolio:
        """Get portfolio interface."""
        pass

    @abstractmethod
    def get_order_manager(self) -> IOrderManager:
        """Get order manager interface."""
        pass

    @abstractmethod
    def get_logger(self) -> ILogger:
        """Get logger interface."""
        pass

    @abstractmethod
    def get_strategy_logger(self) -> Optional[IStrategyLogger]:
        """Get strategy logger interface (may be None for optimization runs)."""
        pass

    @abstractmethod
    def get_event_bus(self) -> IEventBus:
        """Get event bus interface."""
        pass

    # Default-None getters — concrete engines may not provide every component.
    def get_market_adapter(self) -> Optional['IMarketAdapter']:
        """Get market-specific adapter (SHFE, crypto, etc.). May be None."""
        return None

    def get_frequency_context(self) -> Optional['IFrequencyContext']:
        """Get frequency context for time scaling. May be None."""
        return None

    def get_config(self) -> Dict[str, Any]:
        """Get trading configuration."""
        return {}

    def get_current_symbol(self) -> str:
        """Get current trading symbol."""
        return ""

    def get_session_context_provider(self) -> Optional['ISessionContext']:
        """
        Get session context provider for intraday trading.

        Returns ISessionContext implementation that provides:
        - Session phase (night, morning, afternoon)
        - Bar position within session (bar_of_session, bars_remaining)
        - Session-aware indicators (VWAP, Opening Range, Session Levels)
        - Gap context and trading constraints

        May be None for daily-only strategies that don't need session context.
        """
        return None

    def get_trading_context(self) -> Optional[TradingContext]:
        """
        Get trading context with market/instrument configuration.

        Returns TradingContext containing:
        - Market configuration (SHFE, CRYPTO, etc.)
        - Instrument specification (al, btc, etc.)
        - Frequency and bar_size info
        - Market-specific methods (encode_phase, decode_phase, etc.)

        This is the preferred way to access market-specific functionality
        in a market-agnostic manner. May be None when an engine implementation
        does not supply a TradingContext.
        """
        return None
