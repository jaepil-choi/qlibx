"""
Backtrader Engine
=================

Backtrader platform integration implementing ITradingEngine.

Wraps Backtrader's Cerebro engine and provides ITradingEngine interface
so strategy code can run without knowing it's in a backtest.

Architecture:
    BacktraderEngine provides CORE backtrader mechanics only.
    Market-specific and frequency-specific features are added via HOOKS.

    Hooks (added by EngineFactory based on trading mode):
    - ContractAwareHook: For interday futures (contract rollover)
    - SessionAwareHook: For intraday trading (session context)

Components created:
- BacktraderMarketData: Implements IMarketData using bt.feeds
- BacktraderPortfolio: Implements IPortfolio using bt.broker
- BacktraderOrderManager: Implements IOrderManager using bt.order
- BacktraderLogger: Implements ILogger for strategy logging
- BacktraderEventBus: Implements IEventBus for order/trade events

Constructor parameters:
- config: Trading configuration from state.json
- market_adapter: IMarketAdapter for market-specific rules
- frequency_context: IFrequencyContext for time scaling

Key methods:
- add_hook(hook): Add engine hook for customization
- setup(data_feed, strategy_class, params): Configure backtest
- run(): Execute backtest and return results
- get_market_data(), get_portfolio(), etc.: ITradingEngine interface

Hook lifecycle:
1. add_hook() -> hook.on_init(engine)
2. setup() -> hook.on_setup(cerebro, engine)
3. setup() -> hook.on_post_setup(cerebro, engine)
4. run() -> hook.on_pre_run(engine)
5. run() -> hook.on_post_run(engine, strategy, results)
"""

from typing import Dict, Any, Optional, List, Callable, Type, TYPE_CHECKING
from datetime import datetime, date
from dataclasses import dataclass, field
import logging

import pandas as pd
import backtrader as bt
from echolon.strategy.interfaces import (
    ITradingEngine,
    IMarketData,
    IPortfolio,
    IOrderManager,
    ILogger,
    IEventBus,
    IStrategyLogger,
    Bar,
    Order,
    OrderResult,
    Position,
    AccountInfo,
    OrderSide,
    OrderType,
    OrderIntent,
    OrderStatus,
    PositionSide,
)
from echolon.strategy.frequency.interface import IFrequencyContext, FrequencyType
from echolon.markets.interface import IMarketAdapter
from echolon.strategy.frequency.session_interface import ISessionContext, SessionContext
from echolon.strategy.frequency.session_context_provider import BaseSessionContextProvider
from echolon.strategy.logging import CSVStrategyLogger, NullStrategyLogger

# Analyzers
from echolon.backtest.metrics.analyzers import add_analyzers, extract_analysis_results

# Hook interface
from .hooks.base import IEngineHook

from echolon.config.markets.core.context import TradingContext

if TYPE_CHECKING:
    from echolon.data.loaders.contract_loader import ContractIndicatorManager
logger = logging.getLogger(__name__)


@dataclass
class BacktestResults:
    """Results from a backtest run."""
    final_value: float
    initial_value: float
    total_return: float
    sharpe_ratio: Optional[float] = None
    max_drawdown: Optional[float] = None
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    analyzers: Dict[str, Any] = field(default_factory=dict)
    trade_history: List[Dict[str, Any]] = field(default_factory=list)


class BacktraderMarketData(IMarketData):
    """IMarketData implementation for Backtrader.

    Methods:
    - ``get_current_price()``: current close price
    - ``get_current_bar()``: Dict[str, float] (not a Bar object)
    - ``get_indicator(name, index)``: indicator value at offset (0=current, 1=previous)
    - ``get_contract_indicator()``: contract-specific indicator access
    - ``get_bar_data(bars_back)``: historical bar as dict
    - ``is_market_open()``: always True in backtest

    Intraday helpers:
    - ``get_session_context()``: complete session context for current bar
    - ``get_vwap()``: session VWAP
    - ``get_opening_range()``: opening range high/low
    """

    def __init__(
        self,
        data_feed: 'bt.feeds.DataBase',
        indicators: Dict[str, 'bt.Indicator'] = None,
        contract_indicators: Dict[str, Dict[str, Any]] = None,
        session_context_provider: Optional[ISessionContext] = None,
    ):
        """
        Initialize with Backtrader data feed.

        Args:
            data_feed: Backtrader data feed
            indicators: Dictionary of indicator name -> bt.Indicator
            contract_indicators: Dictionary of contract_date -> indicator_name -> value
            session_context_provider: Optional provider for session context (intraday)
        """
        self._data = data_feed
        self._indicators = indicators or {}
        self._contract_indicators = contract_indicators or {}
        self._session_context_provider = session_context_provider

    def set_data_feed(self, data_feed: 'bt.feeds.DataBase') -> None:
        """Update the data feed reference."""
        self._data = data_feed

    def register_indicator(self, name: str, indicator: 'bt.Indicator') -> None:
        """Register an indicator for access."""
        self._indicators[name.lower()] = indicator

    def set_contract_indicators(self, contract_indicators: Dict[str, Dict[str, Any]]) -> None:
        """Set contract-specific indicators for rollover calculations."""
        self._contract_indicators = contract_indicators

    def set_session_context_provider(self, provider: ISessionContext) -> None:
        """Set session context provider for intraday trading."""
        self._session_context_provider = provider

    # ========================================================================
    # IMarketData methods
    # ========================================================================

    def get_current_price(self) -> float:
        """Get current price for the main trading symbol (close price)."""
        return self._data.close[0]

    def get_current_bar(self) -> Dict[str, float]:
        """
        Get current OHLCV bar for the main trading symbol.

        Returns:
            Dict with keys: 'open', 'high', 'low', 'close', 'volume', 'datetime'
        """
        return {
            'open': self._data.open[0],
            'high': self._data.high[0],
            'low': self._data.low[0],
            'close': self._data.close[0],
            'volume': self._data.volume[0],
            'datetime': self._data.datetime.datetime(0),
        }

    def get_indicator(self, name: str, index: int = 0) -> float:
        """
        Get indicator value by name and index.

        Args:
            name: Indicator name (case-insensitive)
            index: Bars back (0=current, 1=previous, etc.)

        Returns:
            Indicator value
        """
        name_lower = name.lower()
        if name_lower not in self._indicators:
            raise KeyError(f"Indicator not found: {name}")
        return self._indicators[name_lower][-index]

    def get_contract_indicator(self, contract_name: str, trading_date: datetime,
                              indicator_name: str) -> Optional[float]:
        """
        Get indicator value for a specific contract on a specific date.

        Used for contract-specific calculations during rollovers.
        """
        date_key = trading_date.strftime('%Y-%m-%d') if isinstance(trading_date, datetime) else str(trading_date)
        contract_key = f"{contract_name}_{date_key}"

        if contract_key in self._contract_indicators:
            return self._contract_indicators[contract_key].get(indicator_name.lower())
        return None

    def get_bar_data(self, bars_back: int = 0) -> Dict[str, float]:
        """
        Get OHLCV data for specific bar.

        Args:
            bars_back: Number of bars back (0=current, 1=previous, etc.)

        Returns:
            Dict with keys: 'open', 'high', 'low', 'close', 'volume'
        """
        return {
            'open': self._data.open[-bars_back],
            'high': self._data.high[-bars_back],
            'low': self._data.low[-bars_back],
            'close': self._data.close[-bars_back],
            'volume': self._data.volume[-bars_back],
        }

    def get_current_datetime(self) -> datetime:
        """Get current market datetime."""
        return self._data.datetime.datetime(0)

    def get_current_date(self) -> date:
        """Get current date."""
        return self._data.datetime.date(0)

    def is_market_open(self) -> bool:
        """Check if market is currently open. Always True in backtest."""
        return True

    # ========================================================================
    # OHLC accessors (index = bars back; 0 = current)
    # ========================================================================

    def get_open(self, index: int = 0) -> float:
        """Get open price, index bars back (0 = current)."""
        return self._data.open[-index]

    def get_high(self, index: int = 0) -> float:
        """Get high price, index bars back (0 = current)."""
        return self._data.high[-index]

    def get_low(self, index: int = 0) -> float:
        """Get low price, index bars back (0 = current)."""
        return self._data.low[-index]

    def get_close(self, index: int = 0) -> float:
        """Get close price, index bars back (0 = current)."""
        return self._data.close[-index]

    def get_volume(self, index: int = 0) -> float:
        """Get volume, index bars back (0 = current)."""
        return self._data.volume[-index]

    def get_indicator_series(self, name: str, length: int) -> List[float]:
        """Get indicator series [oldest, ..., newest]."""
        name_lower = name.lower()
        if name_lower not in self._indicators:
            raise KeyError(f"Indicator not found: {name}")
        indicator = self._indicators[name_lower]
        return [indicator[-(length - 1 - i)] for i in range(length)]

    def has_indicator(self, name: str) -> bool:
        """Check if indicator exists."""
        return name.lower() in self._indicators

    def get_bars(self, length: int) -> List[Dict[str, float]]:
        """Get historical bars as list of dicts [oldest, ..., newest]."""
        bars = []
        for i in range(length - 1, -1, -1):
            bars.append({
                'open': self._data.open[-i],
                'high': self._data.high[-i],
                'low': self._data.low[-i],
                'close': self._data.close[-i],
                'volume': self._data.volume[-i],
                'datetime': self._data.datetime.datetime(-i),
            })
        return bars

    def get_current_bar_object(self) -> Bar:
        """Get the current bar as Bar object (for new code)."""
        return Bar(
            datetime=self._data.datetime.datetime(0),
            open=self._data.open[0],
            high=self._data.high[0],
            low=self._data.low[0],
            close=self._data.close[0],
            volume=self._data.volume[0],
            open_interest=getattr(self._data, 'openinterest', [0])[0] if hasattr(self._data, 'openinterest') else None
        )

    # ========================================================================
    # SESSION CONTEXT METHODS (for intraday trading)
    # ========================================================================

    def get_session_context(self) -> Optional[SessionContext]:
        """
        Get complete session context for current bar.

        Returns SessionContext with:
        - session_type: 'night' or 'day'
        - session_phase: 'night', 'morning', 'afternoon', etc.
        - bar_of_session: 0-indexed position
        - bars_remaining: bars until session end
        - is_opening_phase, is_closing_phase: boundary flags
        - gap_pct: gap from previous session
        - or_high, or_low, or_defined: opening range
        - session_high, session_low: session levels
        - vwap: session VWAP

        Returns None if no session context provider is configured.
        """
        if self._session_context_provider is None or self._data is None:
            return None

        current_time = self._data.datetime.datetime(0)
        ctx = self._session_context_provider.get_session_context(current_time)

        # Set current price for price-relative calculations
        ctx.current_price = self._data.close[0]

        return ctx

    def get_vwap(self) -> Optional[float]:
        """
        Get session VWAP (Volume Weighted Average Price).

        VWAP resets at trading day boundary (21:00 for SHFE).

        Returns None if session context not available.
        """
        ctx = self.get_session_context()
        return ctx.vwap if ctx else None

    def get_opening_range(self) -> tuple:
        """
        Get opening range high and low.

        Returns:
            Tuple of (OR high, OR low) or (None, None) if not defined
        """
        ctx = self.get_session_context()
        if ctx and ctx.or_defined:
            return (ctx.or_high, ctx.or_low)
        return (None, None)

    def get_bar_of_session(self) -> int:
        """
        Get current bar position within session (0-indexed).

        Returns 0 if session context not available.
        """
        ctx = self.get_session_context()
        return ctx.bar_of_session if ctx else 0

    def get_bars_remaining_in_session(self) -> int:
        """
        Get bars remaining until SESSION end (not day end).

        Returns 0 if session context not available.
        """
        ctx = self.get_session_context()
        return ctx.bars_remaining_in_session if ctx else 0

    def is_opening_phase(self) -> bool:
        """Check if within opening phase of session."""
        ctx = self.get_session_context()
        return ctx.is_opening_phase if ctx else False

    def is_closing_phase(self) -> bool:
        """Check if within closing phase of session."""
        ctx = self.get_session_context()
        return ctx.is_closing_phase if ctx else False

    def get_minutes_since_session_open(self) -> int:
        """Get minutes since current session started."""
        ctx = self.get_session_context()
        return ctx.minutes_since_session_open if ctx else 0

    def get_minutes_to_session_close(self) -> int:
        """Get minutes until current session ends."""
        ctx = self.get_session_context()
        return ctx.minutes_to_session_close if ctx else 0

    def get_minutes_to_next_session(self) -> Optional[int]:
        """Get minutes until next session (None if in session)."""
        ctx = self.get_session_context()
        return ctx.minutes_to_next_session if ctx else None

    def get_session_index(self) -> int:
        """Get 0-based index of current session."""
        ctx = self.get_session_context()
        return ctx.session_index if ctx else 0

    def is_first_session(self) -> bool:
        """Check if in first session of trading day."""
        ctx = self.get_session_context()
        return ctx.is_first_session if ctx else False

    def is_last_session(self) -> bool:
        """Check if in last session of trading day."""
        ctx = self.get_session_context()
        return ctx.is_last_session if ctx else False

    def is_session_break(self) -> bool:
        """Check if in a session break (lunch, morning break)."""
        ctx = self.get_session_context()
        return ctx.is_session_break if ctx else True

    def update_session_context(self) -> None:
        """
        Update session context with current bar data.

        Called internally on each bar to update session state
        (session high/low, VWAP, opening range, etc.)
        """
        if self._session_context_provider is None or self._data is None:
            return

        current_time = self._data.datetime.datetime(0)
        high = self._data.high[0]
        low = self._data.low[0]
        close = self._data.close[0]
        volume = self._data.volume[0]

        self._session_context_provider.update_bar(
            current_time=current_time,
            high=high,
            low=low,
            close=close,
            volume=volume,
        )


class BacktraderPortfolio(IPortfolio):
    """IPortfolio implementation for Backtrader.

    Methods:
    - ``get_total_value()``: total portfolio value
    - ``get_cash()``: available cash
    - ``get_position()``: Position with ``direction`` ("LONG"/"SHORT"/"FLAT")
    - ``get_all_positions()``: list of positions
    - ``get_realized_pnl()``: total realized PnL
    - ``get_unrealized_pnl()``: total unrealized PnL
    """

    def __init__(
        self,
        broker: 'bt.BrokerBase',
        data_feed: 'bt.feeds.DataBase',
        initial_cash: float = 100000.0
    ):
        """
        Initialize with Backtrader broker.

        Args:
            broker: Backtrader broker instance
            data_feed: Main data feed for symbol
            initial_cash: Initial cash for account info
        """
        self._broker = broker
        self._data = data_feed
        self._initial_cash = initial_cash
        self._symbol = ""
        self._realized_pnl = 0.0  # Track realized PnL separately

    def set_broker(self, broker: 'bt.BrokerBase') -> None:
        """Update broker reference."""
        self._broker = broker

    def set_data_feed(self, data_feed: 'bt.feeds.DataBase') -> None:
        """Update data feed reference."""
        self._data = data_feed

    def set_symbol(self, symbol: str) -> None:
        """Set trading symbol."""
        self._symbol = symbol

    def add_realized_pnl(self, pnl: float) -> None:
        """Add to realized PnL when a trade closes."""
        self._realized_pnl += pnl

    # ========================================================================
    # IMarketData methods
    # ========================================================================

    def get_total_value(self) -> float:
        """Get total portfolio value (cash + positions)."""
        return self._broker.getvalue()

    def get_cash(self) -> float:
        """Get available cash."""
        return self._broker.getcash()

    def get_position(self) -> Optional[Position]:
        """
        Get the current position.

        Returns Position with OLD field names:
        - direction: "LONG", "SHORT", or "FLAT"
        - avg_price: Average entry price
        - market_value: Current market value
        """
        bt_position = self._broker.getposition(self._data)

        if bt_position.size == 0:
            return None

        current_price = self._data.close[0]
        entry_price = bt_position.price
        size = abs(bt_position.size)
        direction = "LONG" if bt_position.size > 0 else "SHORT"

        # Calculate unrealized PnL
        if direction == "LONG":
            unrealized_pnl = (current_price - entry_price) * size
        else:
            unrealized_pnl = (entry_price - current_price) * size

        market_value = size * current_price

        return Position(
            symbol=self._symbol,
            size=size,
            avg_price=entry_price,
            market_value=market_value,
            unrealized_pnl=unrealized_pnl,
            realized_pnl=self._realized_pnl,
            direction=direction,
            current_price=current_price,
        )

    def get_all_positions(self) -> List[Position]:
        """Get all current positions (will contain zero or one position)."""
        pos = self.get_position()
        return [pos] if pos else []

    def get_realized_pnl(self) -> float:
        """Get total realized PnL."""
        # Calculate from portfolio value change minus unrealized
        equity = self._broker.getvalue()
        unrealized = self.get_unrealized_pnl()
        return equity - self._initial_cash - unrealized

    def get_unrealized_pnl(self) -> float:
        """Get total unrealized PnL."""
        pos = self.get_position()
        return pos.unrealized_pnl if pos else 0.0

    # ========================================================================
    # EXTENDED METHODS (aliases and new functionality)
    # ========================================================================

    def get_equity(self) -> float:
        """Alias for get_total_value()."""
        return self.get_total_value()

    def has_position(self, symbol: Optional[str] = None) -> bool:
        """Check if there's a position."""
        bt_position = self._broker.getposition(self._data)
        return bt_position.size != 0

    def get_position_size(self, symbol: Optional[str] = None) -> float:
        """Get position size (positive for long, negative for short, 0 for flat)."""
        bt_position = self._broker.getposition(self._data)
        return bt_position.size

    def get_position_value(self, symbol: Optional[str] = None) -> float:
        """Get position value at current price."""
        bt_position = self._broker.getposition(self._data)
        if bt_position.size == 0:
            return 0.0
        return abs(bt_position.size) * self._data.close[0]

    def get_position_contract(self) -> Optional[str]:
        """Return the actual held contract code (e.g. 'al2602'), not the
        base instrument symbol.

        For SHFE futures backtest: ContractAwareBroker stores the held
        contract on EnhancedPosition.contract (set when the position was
        opened). Read it from there so ForcedExitStrategyHook can ask the
        adapter about the *held* contract's expiry, not today's main contract
        — those diverge once the front-month rolls over while the strategy
        still holds the previous month.

        Falls back to base symbol if the broker isn't ContractAware.
        """
        bt_position = self._broker.getposition(self._data)
        if bt_position.size == 0:
            return None
        contract = getattr(bt_position, 'contract', None)
        return contract if contract else self._symbol

    def get_account_info(self) -> AccountInfo:
        """Get account information."""
        equity = self._broker.getvalue()
        cash = self._broker.getcash()

        return AccountInfo(
            equity=equity,
            cash=cash,
            margin_used=equity - cash,
            margin_available=cash,
            unrealized_pnl=self.get_unrealized_pnl(),
            realized_pnl=self.get_realized_pnl(),
            currency="CNY"
        )

    def _get_position_cost(self) -> float:
        """Get position cost for PnL calculation."""
        bt_position = self._broker.getposition(self._data)
        if bt_position.size != 0:
            return abs(bt_position.size) * bt_position.price
        return 0.0


class BacktraderOrderManager(IOrderManager):
    """IOrderManager implementation for Backtrader.

    Methods:
    - ``submit_entry_order(direction, size, price)``: enter new position
    - ``submit_exit_order(size, price)``: exit/reduce position
    - ``cancel_order(order_id)``: cancel an order
    - ``get_order_status(order_id)``: get order status
    """

    def __init__(
        self,
        strategy: 'bt.Strategy',
        data_feed: 'bt.feeds.DataBase',
        symbol: str = ""
    ):
        """
        Initialize with Backtrader strategy.

        Args:
            strategy: Backtrader strategy instance
            data_feed: Main data feed
            symbol: Trading symbol
        """
        self._strategy = strategy
        self._data = data_feed
        self._symbol = symbol
        self._orders: Dict[str, Order] = {}
        self._order_status: Dict[str, OrderStatus] = {}
        self._order_counter = 0

    def set_strategy(self, strategy: 'bt.Strategy') -> None:
        """Update strategy reference."""
        self._strategy = strategy

    def set_data_feed(self, data_feed: 'bt.feeds.DataBase') -> None:
        """Update data feed reference."""
        self._data = data_feed

    def set_symbol(self, symbol: str) -> None:
        """Set trading symbol."""
        self._symbol = symbol

    def _generate_order_id(self) -> str:
        """Generate unique order ID."""
        self._order_counter += 1
        return f"BT-{self._order_counter:06d}"

    # ========================================================================
    # IMarketData methods
    # ========================================================================

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
        order_id = self._generate_order_id()

        # Determine side and intent
        if direction.upper() == "LONG":
            side = OrderSide.BUY
            intent = OrderIntent.ENTRY_LONG
        else:
            side = OrderSide.SELL
            intent = OrderIntent.ENTRY_SHORT

        # Submit to Backtrader
        if price is None:
            # Market order
            if side == OrderSide.BUY:
                bt_order = self._strategy.buy(data=self._data, size=size)
            else:
                bt_order = self._strategy.sell(data=self._data, size=size)
        else:
            # Limit order
            import backtrader as bt
            if side == OrderSide.BUY:
                bt_order = self._strategy.buy(data=self._data, size=size, price=price, exectype=bt.Order.Limit)
            else:
                bt_order = self._strategy.sell(data=self._data, size=size, price=price, exectype=bt.Order.Limit)

        # Store order info
        status = OrderStatus.SUBMITTED
        if bt_order:
            self._orders[order_id] = Order(
                order_id=order_id,
                symbol=self._symbol,
                side=side,
                order_type=OrderType.MARKET if price is None else OrderType.LIMIT,
                size=size,
                price=price,
                intent=intent,
                status=status,
                created_at=self._data.datetime.datetime(0) if self._data else None,
                metadata={'bt_order': bt_order, 'bt_ref': bt_order.ref}
            )
            self._order_status[order_id] = status

        return OrderResult(
            order_id=order_id,
            status=status,
            message=f"Entry {direction} order submitted",
            intent=intent
        )

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
        order_id = self._generate_order_id()

        # Get current position to determine direction
        position = self._strategy.broker.getposition(self._data)
        if position.size == 0:
            return OrderResult(
                order_id=order_id,
                status=OrderStatus.REJECTED,
                message="No position to exit",
                intent=None
            )

        # Determine side based on current position
        if position.size > 0:
            side = OrderSide.SELL
            intent = OrderIntent.EXIT_LONG
        else:
            side = OrderSide.BUY
            intent = OrderIntent.EXIT_SHORT

        # Submit to Backtrader
        if price is None:
            # Market order
            if side == OrderSide.BUY:
                bt_order = self._strategy.buy(data=self._data, size=size)
            else:
                bt_order = self._strategy.sell(data=self._data, size=size)
        else:
            # Limit order
            import backtrader as bt
            if side == OrderSide.BUY:
                bt_order = self._strategy.buy(data=self._data, size=size, price=price, exectype=bt.Order.Limit)
            else:
                bt_order = self._strategy.sell(data=self._data, size=size, price=price, exectype=bt.Order.Limit)

        # Store order info
        status = OrderStatus.SUBMITTED
        if bt_order:
            self._orders[order_id] = Order(
                order_id=order_id,
                symbol=self._symbol,
                side=side,
                order_type=OrderType.MARKET if price is None else OrderType.LIMIT,
                size=size,
                price=price,
                intent=intent,
                status=status,
                created_at=self._data.datetime.datetime(0) if self._data else None,
                metadata={'bt_order': bt_order, 'bt_ref': bt_order.ref}
            )
            self._order_status[order_id] = status

        return OrderResult(
            order_id=order_id,
            status=status,
            message="Exit order submitted",
            intent=intent
        )

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an order."""
        if order_id not in self._orders:
            return False

        order = self._orders[order_id]
        bt_order = order.metadata.get('bt_order')
        if bt_order:
            self._strategy.cancel(bt_order)
            order.status = OrderStatus.CANCELLED
            self._order_status[order_id] = OrderStatus.CANCELLED
            return True
        return False

    def get_order_status(self, order_id: str) -> OrderStatus:
        """Get order status."""
        return self._order_status.get(order_id, OrderStatus.REJECTED)

    # ========================================================================
    # EXTENDED METHODS (new functionality)
    # ========================================================================

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
        """Submit an order through Backtrader (extended method)."""
        order_id = self._generate_order_id()

        # Create order record
        order = Order(
            order_id=order_id,
            symbol=symbol,
            side=side,
            order_type=order_type,
            size=size,
            price=price,
            stop_price=stop_price,
            intent=intent,
            status=OrderStatus.SUBMITTED,
            created_at=self._data.datetime.datetime(0) if self._data else None,
            metadata=metadata or {}
        )

        # Submit to Backtrader
        import backtrader as bt
        if order_type == OrderType.MARKET:
            if side == OrderSide.BUY:
                bt_order = self._strategy.buy(data=self._data, size=size)
            else:
                bt_order = self._strategy.sell(data=self._data, size=size)
        elif order_type == OrderType.LIMIT:
            if side == OrderSide.BUY:
                bt_order = self._strategy.buy(data=self._data, size=size, price=price, exectype=bt.Order.Limit)
            else:
                bt_order = self._strategy.sell(data=self._data, size=size, price=price, exectype=bt.Order.Limit)
        elif order_type == OrderType.STOP:
            if side == OrderSide.BUY:
                bt_order = self._strategy.buy(data=self._data, size=size, price=stop_price, exectype=bt.Order.Stop)
            else:
                bt_order = self._strategy.sell(data=self._data, size=size, price=stop_price, exectype=bt.Order.Stop)
        else:
            raise ValueError(f"Unsupported order type: {order_type}")

        # Store mapping
        if bt_order:
            order.metadata['bt_order'] = bt_order
            order.metadata['bt_ref'] = bt_order.ref
            self._orders[order_id] = order
            self._order_status[order_id] = OrderStatus.SUBMITTED

        return order

    def get_order(self, order_id: str) -> Optional[Order]:
        """Get order by ID."""
        return self._orders.get(order_id)

    def get_pending_orders(self, symbol: Optional[str] = None) -> List[Order]:
        """
        Get pending orders (not yet filled).

        Includes orders in PENDING, SUBMITTED, or ACCEPTED states.
        CRITICAL: Must include ACCEPTED - Backtrader orders go through
        SUBMITTED → ACCEPTED → FILLED, and ACCEPTED orders are still pending!
        """
        return [
            order for order in self._orders.values()
            if order.status in (OrderStatus.PENDING, OrderStatus.SUBMITTED, OrderStatus.ACCEPTED)
        ]

    def cancel_all_orders(self, symbol: Optional[str] = None) -> int:
        """Cancel all pending orders."""
        cancelled = 0
        for order_id in list(self._orders.keys()):
            if self.cancel_order(order_id):
                cancelled += 1
        return cancelled

    def close_position(
        self,
        symbol: Optional[str] = None,
        intent: OrderIntent = OrderIntent.EXIT_LONG,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[OrderResult]:
        """Close existing position."""
        position = self._strategy.broker.getposition(self._data)
        if position.size == 0:
            return None

        size = abs(position.size)
        return self.submit_exit_order(size=size)

    def update_order_status(self, bt_ref: int, new_status: OrderStatus) -> None:
        """Update order status from Backtrader notification."""
        for order_id, order in self._orders.items():
            if order.metadata.get('bt_ref') == bt_ref:
                order.status = new_status
                self._order_status[order_id] = new_status
                break


class BacktraderLogger(ILogger):
    """ILogger implementation for Backtrader.

    Routes ``info``/``warning``/``error``/``debug`` to Python's logging system.
    """

    def __init__(self, name: str = "BacktraderStrategy"):
        """Initialize logger."""
        self._logger = logging.getLogger(name)

    # ========================================================================
    # IMarketData methods
    # ========================================================================

    def info(self, message: str) -> None:
        """Log info message."""
        self._logger.info(message)

    def warning(self, message: str) -> None:
        """Log warning message."""
        self._logger.warning(message)

    def error(self, message: str) -> None:
        """Log error message."""
        self._logger.error(message)

    def debug(self, message: str) -> None:
        """Log debug message."""
        self._logger.debug(message)

    # ========================================================================
    # EXTENDED METHODS (aliases and new functionality)
    # ========================================================================

    def log_info(self, message: str, **kwargs) -> None:
        """Alias for info()."""
        self._logger.info(message, extra=kwargs if kwargs else None)

    def log_warning(self, message: str, **kwargs) -> None:
        """Alias for warning()."""
        self._logger.warning(message, extra=kwargs if kwargs else None)

    def log_error(self, message: str, **kwargs) -> None:
        """Alias for error()."""
        self._logger.error(message, extra=kwargs if kwargs else None)

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
        """Log trade."""
        self._logger.info(
            f"TRADE: {action} {side.value} {size} {symbol} @ {price:.2f} - {reason}"
        )

    def log_signal(
        self,
        signal_type: str,
        direction: str,
        strength: float,
        reason: str,
        **kwargs
    ) -> None:
        """Log signal."""
        self._logger.info(
            f"SIGNAL: {signal_type} {direction} (strength={strength:.2f}) - {reason}"
        )

    def log_risk_event(
        self,
        event_type: str,
        details: str,
        **kwargs
    ) -> None:
        """Log risk event."""
        self._logger.warning(f"RISK: {event_type} - {details}")


class BacktraderEventBus(IEventBus):
    """
    IEventBus implementation for Backtrader.

    Simple in-process event bus for order fills and trade closures, using
    callback registration.
    """

    def __init__(self):
        """Initialize event bus."""
        self._subscribers: Dict[str, List[Callable]] = {
            'order_filled': [],
            'trade_closed': [],
            'market_data_update': [],
        }

    # ========================================================================
    # IMarketData methods
    # ========================================================================

    def on_order_filled(self, callback: Callable) -> None:
        """Register callback for order filled events."""
        self._subscribers['order_filled'].append(callback)

    def on_trade_closed(self, callback: Callable) -> None:
        """Register callback for trade closed events."""
        self._subscribers['trade_closed'].append(callback)

    def on_market_data_update(self, callback: Callable) -> None:
        """Register callback for market data updates."""
        self._subscribers['market_data_update'].append(callback)

    # ========================================================================
    # EXTENDED METHODS (new subscription pattern)
    # ========================================================================

    def subscribe(self, event_type: str, callback: Callable) -> None:
        """Subscribe to event."""
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(callback)

    def unsubscribe(self, event_type: str, callback: Callable) -> None:
        """Unsubscribe from event."""
        if event_type in self._subscribers and callback in self._subscribers[event_type]:
            self._subscribers[event_type].remove(callback)

    def publish(self, event_type: str, data: Any) -> None:
        """Publish event to all subscribers."""
        if event_type in self._subscribers:
            for callback in self._subscribers[event_type]:
                callback(data)


class BacktraderEngine(ITradingEngine):
    """
    Main Backtrader engine implementing ITradingEngine.

    This is a CLEAN engine that handles only core backtrader mechanics.
    Market-specific and frequency-specific features are added via HOOKS.

    TradingContext as Single Source of Truth:
    - ctx provides market, instrument, and frequency configuration
    - market_adapter and frequency_context are required

    Hook-based customization:
    - ContractAwareHook: For interday futures (contract rollover)
    - SessionAwareHook: For intraday trading (session context)
    """

    def __init__(
        self,
        ctx: TradingContext,
        market_adapter: IMarketAdapter,
        frequency_context: IFrequencyContext,
        strategy_logger_enabled: bool = True,
        strategy_logger_dir: Optional[str] = None,
    ):
        """
        Initialize Backtrader engine.

        Args:
            ctx: TradingContext (single source of truth)
            market_adapter: Market-specific adapter
            frequency_context: Frequency context for time scaling
            strategy_logger_enabled: Whether to enable strategy logging
            strategy_logger_dir: Directory for strategy logs

        Note:
            Use add_hook() to add market-specific or frequency-specific features.
            EngineFactory handles hook composition based on trading mode.
        """
        self._ctx = ctx
        self._market_adapter = market_adapter
        self._frequency_context = frequency_context
        self._initial_cash = ctx.initial_capital

        # Create component instances (will be configured in setup)
        self._market_data = BacktraderMarketData(None, session_context_provider=None)
        self._portfolio = BacktraderPortfolio(None, None, self._initial_cash)
        self._order_manager = BacktraderOrderManager(None, None)
        self._logger = BacktraderLogger()
        self._event_bus = BacktraderEventBus()

        # Strategy logger
        self._strategy_logger_enabled = strategy_logger_enabled
        self._strategy_logger_dir = strategy_logger_dir
        self._strategy_logger: Optional[IStrategyLogger] = None

        # Hooks for customization (added by factory or manually)
        self._hooks: List[IEngineHook] = []

        # Optional components (set by hooks)
        self._session_context_provider: Optional[BaseSessionContextProvider] = None
        self._contract_manager: Optional['ContractIndicatorManager'] = None
        # Per-bar segmentation column for trade analyzers (e.g., TRS-paradigm
        # 'market_regime'; other paradigms can use any categorical column).
        self._segmentation_data: Optional[pd.DataFrame] = None

        # Backtrader components (set during setup)
        self._cerebro: Optional['bt.Cerebro'] = None
        self._data_feed: Optional['bt.feeds.DataBase'] = None
        self._strategy: Optional['bt.Strategy'] = None
        # Use instrument_code (e.g., 'al') for trading
        self._symbol = ctx.instrument_code

        # Log initialization
        logger.info(
            f"BacktraderEngine initialized: market={ctx.market_code}, "
            f"frequency={frequency_context.bar_size.value} ({frequency_context.frequency_type.value}), "
            f"initial_cash={self._initial_cash:,.0f}"
        )

    def add_hook(self, hook: IEngineHook) -> None:
        """
        Add engine hook for customization.

        Hooks allow market-specific and frequency-specific features
        to be added without modifying core engine code.

        Args:
            hook: IEngineHook implementation

        Example:
            engine.add_hook(ContractAwareHook(market_adapter, indicators_dir))
            engine.add_hook(SessionAwareHook(market_adapter, bar_size_minutes=5))
        """
        self._hooks.append(hook)
        hook.on_init(self)
        logger.debug(f"Hook added: {hook.name}")

    def _derive_slippage_typical_price(self) -> float:
        """Derive a deterministic fallback price from the active data feed."""
        if self._data_feed is None:
            raise RuntimeError("Cannot derive slippage price before data feed is configured")

        dataname = getattr(getattr(self._data_feed, "p", None), "dataname", None)
        if isinstance(dataname, pd.DataFrame):
            for column in ("close", "open"):
                if column in dataname.columns:
                    series = pd.to_numeric(dataname[column], errors="coerce").dropna()
                    series = series[series > 0]
                    if not series.empty:
                        return float(series.iloc[0])

        raise RuntimeError(
            "Cannot derive tick-size slippage fallback: data feed does not expose "
            "a positive open/close price. Provide calibrated_slippage_bps instead."
        )

    def _apply_scalar_slippage_config(self, contract_spec: Any) -> None:
        """Apply scalar slippage tiers to the final broker after hooks run."""
        if self._cerebro is None or contract_spec is None:
            return

        if contract_spec.calibrated_slippage_bps_by_intent is not None:
            return

        if contract_spec.calibrated_slippage_bps is not None:
            slippage_pct = contract_spec.calibrated_slippage_bps / 10000.0
            self._cerebro.broker.set_slippage_perc(slippage_pct)
            return

        if contract_spec.tick_size > 0:
            typical_price = self._derive_slippage_typical_price()
            slippage_pct = contract_spec.tick_size / typical_price
            self._cerebro.broker.set_slippage_perc(slippage_pct)

    def setup(
        self,
        data_feed: 'bt.feeds.DataBase',
        strategy_class: Type['bt.Strategy'],
        strategy_params: Optional[Dict[str, Any]] = None,
        analyzers: Optional[List[Type['bt.Analyzer']]] = None,
        strategy_name: Optional[str] = None,
        segmentation_data: Optional[pd.DataFrame] = None,
    ) -> None:
        """
        Configure backtest.

        Args:
            data_feed: Backtrader data feed
            strategy_class: Backtrader strategy class
            strategy_params: Strategy parameters
            analyzers: List of analyzer classes to attach
            strategy_name: Name for strategy logger (uses class name if None)
            segmentation_data: Pre-loaded per-bar categorical column used by
                trade analyzers to stratify metrics. TRS-paradigm strategies
                pass a ``market_regime`` column; other paradigms can pass any
                categorical column the analyzer should bucket by.

        Note:
            Commission, slippage, and contract multiplier are retrieved from
            market_adapter.get_contract_spec(symbol). No need to pass them.

            Hooks can customize broker, add observers, etc. during on_setup().
        """
        self._cerebro = bt.Cerebro()
        self._data_feed = data_feed
        self._segmentation_data = segmentation_data

        # Add data feed
        self._cerebro.adddata(data_feed, name=self._symbol)

        # Get contract spec from market adapter (commission, multiplier, tick_size)
        contract_spec = None
        if self._market_adapter is not None:
            contract_spec = self._market_adapter.get_contract_spec(self._symbol)

        # =====================================================================
        # Default broker configuration (may be overridden by hooks)
        # =====================================================================
        self._cerebro.broker.setcash(self._initial_cash)

        # Set commission from market adapter's contract spec
        # IMPORTANT: Must include mult for futures to calculate P&L correctly
        if contract_spec is not None:
            if contract_spec.commission_type == "percentage":
                self._cerebro.broker.setcommission(
                    commission=contract_spec.commission,
                    mult=contract_spec.multiplier
                )
            else:
                self._cerebro.broker.setcommission(
                    commission=contract_spec.commission,
                    commtype=bt.CommInfoBase.COMM_FIXED,
                    mult=contract_spec.multiplier
                )

        # Slippage selection — three-tier precedence per qorka
        # `decisions_log.md` 2026-05-13 "Cost-model v2" entry:
        #
        #   1. v2 calibrated_slippage_bps_by_intent (per-intent + vol-regime)
        #      → install StructuredSlippageBroker for per-order classification
        #      [Wave 1A T27b/c — broker implementation lands in follow-up commit;
        #      this branch currently degrades to mean-of-intents as scalar
        #      with a warning until the broker ships]
        #   2. v1 calibrated_slippage_bps (scalar; backward-compat for archived clusters)
        #      → set_slippage_perc(scalar / 10000)
        #   3. tick-size-derived default (legacy fallback when neither calibration is set)
        #      → set_slippage_perc(tick_size / typical_price)
        if contract_spec is not None and contract_spec.calibrated_slippage_bps_by_intent is not None:
            # v2 path — install StructuredSlippageBroker for per-order
            # intent classification + vol-regime multiplier. Replaces
            # the prior degrade-to-mean-of-intents fallback.
            from echolon.backtest.engine.structured_slippage import (
                StructuredSlippageBroker,
            )
            import logging
            # logger = logging.getLogger(__name__)  # patched: use module-level logger

            # Capture cash from the default broker before swap so the
            # configured initial_cash isn't lost when we replace the
            # broker instance.
            initial_cash = self._cerebro.broker.getcash()

            structured_broker = StructuredSlippageBroker()
            structured_broker.setcash(initial_cash)
            structured_broker.configure_v2(
                by_intent=contract_spec.calibrated_slippage_bps_by_intent,
                high_vol_threshold=contract_spec.high_vol_pct_threshold,
                high_vol_multiplier=contract_spec.high_vol_slippage_multiplier,
            )
            self._cerebro.broker = structured_broker
            logger.info(
                "ContractSpec %s: installed StructuredSlippageBroker with "
                "by_intent=%s, high_vol_threshold=%.1f, high_vol_multiplier=%.2f. "
                "Per-order intent classification active.",
                contract_spec.symbol,
                contract_spec.calibrated_slippage_bps_by_intent,
                contract_spec.high_vol_pct_threshold,
                contract_spec.high_vol_slippage_multiplier,
            )

        # =====================================================================
        # Hook lifecycle: on_setup (before strategy added)
        # Hooks can replace broker, add observers, etc.
        # =====================================================================
        for hook in self._hooks:
            hook.on_setup(self._cerebro, self)

        # Hooks may replace the broker. Scalar slippage must be applied to the
        # final broker, not to the provisional default broker configured above.
        self._apply_scalar_slippage_config(contract_spec)

        # Initialize strategy logger
        log_strategy_name = strategy_name or strategy_class.__name__
        if self._strategy_logger_enabled:
            self._strategy_logger = CSVStrategyLogger(
                output_dir=self._strategy_logger_dir,
                strategy_name=log_strategy_name,
                enabled=True
            )
        else:
            self._strategy_logger = NullStrategyLogger()

        # Add strategy with properly nested params for BacktraderStrategyBridge
        # instrument = full name (e.g., 'aluminum'), instrument_code = code (e.g., 'al')
        # Extract printlog from strategy_params if provided (used by optimization to suppress output)
        effective_strategy_params = strategy_params or {}
        printlog = effective_strategy_params.get('printlog', True)
        # Remove printlog from strategy_params to avoid passing it to strategy logic
        if 'printlog' in effective_strategy_params:
            effective_strategy_params = {k: v for k, v in effective_strategy_params.items() if k != 'printlog'}
        bridge_params = {
            'engine': self,
            'strategy_name': log_strategy_name,
            'market': self._ctx.market_code,
            'instrument': self._ctx.instrument_name,
            'instrument_code': self._ctx.instrument_code,
            'strategy_params': effective_strategy_params,
            'printlog': printlog,
        }
        self._cerebro.addstrategy(strategy_class, **bridge_params)

        # =====================================================================
        # Add analyzers
        # =====================================================================
        if analyzers:
            for analyzer in analyzers:
                self._cerebro.addanalyzer(analyzer)

        # Add comprehensive analyzers
        # Determine if contract-aware trades should be used (set by ContractAwareHook)
        use_contract_aware = self._contract_manager is not None
        contract_multiplier = contract_spec.multiplier 
        add_analyzers(
            cerebro=self._cerebro,
            use_contract_aware_trades=use_contract_aware,
            market_adapter=self._market_adapter,
            contract_manager=self._contract_manager,
            segmentation_data=segmentation_data,
            contract_multiplier=contract_multiplier,
            session_context_provider=self._session_context_provider,
        )

        # =====================================================================
        # Hook lifecycle: on_post_setup (after strategy and analyzers added)
        # =====================================================================
        for hook in self._hooks:
            hook.on_post_setup(self._cerebro, self)

        # Update component references
        self._market_data.set_data_feed(data_feed)
        self._portfolio.set_data_feed(data_feed)
        self._portfolio.set_symbol(self._symbol)
        self._order_manager.set_symbol(self._symbol)

        hooks_info = f", hooks=[{', '.join(h.name for h in self._hooks)}]" if self._hooks else ""
        logger.info(f"Backtest configured: symbol={self._symbol}{hooks_info}")

    def run(self) -> BacktestResults:
        """
        Run backtest.

        Returns:
            BacktestResults with performance metrics
        """
        if self._cerebro is None:
            raise RuntimeError("Engine not configured. Call setup() first.")

        # Hook lifecycle: on_pre_run
        for hook in self._hooks:
            hook.on_pre_run(self)

        # Run backtest
        bt_results = self._cerebro.run(preload=True)
        strategy = bt_results[0]

        # Update references after run
        self._strategy = strategy
        self._portfolio.set_broker(self._cerebro.broker)
        self._order_manager.set_strategy(strategy)
        self._order_manager.set_data_feed(self._data_feed)

        # Collect results
        final_value = self._cerebro.broker.getvalue()
        total_return = (final_value - self._initial_cash) / self._initial_cash * 100

        # Extract comprehensive analysis results
        # Use contract-aware extraction if ContractAwareHook was added
        use_contract_aware = self._contract_manager is not None
        analysis_results = extract_analysis_results(
            strategy=strategy,
            use_contract_aware_trades=use_contract_aware
        )

        # Get key metrics from analysis
        sharpe = analysis_results.get('sharpe_ratio_annual')
        max_drawdown = analysis_results.get('max_drawdown_pct')
        total_trades = analysis_results.get('total_trades', 0)

        # Get win/loss counts from trade analyzer details
        trade_details = analysis_results.get('trade_analyzer_details', {})
        winning_trades = trade_details.get('won', {}).get('total', 0)
        losing_trades = trade_details.get('lost', {}).get('total', 0)

        # Build results dictionary for hook augmentation
        results_dict = {
            'final_value': final_value,
            'initial_value': self._initial_cash,
            'total_return': total_return,
            'sharpe_ratio': sharpe,
            'max_drawdown': max_drawdown,
            'total_trades': total_trades,
            'winning_trades': winning_trades,
            'losing_trades': losing_trades,
            'analyzers': analysis_results,
        }

        # Hook lifecycle: on_post_run (hooks can augment results)
        for hook in self._hooks:
            results_dict = hook.on_post_run(self, strategy, results_dict)

        logger.info(
            f"Backtest complete: final_value={final_value:,.0f}, "
            f"return={total_return:.2f}%, trades={total_trades}"
        )

        return BacktestResults(
            final_value=results_dict['final_value'],
            initial_value=results_dict['initial_value'],
            total_return=results_dict['total_return'],
            sharpe_ratio=results_dict.get('sharpe_ratio'),
            max_drawdown=results_dict.get('max_drawdown'),
            total_trades=results_dict.get('total_trades', 0),
            winning_trades=results_dict.get('winning_trades', 0),
            losing_trades=results_dict.get('losing_trades', 0),
            analyzers=results_dict.get('analyzers', {}),
        )

    # ========================================================================
    # ITradingEngine interface implementation
    # ========================================================================

    def get_market_data(self) -> IMarketData:
        """Get market data interface."""
        return self._market_data

    def get_portfolio(self) -> IPortfolio:
        """Get portfolio interface."""
        return self._portfolio

    def get_order_manager(self) -> IOrderManager:
        """Get order manager interface."""
        return self._order_manager

    def get_logger(self) -> ILogger:
        """Get logger interface."""
        return self._logger

    def get_strategy_logger(self) -> Optional[IStrategyLogger]:
        """Get strategy logger interface (may be None for optimization runs)."""
        return self._strategy_logger

    def get_event_bus(self) -> IEventBus:
        """Get event bus interface."""
        return self._event_bus

    def get_market_adapter(self) -> IMarketAdapter:
        """Get market adapter."""
        return self._market_adapter

    def get_frequency_context(self) -> IFrequencyContext:
        """Get frequency context."""
        return self._frequency_context

    def get_trading_context(self) -> TradingContext:
        """Get trading context (single source of truth)."""
        return self._ctx

    def get_session_context_provider(self) -> Optional[ISessionContext]:
        """
        Get session context provider for intraday trading.

        Returns ISessionContext implementation that provides:
        - Session phase (night, morning, afternoon)
        - Bar position within session (bar_of_session, bars_remaining)
        - Session-aware indicators (VWAP, Opening Range, Session Levels)

        Returns None for daily strategies that don't need session context.
        """
        return self._session_context_provider

    def get_current_symbol(self) -> str:
        """Get current trading symbol (instrument_code)."""
        return self._symbol

    # ========================================================================
    # Additional helper methods
    # ========================================================================

    def set_strategy_logger_enabled(self, enabled: bool) -> None:
        """Enable or disable strategy logging."""
        self._strategy_logger_enabled = enabled
        if self._strategy_logger is not None:
            if hasattr(self._strategy_logger, 'enabled'):
                self._strategy_logger.enabled = enabled
