"""
QMT Trading Engine
==================

MiniQMT platform integration implementing ITradingEngine.

This is the critical bridge between platform-agnostic strategy
and the MiniQMT trading platform.

Integration architecture:
1. Strategy → QMTEngine: Strategy uses ITradingEngine interface
2. QMTEngine → MiniQMT: Engine translates to QMT API calls
3. Data flow: CSV files → QMTMarketData → strategy
4. Order flow: Strategy → QMTOrderManager → MiniQMTClient → QMT

Inner classes:
- QMTMarketData: Implements IMarketData, loads from CSV
- QMTPortfolio: Implements IPortfolio, queries QMT API
- QMTOrderManager: Implements IOrderManager, submits to QMT
- QMTLogger: Implements ILogger, Excel logging
- QMTEventBus: Implements IEventBus, order/trade events

Constructor:
    engine = QMTEngine(
        ctx=ctx,  # TradingContext (single source of truth)
        market_adapter=shfe_adapter,
        frequency_context=interday_context,
        client=miniqmt_client
    )

The engine ensures strategy code runs identically
to backtest, with QMT handling actual execution.
"""

from typing import Dict, Any, Optional, List, Callable, TYPE_CHECKING
from datetime import datetime, date
from pathlib import Path
import logging
import pickle  # nosec — used by get_contract_indicator to read pre-validated indicator pickles
import pandas as pd

from echolon.strategy.interfaces import (
    ITradingEngine,
    IMarketData,
    IPortfolio,
    IOrderManager,
    ILogger,
    IStrategyLogger,
    IEventBus,
    Order,
    OrderResult,
    Position,
    OrderSide,
    OrderType,
    OrderIntent,
    OrderStatus,
)
from echolon.markets.interface import IMarketAdapter
from echolon.strategy.frequency.interface import IFrequencyContext
from echolon.strategy.logging import CSVStrategyLogger

from echolon.config.markets.core.context import TradingContext

if TYPE_CHECKING:
    from .qmt_client import MiniQMTClient

logger = logging.getLogger(__name__)


class QMTMarketData(IMarketData):
    """
    IMarketData implementation for MiniQMT.

    Loads market data and indicators from CSV files (pre-calculated).
    This matches the existing QTS_deploy data loading approach.
    """

    def __init__(
        self,
        indicators_df: pd.DataFrame = None,
        symbol: str = "al"
    ):
        """
        Initialize with indicators DataFrame.

        Args:
            indicators_df: Pre-calculated indicators DataFrame
            symbol: Trading symbol
        """
        self._df = indicators_df
        self._symbol = symbol
        self._current_idx = -1  # Points to current bar
        self._contract_indicators_dir: Optional[str] = None
        self._contract_indicator_cache: Dict[str, pd.DataFrame] = {}

    def load_indicators(self, csv_path: str) -> None:
        """
        Load indicators from CSV file.

        Supports both formats:
        - New format: 'datetime' column (parsed as datetime)
        - Old format: 'date' column (parsed as date, for SHFE_loader compatibility)

        Auto-detects which column is present.
        """
        # Read header first to detect format
        df = pd.read_csv(csv_path)
        if 'datetime' in df.columns:
            df['datetime'] = pd.to_datetime(df['datetime'])
            df.set_index('datetime', inplace=True)
        elif 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'])
            df.set_index('date', inplace=True)
        else:
            raise ValueError(
                f"CSV must contain 'datetime' or 'date' column. "
                f"Found columns: {list(df.columns)}"
            )
        self._df = df
        logger.info(f"Loaded {len(self._df)} bars from {csv_path}")

    def set_current_bar(self, bar_datetime: datetime) -> None:
        """Set current bar by exact datetime match.

        Raises KeyError if the requested date is not in the data.
        Silent fallback to a stale bar is dangerous — it would cause
        the strategy to re-trade on yesterday's indicators.
        """
        if self._df is None:
            raise RuntimeError("No data loaded")

        try:
            self._current_idx = self._df.index.get_loc(bar_datetime)
        except KeyError:
            available = self._df.index[-1] if len(self._df) > 0 else 'empty'
            raise KeyError(
                f"Bar for {bar_datetime.date()} not found in indicator data. "
                f"Latest available: {available}. "
                f"Data pipeline may have failed — refusing to trade on stale data."
            )

    def get_current_bar(self) -> Dict[str, float]:
        """Get current OHLCV bar as dict (matches IMarketData interface)."""
        return self.get_bar_data(0)

    def get_current_datetime(self) -> datetime:
        """Get the current datetime."""
        if self._df is None:
            raise RuntimeError("No data loaded")

        dt = self._df.index[self._current_idx]
        return dt if isinstance(dt, datetime) else datetime.combine(dt, datetime.min.time())

    def get_current_price(self) -> float:
        """Get current price for the main trading symbol."""
        return self._get_value('close', 0)

    def get_current_date(self) -> date:
        """Get the current date."""
        return self.get_current_datetime().date()

    def get_contract_indicator(
        self,
        contract_name: str,
        trading_date: datetime,
        indicator_name: str
    ) -> Optional[float]:
        """
        Get indicator value for a specific contract on a specific date.

        Loads from per-contract indicator pickle files at:
        {indicators_dir}/by_contract/{contract_name}_indicators.pkl
        """
        if self._contract_indicators_dir is None:
            logger.warning("Contract indicators directory not set")
            return None

        # Load from cache or disk
        if contract_name not in self._contract_indicator_cache:
            pkl_path = Path(self._contract_indicators_dir) / "by_contract" / f"{contract_name}_indicators.pkl"
            if not pkl_path.exists():
                logger.warning(f"Contract indicator file not found: {pkl_path}")
                return None
            with open(pkl_path, 'rb') as f:
                df = pickle.load(f)
            self._contract_indicator_cache[contract_name] = df

        df = self._contract_indicator_cache[contract_name]

        # Look up the indicator for the given date
        target_date = trading_date.date() if isinstance(trading_date, datetime) else trading_date
        if hasattr(df.index, 'date'):
            mask = df.index.date == target_date
        else:
            mask = df.index == target_date

        matched = df.loc[mask]
        if matched.empty:
            return None

        if indicator_name not in matched.columns:
            return None

        return float(matched.iloc[0][indicator_name])

    def get_bar_data(self, bars_back: int = 0) -> Dict[str, float]:
        """
        Get OHLCV data for specific bar.

        Args:
            bars_back: Number of bars back (0=current)

        Returns:
            Dict with keys: 'open', 'high', 'low', 'close', 'volume'
        """
        if self._df is None:
            raise RuntimeError("No data loaded")

        idx = self._current_idx - bars_back
        if idx < 0:
            raise IndexError(f"Not enough history for bars_back={bars_back}")

        row = self._df.iloc[idx]
        return {
            'open': float(row['open']),
            'high': float(row['high']),
            'low': float(row['low']),
            'close': float(row['close']),
            'volume': float(row.get('volume', 0)),
        }

    def is_market_open(self) -> bool:
        """
        Check if market is currently open.

        Returns True because daily bar strategies run post-market
        when the bar data is already complete.
        """
        return True

    def _get_value(self, column: str, ago: int = 0) -> float:
        """Get value from DataFrame."""
        if self._df is None:
            raise RuntimeError("No data loaded")

        idx = self._current_idx - ago
        if idx < 0:
            raise IndexError(f"Not enough history for ago={ago}")

        return float(self._df.iloc[idx][column])

    def get_open(self, ago: int = 0) -> float:
        """Get open price."""
        return self._get_value('open', ago)

    def get_high(self, ago: int = 0) -> float:
        """Get high price."""
        return self._get_value('high', ago)

    def get_low(self, ago: int = 0) -> float:
        """Get low price."""
        return self._get_value('low', ago)

    def get_close(self, ago: int = 0) -> float:
        """Get close price."""
        return self._get_value('close', ago)

    def get_volume(self, ago: int = 0) -> float:
        """Get volume."""
        return self._get_value('volume', ago)

    def get_indicator(self, name: str, ago: int = 0) -> float:
        """Get indicator value."""
        return self._get_value(name.lower(), ago)

    def get_indicator_series(self, name: str, length: int) -> List[float]:
        """Get indicator series."""
        if self._df is None:
            raise RuntimeError("No data loaded")

        col = name.lower()
        if col not in self._df.columns:
            raise KeyError(f"Indicator not found: {name}")

        start_idx = max(0, self._current_idx - length + 1)
        end_idx = self._current_idx + 1

        return list(self._df.iloc[start_idx:end_idx][col].values)

    def has_indicator(self, name: str) -> bool:
        """Check if indicator exists."""
        if self._df is None:
            return False
        return name.lower() in self._df.columns


class QMTPortfolio(IPortfolio):
    """
    IPortfolio implementation for MiniQMT.

    Queries portfolio and position information from QMT API.
    """

    def __init__(
        self,
        client: 'MiniQMTClient' = None,
        symbol: str = "al"
    ):
        """
        Initialize with QMT client.

        Args:
            client: MiniQMT client for API calls
            symbol: Trading symbol
        """
        self._client = client
        self._symbol = symbol
        self._cached_equity: float = 1000000.0
        self._cached_cash: float = 1000000.0
        self._cached_position: Optional[Position] = None
        self._realized_pnl: float = 0.0
        self._unrealized_pnl: float = 0.0

    def set_client(self, client: 'MiniQMTClient') -> None:
        """Update client reference."""
        self._client = client

    def refresh(self) -> None:
        """Force refresh of account info and positions from QMT API."""
        if self._client is None:
            return

        # Refresh account info
        try:
            account_info = self._client.get_account_info()
            if account_info:
                self._cached_equity = account_info.get('total_asset', self._cached_equity)
                self._cached_cash = account_info.get('available_cash', self._cached_cash)
        except Exception as e:
            logger.error(f"Failed to refresh account info: {e}")

        # Refresh position data
        # MiniQMTClient.get_positions() returns Dict[str, PositionInfo]
        try:
            positions = self._client.get_positions()
            self._cached_position = None
            for pos_info in positions.values():
                if pos_info.volume > 0:
                    self._cached_position = Position(
                        symbol=pos_info.symbol,
                        size=float(pos_info.volume),
                        avg_price=pos_info.avg_price,
                        market_value=pos_info.market_value,
                        unrealized_pnl=pos_info.unrealized_pnl,
                        realized_pnl=self._realized_pnl,
                        direction=pos_info.direction,
                        current_price=pos_info.avg_price,
                    )
                    self._unrealized_pnl = pos_info.unrealized_pnl
                    break  # Single-position trading: take first active position
        except Exception as e:
            logger.error(f"Failed to refresh positions: {e}")

    def get_total_value(self) -> float:
        """Get total portfolio value (cash + positions)."""
        if self._client is not None:
            try:
                account_info = self._client.get_account_info()
                self._cached_equity = account_info.get('total_asset', self._cached_equity)
                return self._cached_equity
            except Exception as e:
                logger.error(f"Failed to get total value: {e}")
        return self._cached_equity

    def get_cash(self) -> float:
        """Get available cash."""
        if self._client is not None:
            try:
                account_info = self._client.get_account_info()
                self._cached_cash = account_info.get('available_cash', self._cached_cash)
                return self._cached_cash
            except Exception as e:
                logger.error(f"Failed to get cash: {e}")
        return self._cached_cash

    def get_realized_pnl(self) -> float:
        """Get total realized PnL (tracked cumulatively)."""
        return self._realized_pnl

    def get_unrealized_pnl(self) -> float:
        """Get total unrealized PnL from current position."""
        pos = self.get_position()
        if pos is not None:
            return pos.unrealized_pnl
        return 0.0

    def get_equity(self) -> float:
        """Get current equity."""
        return self.get_total_value()

    def get_position(self, symbol: Optional[str] = None) -> Optional[Position]:
        """
        Get current position for symbol.

        Queries QMT API via MiniQMTClient.get_positions() which returns
        Dict[str, PositionInfo] with direction already mapped to "LONG"/"SHORT".
        Returns first active position found.
        """
        if self._client is None:
            return self._cached_position

        try:
            positions = self._client.get_positions()
            for pos_info in positions.values():
                if pos_info.volume > 0:
                    self._cached_position = Position(
                        symbol=pos_info.symbol,
                        size=float(pos_info.volume),
                        avg_price=pos_info.avg_price,
                        market_value=pos_info.market_value,
                        unrealized_pnl=pos_info.unrealized_pnl,
                        realized_pnl=self._realized_pnl,
                        direction=pos_info.direction,
                        current_price=pos_info.avg_price,
                    )
                    return self._cached_position

            # No active positions found
            self._cached_position = None
            return None
        except Exception as e:
            logger.error(f"Failed to get positions: {e}")
            return self._cached_position

    def get_all_positions(self) -> List[Position]:
        """Get all positions."""
        pos = self.get_position()
        return [pos] if pos else []

    def has_position(self, symbol: Optional[str] = None) -> bool:
        """Check if there's a position."""
        pos = self.get_position(symbol)
        return pos is not None and pos.size > 0

    def get_position_size(self, symbol: Optional[str] = None) -> float:
        """Get position size."""
        pos = self.get_position(symbol)
        if pos is None:
            return 0.0
        return pos.size if pos.is_long else -pos.size


class QMTOrderManager(IOrderManager):
    """
    IOrderManager implementation for MiniQMT.

    Records strategy-side order intents in deferred mode — the
    portfolio runner picks pending orders up via
    ``self.client.submit_order_async`` for burst-fire at market open.
    This class does not place orders directly.
    """

    def __init__(
        self,
        client: 'MiniQMTClient' = None,
        symbol: str = "al",
        portfolio: Optional[QMTPortfolio] = None,
    ):
        """
        Args:
            client: MiniQMT client (held only so the runner can reach it
                via the engine; not used by this class).
            symbol: Trading symbol (product code, e.g. 'al').
            portfolio: Portfolio reference for exit-direction queries.
        """
        self._client = client
        self._symbol = symbol
        self._trading_contract = symbol  # Specific contract code for orders (e.g. 'al2508')
        self._portfolio = portfolio
        self._orders: Dict[str, Order] = {}
        self._order_counter = 0

    def set_client(self, client: 'MiniQMTClient') -> None:
        """Update client reference."""
        self._client = client

    def set_portfolio(self, portfolio: QMTPortfolio) -> None:
        """Set portfolio reference for position queries."""
        self._portfolio = portfolio

    def set_trading_contract(self, contract_code: str) -> None:
        """Set the specific contract code used for order placement."""
        self._trading_contract = contract_code
        logger.info(f"Order manager trading contract set to: {contract_code}")

    def _generate_order_id(self) -> str:
        """Generate unique order ID."""
        self._order_counter += 1
        return f"QMT-{self._order_counter:06d}"

    def submit_entry_order(
        self,
        direction: str,
        size: float,
        price: Optional[float] = None
    ) -> OrderResult:
        """
        Record an entry-order intent. The portfolio runner reads
        ``get_pending_orders()`` and fires the actual broker call.

        Args:
            direction: "LONG" or "SHORT"
            size: Position size (contracts)
            price: Limit price (None for market order)
        """
        order_id = self._generate_order_id()
        intent = OrderIntent.ENTRY_LONG if direction == "LONG" else OrderIntent.ENTRY_SHORT
        order_type = OrderType.LIMIT if price is not None else OrderType.MARKET

        order = Order(
            order_id=order_id,
            symbol=self._trading_contract,
            side=OrderSide.BUY if direction == "LONG" else OrderSide.SELL,
            order_type=order_type,
            size=size,
            price=price,
            intent=intent,
            status=OrderStatus.PENDING,
            created_at=datetime.now(),
        )
        self._orders[order_id] = order
        logger.info(
            f"Entry order deferred: {order_id} {direction} {size}@{price} "
            f"contract={self._trading_contract}"
        )
        return OrderResult(
            order_id=order_id,
            status=order.status,
            message=None,
            intent=intent,
        )

    def submit_exit_order(
        self,
        size: float,
        price: Optional[float] = None
    ) -> OrderResult:
        """
        Record an exit-order intent. Direction is derived from the
        current portfolio position. The portfolio runner reads
        ``get_pending_orders()`` and fires the actual broker call.

        Args:
            size: Size to exit (contracts)
            price: Limit price (None for market order)
        """
        order_id = self._generate_order_id()
        order_type = OrderType.LIMIT if price is not None else OrderType.MARKET

        intent = OrderIntent.EXIT_LONG  # default
        side = OrderSide.SELL  # default
        if self._portfolio is not None:
            pos = self._portfolio.get_position()
            if pos is not None and pos.direction == "SHORT":
                intent = OrderIntent.EXIT_SHORT
                side = OrderSide.BUY

        order = Order(
            order_id=order_id,
            symbol=self._trading_contract,
            side=side,
            order_type=order_type,
            size=size,
            price=price,
            intent=intent,
            status=OrderStatus.PENDING,
            created_at=datetime.now(),
        )
        self._orders[order_id] = order
        logger.info(
            f"Exit order deferred: {order_id} {intent.value} {size}@{price} "
            f"contract={self._trading_contract}"
        )
        return OrderResult(
            order_id=order_id,
            status=order.status,
            message=None,
            intent=intent,
        )

    def get_order_status(self, order_id: str) -> OrderStatus:
        """Get order status by ID."""
        if order_id in self._orders:
            return self._orders[order_id].status
        return OrderStatus.REJECTED

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an order."""
        if order_id not in self._orders:
            return False

        order = self._orders[order_id]
        if order.status not in (OrderStatus.PENDING, OrderStatus.SUBMITTED):
            return False

        if self._client is not None:
            try:
                # self._client.cancel_order(order_id)
                order.status = OrderStatus.CANCELLED
                return True
            except Exception as e:
                logger.error(f"Cancel failed: {e}")
                return False

        order.status = OrderStatus.CANCELLED
        return True

    def get_pending_orders(self, symbol: Optional[str] = None) -> List[Order]:
        """Get pending orders."""
        return [
            order for order in self._orders.values()
            if order.status in (OrderStatus.PENDING, OrderStatus.SUBMITTED)
            and (symbol is None or order.symbol == symbol)
        ]

    def close_position(
        self,
        symbol: Optional[str] = None,
        intent: OrderIntent = OrderIntent.EXIT_LONG,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[OrderResult]:
        """
        Close existing position by querying portfolio and submitting exit order.

        Returns OrderResult or None if no position to close.
        """
        if self._portfolio is None:
            logger.warning("No portfolio reference - cannot close position")
            return None

        pos = self._portfolio.get_position()
        if pos is None or pos.size == 0:
            logger.info("No position to close")
            return None

        return self.submit_exit_order(size=pos.size)


class QMTLogger(ILogger):
    """
    ILogger implementation for MiniQMT.

    Routes logging to Python's standard logging system. The structured
    ``log_trade`` / ``log_signal`` / ``log_risk_event`` aliases live on
    the ILogger base class.
    """

    def __init__(self, name: str = "QMTStrategy"):
        """Initialize logger with the given name."""
        self._logger = logging.getLogger(name)

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


class QMTEventBus(IEventBus):
    """
    IEventBus implementation for MiniQMT.

    Handles order fills and trade closure events from QMT.
    """

    def __init__(self):
        """Initialize event bus."""
        self._subscribers: Dict[str, List[Callable]] = {}

    def on_order_filled(self, callback: Callable) -> None:
        """Register callback for order filled events."""
        self.subscribe("order_filled", callback)

    def on_trade_closed(self, callback: Callable) -> None:
        """Register callback for trade closed events."""
        self.subscribe("trade_closed", callback)

    def on_market_data_update(self, callback: Callable) -> None:
        """Register callback for market data updates."""
        self.subscribe("market_data_update", callback)

    def subscribe(self, event_type: str, callback: Callable) -> None:
        """Subscribe to event."""
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(callback)


class QMTEngine(ITradingEngine):
    """
    Main QMT engine implementing ITradingEngine.

    This engine bridges platform-agnostic strategy code to the
    MiniQMT trading platform for live trading.
    """

    def __init__(
        self,
        ctx: TradingContext,
        market_adapter: IMarketAdapter,
        frequency_context: IFrequencyContext,
        client: 'MiniQMTClient' = None,
        slot_id: Optional[str] = None,
    ):
        """
        Initialize QMT engine.

        Args:
            ctx: TradingContext (single source of truth for market/instrument config)
            market_adapter: Market-specific adapter
            frequency_context: Frequency context for time scaling
            client: MiniQMT client for API calls
            slot_id: Deployment slot identifier; used as the log subdirectory name.
                Defaults to ``instrument_code`` when absent.
        """
        self._ctx = ctx
        self._market_adapter = market_adapter
        self._frequency_context = frequency_context
        self._client = client
        self._symbol = ctx.instrument_code
        self._slot_id = slot_id or self._symbol  # slot-unique log key; defaults to instrument_code

        # Create component instances
        self._market_data = QMTMarketData(symbol=self._symbol)
        self._portfolio = QMTPortfolio(client=client, symbol=self._symbol)
        self._order_manager = QMTOrderManager(
            client=client, symbol=self._symbol, portfolio=self._portfolio
        )
        self._logger = QMTLogger(name="QMTStrategy")
        self._event_bus = QMTEventBus()
        self._strategy_logger: Optional[IStrategyLogger] = None

        logger.info(
            f"QMTEngine initialized: market={ctx.market_code}, "
            f"instrument={ctx.instrument_name}, "
            f"frequency={frequency_context.bar_size.value}, "
            f"symbol={self._symbol}"
        )

    def load_data(self, indicators_path: str) -> None:
        """
        Load indicator data from CSV.

        Args:
            indicators_path: Path to indicators CSV file
        """
        self._market_data.load_indicators(indicators_path)

    def set_client(self, client: 'MiniQMTClient') -> None:
        """
        Set or update QMT client.

        Args:
            client: MiniQMT client
        """
        self._client = client
        self._portfolio.set_client(client)
        self._order_manager.set_client(client)

    def set_trading_contract(self, contract_code: str) -> None:
        """
        Set the specific contract code for order placement.

        The slot resolves the main contract (e.g. 'al2508') each day
        and calls this so orders go to the correct contract, not just
        the product code ('al').

        Args:
            contract_code: Full contract code (e.g. 'al2508')
        """
        self._order_manager.set_trading_contract(contract_code)
        logger.info(f"QMTEngine trading contract set to: {contract_code}")

    def refresh(self) -> None:
        """Refresh portfolio and position data from QMT."""
        self._portfolio.refresh()

    # ITradingEngine interface implementation

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

    def get_event_bus(self) -> IEventBus:
        """Get event bus interface."""
        return self._event_bus

    def get_strategy_logger(self) -> Optional[IStrategyLogger]:
        """
        Get strategy logger interface.

        Creates a CSVStrategyLogger on first call with append_mode=True
        for live/deployment trading (accumulates logs across sessions).

        Logs are written to ``workspace/deploy/slots/{slot_id}/qmt_{symbol}.csv``
        so each deployment slot gets its own isolated log directory.
        """
        if self._strategy_logger is None:
            output_dir = str(
                Path.cwd() / "workspace" / "deploy" / "slots" / self._slot_id
            )
            self._strategy_logger = CSVStrategyLogger(
                output_dir=output_dir,
                strategy_name=f"qmt_{self._symbol}",  # filename: qmt_{instrument_code}.csv
                enabled=True,
                append_mode=True,
            )
        return self._strategy_logger

    def get_trading_context(self) -> Optional[TradingContext]:
        """Get trading context with market/instrument configuration."""
        return self._ctx

    def get_market_adapter(self) -> IMarketAdapter:
        """Get market adapter."""
        return self._market_adapter

    def get_frequency_context(self) -> IFrequencyContext:
        """Get frequency context."""
        return self._frequency_context

    def get_current_symbol(self) -> str:
        """Get current trading symbol."""
        return self._symbol
