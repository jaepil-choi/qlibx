"""
MiniQMT Client
==============

Low-level wrapper for MiniQMT API (xtquant).

Ported from QTS_deploy/miniqmt/miniqmt_client.py with the following changes:
- Uses QMTAccountConfig from deploy_config instead of old TradeConfig
- Proper relative imports (no sys.path hacks)
- Standard logging via logging.getLogger(__name__)
- EXEMPT from no-try-except policy (external API boundary)

Handles:
- Connection management (connect, disconnect)
- Order placement with night market scheduling (APScheduler)
- Position and account queries
- Callback registration for order/trade events

Reference:
- Data API: https://dict.thinktrader.net/nativeApi/xtdata.html
- Trading API: https://dict.thinktrader.net/nativeApi/xttrader.html
"""

import datetime
import logging
import os
import random
import threading
import time
import traceback
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

import pandas as pd

from xtquant import xtconstant, xtdata
from xtquant.xttrader import XtQuantTrader, XtQuantTraderCallback
from xtquant.xttype import StockAccount

from ...config.deploy_config import QMTAccountConfig
from ...config.order_policy import (
    BUFFER_TICKS_BY_ATTEMPT,
    DEFAULT_BUFFER_TICKS,
    TICK_SNAPSHOT_MAX_AGE_S,
)
from echolon.errors import raise_error


def _is_tick_fresh(tick: Optional[Dict[str, Any]]) -> bool:
    """Return True if the tick snapshot's `time` field is within
    TICK_SNAPSHOT_MAX_AGE_S of now. Stale or missing time → False.
    """
    if tick is None:
        return False
    ts_ms = tick.get("time", 0)
    try:
        ts_ms = float(ts_ms)
    except (TypeError, ValueError):
        return False
    if ts_ms <= 0:
        return False
    age_s = (datetime.datetime.now().timestamp() * 1000 - ts_ms) / 1000.0
    return age_s <= TICK_SNAPSHOT_MAX_AGE_S

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Error helpers (LIV-001)
# ---------------------------------------------------------------------------


def _raise_broker_unavailable(account_id: str, error: str) -> None:
    """Raise LIV-001 when the miniQMT client can't connect or loses connection."""
    raise_error(
        "LIV-001",
        platform="miniqmt",
        account_id=account_id,
        error=error,
    )


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class OrderInfo:
    """Order information structure."""
    order_id: int
    symbol: str
    intent: str
    price: float
    volume: int
    order_type: str
    timestamp: datetime.datetime
    status: str = "PENDING"


@dataclass
class PositionInfo:
    """Position information structure."""
    symbol: str
    volume: int
    avg_price: float
    unrealized_pnl: float
    market_value: float
    direction: str


# ---------------------------------------------------------------------------
# Callback
# ---------------------------------------------------------------------------

class MiniQMTCallback(XtQuantTraderCallback):
    """Callback handler for miniQMT events."""

    def __init__(self, client: "MiniQMTClient"):
        super().__init__()
        self.client = client

    def on_disconnected(self):
        """Handle disconnection events."""
        logger.warning("miniQMT connection lost!")
        self.client.is_connected = False

    def on_order_stock_async_response(self, response):
        """Handle async order response — maps seq_id to real order_id.

        Called by xtquant after order_stock_async(). The response object
        contains .seq (the sequence ID returned by order_stock_async)
        and .order_id (the real exchange order ID used in all subsequent
        callbacks).
        """
        seq = getattr(response, 'seq', 0)
        order_id = getattr(response, 'order_id', 0)
        logger.info("Async response: seq=%s -> order_id=%s", seq, order_id)
        if hasattr(self.client, "async_response_callback") and self.client.async_response_callback:
            self.client.async_response_callback(seq, order_id)

    def on_stock_order(self, order):
        """Handle order status updates."""
        logger.info(
            "Order update: %s - Status: %s", order.order_id, order.order_status
        )
        if hasattr(self.client, "order_callback") and self.client.order_callback:
            self.client.order_callback(order)

    def on_stock_trade(self, trade):
        """Handle trade execution updates."""
        logger.info(
            "Trade executed: %s - Price: %s, Volume: %s",
            trade.order_id,
            trade.traded_price,
            trade.traded_volume,
        )
        if hasattr(self.client, "trade_callback") and self.client.trade_callback:
            self.client.trade_callback(trade)


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class MiniQMTClient:
    """
    Main client class for interacting with miniQMT platform.

    Features:
    - Connection management with automatic reconnection
    - Market data downloading and retrieval
    - Real-time data subscription and streaming
    - Order placement and management (with night-market scheduling)
    - Position monitoring
    - Error handling and logging
    """

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def __init__(
        self,
        config: QMTAccountConfig,
        session_id: Optional[int] = None,
        market: Optional[str] = None,
        asset: Optional[str] = None,
    ):
        """
        Initialize the miniQMT client.

        Args:
            config: QMTAccountConfig with qmt_path, account_id, account_type.
            session_id: Explicit session ID.  Generated randomly if None.
            market: Market code (e.g., "SHFE") for calendar lookups.
            asset: Asset name (e.g., "aluminum") for calendar lookups.
        """
        self.config = config
        self.session_id = session_id
        self.market = market
        self.asset = asset

        self.trader: Optional[XtQuantTrader] = None
        self.account: Optional[StockAccount] = None
        self.is_connected: bool = False
        self.is_subscribed: bool = False

        # Real-time data subscription management
        self.subscribed_symbols: set = set()
        self.realtime_data_cache: Dict[str, Any] = {}

        # Callbacks
        self.order_callback: Optional[Callable] = None
        self.trade_callback: Optional[Callable] = None
        self.market_data_callback: Optional[Callable] = None

        # Data storage
        self.market_data_cache: Dict[str, Any] = {}
        self.orders: Dict[int, OrderInfo] = {}
        self.positions: Dict[str, PositionInfo] = {}

        # Thread safety — locks for the live paths only
        self.data_lock = threading.Lock()
        self.subscription_lock = threading.Lock()

        logger.info("MiniQMT Client initialized for account: %s", config.account_id)

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        """
        Connect to miniQMT platform.

        Returns:
            True if connection successful, False otherwise.
        """
        try:
            # Generate session ID if not provided
            if self.session_id is None:
                self.session_id = int(random.randint(100000, 999999))

            logger.info("Connecting to miniQMT with session: %s", self.session_id)

            # Check if QMT path exists
            if not os.path.exists(self.config.qmt_path):
                logger.error("QMT path does not exist: %s", self.config.qmt_path)
                return False

            # Initialize trader
            self.trader = XtQuantTrader(self.config.qmt_path, self.session_id)
            logger.info("QMT Path: %s", self.config.qmt_path)
            logger.info("Session ID: %s", self.session_id)

            # Set callback
            callback = MiniQMTCallback(self)
            self.trader.register_callback(callback)

            # Start trader
            logger.info("Starting XtQuantTrader...")
            self.trader.start()

            # Wait for startup
            time.sleep(3)

            # Connect
            logger.info("Attempting to connect to miniQMT...")
            connect_result = self.trader.connect()
            if connect_result != 0:
                logger.error(
                    "Failed to connect to miniQMT. Error code: %s", connect_result
                )
                return False

            logger.info("Successfully connected to miniQMT")

            # Set up account
            if not self._setup_account():
                return False

            self.is_connected = True
            return True

        except Exception as exc:
            logger.error("Connection error: %s", exc)
            logger.error("Full traceback: %s", traceback.format_exc())
            return False

    def _setup_account(self) -> bool:
        """Set up trading account."""
        self.account = StockAccount(
            self.config.account_id, self.config.account_type
        )

        # Subscribe to account
        subscribe_result = self.trader.subscribe(self.account)
        if subscribe_result != 0:
            logger.error("Failed to subscribe to account: %s", subscribe_result)
            return False

        self.is_subscribed = True
        logger.info(
            "Successfully subscribed to account: %s", self.config.account_id
        )

        # Get account info
        account_info = self.trader.query_stock_asset(self.account)
        if account_info:
            available_cash = account_info.m_dCash
            logger.info(
                "Account %s - Available cash: %.2f",
                self.config.account_id,
                available_cash,
            )

        return True

    def disconnect(self):
        """Disconnect from miniQMT platform."""
        try:
            if self.trader and self.is_connected:
                self.trader.stop()
                logger.info("Disconnected from miniQMT")
            self.is_connected = False
            self.is_subscribed = False
        except Exception as exc:
            logger.error("Disconnect error: %s", exc)

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self):
        """Context manager entry."""
        if self.connect():
            return self
        _raise_broker_unavailable(
            account_id=self.config.account_id,
            error="connect() returned False; see logs above for error code and traceback",
        )

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.disconnect()

    # ------------------------------------------------------------------
    # Real-time data
    # ------------------------------------------------------------------

    def subscribe_tick(self, symbol: str) -> bool:
        """Subscribe to tick-level data for a futures symbol.

        Optional warm-up: get_full_tick() works without subscription,
        but subscribing ensures the local cache stays fresh during
        the wait period before order firing.

        Args:
            symbol: Contract code with suffix (e.g. 'al2605.SF').

        Returns:
            True if subscription successful or already active.
        """
        cache_key = f"{symbol}_tick"
        with self.subscription_lock:
            if cache_key in self.subscribed_symbols:
                return True

        try:
            result = xtdata.subscribe_quote(
                stock_code=symbol,
                period="tick",
                count=-1,
                start_time="",
                end_time="",
            )
            if result == 1:
                with self.subscription_lock:
                    self.subscribed_symbols.add(cache_key)
                logger.info("Tick subscription active: %s", symbol)
                return True
            else:
                logger.error("Tick subscription failed for %s: %s", symbol, result)
                return False
        except Exception as exc:
            logger.error("Tick subscription error for %s: %s", symbol, exc)
            return False

    def _get_tick_snapshot(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Read the latest tick snapshot via get_full_tick.

        Returns:
            Dict with askPrice (list[5]), bidPrice (list[5]),
            lastPrice, etc., or None.
        """
        try:
            data = xtdata.get_full_tick([symbol])
            if not data or symbol not in data:
                return None
            tick = data[symbol]
            if not isinstance(tick, dict) or not tick:
                return None
            return tick
        except Exception as exc:
            logger.warning("Tick snapshot failed for %s: %s", symbol, exc)
            return None

    def resolve_aggressive_price(
        self, symbol: str, intent: str, attempt: int = 1, atr_ticks: int = 0,
    ) -> Tuple[int, float]:
        """Resolve price_type and price for aggressive (market-like) order.

        Returns FIX_PRICE with a price derived from live market data,
        or falls back to LATEST_PRICE as last resort.

        Tier 1: Counterparty price (ask1 for buy, bid1 for sell) +/- buffer
        Tier 2: Last traded price +/- buffer
        Tier 3: LATEST_PRICE (let QMT resolve internally)

        Both Tier 1 and Tier 2 apply ``(BUFFER_TICKS_BY_ATTEMPT[attempt] +
        atr_ticks) * price_tick`` — past the touch on Tier 1, around
        lastPrice on Tier 2. Yesterday's al_s1 bug submitted FIX_PRICE
        @ bid1=24645 with zero buffer; the market moved through 24645
        within seconds and never returned. The buffer keeps the order
        marketable.

        Args:
            symbol: Contract code with suffix (e.g. 'al2605.SF').
            intent: Order intent ('ENTRY_LONG', 'EXIT_LONG', etc.).
            attempt: Submission attempt number (1=first, 2+=resubmit).
            atr_ticks: Layer 3 ATR-aware additive buffer (in ticks). The
                caller computes ``ceil(ATR / price_tick * factor)`` from
                the slot's indicator data and passes it; default 0 keeps
                Layer 1 behavior.

        Returns:
            Tuple of (price_type constant, resolved price).
        """
        is_buy = intent in (
            "ENTRY_LONG", "EXIT_SHORT", "ROLLOVER_OPEN",
        )
        base_ticks = BUFFER_TICKS_BY_ATTEMPT.get(attempt, DEFAULT_BUFFER_TICKS)
        buffer_ticks = base_ticks + max(0, int(atr_ticks))

        # Look up tick size once — needed by both Tier 1 and Tier 2.
        detail = xtdata.get_instrument_detail(symbol)
        price_tick = float(detail.get("PriceTick", 5)) if detail else 5.0
        buffer = buffer_ticks * price_tick

        # Tier 1: counterparty price + buffer past the touch.
        # Skip Tier 1 if tick is stale (TICK_SNAPSHOT_MAX_AGE_S=2.0s).
        # The tick snapshot's `time` field is checked: a stale tick is a
        # symptom of broken subscription / outage and using it would risk
        # filling at a price that no longer reflects the live market.
        tick = self._get_tick_snapshot(symbol)
        if tick is not None and not _is_tick_fresh(tick):
            logger.warning(
                "Tick stale for %s (age > %ss) — skipping Tier 1, falling through",
                symbol, TICK_SNAPSHOT_MAX_AGE_S,
            )
            tick = None
        if tick is not None:
            if is_buy:
                ask_prices = tick.get("askPrice")
                if ask_prices is not None:
                    ask1 = ask_prices[0] if hasattr(ask_prices, '__getitem__') else 0
                    if ask1 and float(ask1) > 0:
                        ask1 = float(ask1)
                        price = ask1 + buffer
                        logger.info(
                            "Price resolved [Tier1 ask1+buf]: %s %.2f "
                            "(ask1=%.2f, buf=%.2f, attempt=%d)",
                            symbol, price, ask1, buffer, attempt,
                        )
                        return xtconstant.FIX_PRICE, price
            else:
                bid_prices = tick.get("bidPrice")
                if bid_prices is not None:
                    bid1 = bid_prices[0] if hasattr(bid_prices, '__getitem__') else 0
                    if bid1 and float(bid1) > 0:
                        bid1 = float(bid1)
                        price = bid1 - buffer
                        logger.info(
                            "Price resolved [Tier1 bid1-buf]: %s %.2f "
                            "(bid1=%.2f, buf=%.2f, attempt=%d)",
                            symbol, price, bid1, buffer, attempt,
                        )
                        return xtconstant.FIX_PRICE, price

            # Tier 2: lastPrice +/- buffer
            last_price = tick.get("lastPrice", 0)
            if last_price and float(last_price) > 0:
                last_price = float(last_price)
                price = last_price + buffer if is_buy else last_price - buffer
                logger.info(
                    "Price resolved [Tier2 last+buf]: %s %.2f "
                    "(last=%.2f, buf=%.2f, attempt=%d)",
                    symbol, price, last_price, buffer, attempt,
                )
                return xtconstant.FIX_PRICE, price

        # Tier 3: LATEST_PRICE — let QMT resolve internally.
        # This won't work on sim accounts but is acceptable: if we
        # reached here, tick data is empty/invalid and there's nothing
        # better to do.
        logger.warning(
            "Tier1/2 failed for %s — falling back to LATEST_PRICE",
            symbol,
        )
        return xtconstant.LATEST_PRICE, -1

    def download_main_contract_history(
        self, futures_code: str, xuntou_code: str,
    ) -> pd.DataFrame:
        """
        Download full main contract history via QMT's xtdata connection.

        Replicates the logic from SHFEApiMinuteExtractor._download_main_contract_history
        but uses the QMT desktop xtdata connection (no xtdc required).

        Args:
            futures_code: Futures product code (e.g. 'al').
            xuntou_code: Exchange code (e.g. 'SF').

        Returns:
            DataFrame with columns ``[date, main_contract]``.
        """
        symbol = f"{futures_code}00.{xuntou_code}"
        period = "historymaincontract"

        logger.info("Downloading main contract history for %s", symbol)

        xtdata.download_history_data(symbol, period, '', '')
        data_dict = xtdata.get_market_data_ex([], [symbol], period)

        if not data_dict or symbol not in data_dict:
            logger.warning("No main contract data for %s", symbol)
            return pd.DataFrame()

        df = data_dict[symbol].copy()

        # Convert timestamp to date
        df['date'] = pd.to_datetime(df['time'], unit='ms')
        df['date'] = df['date'].dt.strftime('%Y-%m-%d')

        # Rename Chinese column and filter
        df_filtered = df[['date', '期货统一规则代码']].copy()
        df_filtered.rename(
            columns={'期货统一规则代码': 'main_contract'}, inplace=True,
        )

        logger.info(
            "Main contract history downloaded: %d entries", len(df_filtered),
        )
        return df_filtered

    # ------------------------------------------------------------------
    # Order placement
    # ------------------------------------------------------------------

    def submit_order_async(
        self,
        symbol: str,
        volume: int,
        price: Optional[float],
        order_type: str,
        intent: str,
        strategy_name: str = "DolphinQuantStrategy",
    ) -> Optional[int]:
        """
        Submit order via xtquant order_stock_async (non-blocking).

        Returns a sequence ID immediately; the real order_id arrives later
        via the order callback. Used by PortfolioTradingRunner for
        burst-fire — all slots' orders hit QMT within ~50ms instead of
        being sequenced one-by-one.

        Args:
            symbol: Contract code (e.g. 'al2508.SF')
            volume: Number of lots
            price: Limit price (None for market order)
            order_type: 'MARKET' or 'LIMIT'
            intent: 'ENTRY_LONG', 'ENTRY_SHORT', 'EXIT_LONG', 'EXIT_SHORT'
            strategy_name: Strategy name for QMT tracking

        Returns:
            Sequence ID (>0) on success, None on failure.
            The real order_id will arrive via order callback.
        """
        # Price type — use 3-tier aggressive pricing for market orders
        # LATEST_PRICE doesn't work on sim accounts and can fail at market
        # open when no last traded price exists. FIX_PRICE with resolved
        # counterparty/limit price works universally.
        if order_type.upper() == "MARKET" or price is None:
            price_type, price = self.resolve_aggressive_price(symbol, intent)
        else:
            price_type = xtconstant.FIX_PRICE

        # Map intent to xtconstant order type
        intent_map = {
            "ENTRY_LONG": xtconstant.FUTURE_OPEN_LONG,
            "ENTRY_SHORT": xtconstant.FUTURE_OPEN_SHORT,
            "EXIT_LONG": xtconstant.FUTURE_CLOSE_LONG_HISTORY,
            "EXIT_SHORT": xtconstant.FUTURE_CLOSE_SHORT_HISTORY,
            # "EXIT_LONG": xtconstant.FUTURE_CLOSE_LONG_TODAY,
            # "EXIT_SHORT": xtconstant.FUTURE_CLOSE_SHORT_TODAY,
            "FORCED_EXIT": xtconstant.FUTURE_CLOSE_LONG_HISTORY,
            "ROLLOVER_CLOSE": xtconstant.FUTURE_CLOSE_LONG_HISTORY,
            "ROLLOVER_OPEN": xtconstant.FUTURE_OPEN_LONG,
        }
        side = intent_map.get(intent)
        if side is None:
            logger.error("Unknown order intent: %s", intent)
            return None

        # Ensure .SF suffix for SHFE contracts
        if not symbol.endswith(".SF"):
            product_code = "".join(c for c in symbol if c.isalpha()).lower()
            shfe_products = {
                "al", "cu", "zn", "pb", "ni", "sn", "au", "ag",
                "rb", "hc", "ss", "bu", "ru", "fu", "sp", "nr",
            }
            if product_code in shfe_products:
                symbol = symbol + ".SF"
        print(f'debug: submit_order_async - symbol={symbol}, volume={volume}, price={price}, order_type={order_type}, intent={intent}, strategy_name={strategy_name}')
        try:
            seq_id = self.trader.order_stock_async(
                account=self.account,
                stock_code=symbol,
                order_type=side,
                order_volume=volume,
                price_type=price_type,
                price=price,
                strategy_name=strategy_name,
                order_remark=(
                    f"{intent}_{volume}_"
                    f"{datetime.datetime.now().strftime('%H%M%S')}"
                ),
            )
            logger.info(
                "Async order submitted: %s %s x %d, seq_id=%s",
                intent, symbol, volume, seq_id,
            )
            return seq_id if seq_id is not None and seq_id > 0 else None

        except Exception as exc:
            logger.error("order_stock_async failed: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Order management
    # ------------------------------------------------------------------

    def cancel_order(self, order_id: int) -> bool:
        """
        Cancel a pending order.

        Args:
            order_id: Order ID to cancel.

        Returns:
            True if cancellation successful.
        """
        if not self.is_connected:
            logger.error("Not connected to miniQMT")
            return False

        try:
            result = self.trader.cancel_order_stock(self.account, order_id)
            if result == 0:
                logger.info("Order %s cancelled successfully", order_id)

                if order_id in self.orders:
                    self.orders[order_id].status = "CANCELLED"

                return True
            else:
                logger.error("Failed to cancel order %s: %s", order_id, result)
                return False

        except Exception as exc:
            logger.error("Order cancellation error: %s", exc)
            return False

    def query_stock_trades(self) -> List[Dict[str, Any]]:
        """
        Query all stock trades for the account.

        Returns:
            List of trade dictionaries with trade execution details.
        """
        if not self.is_connected:
            logger.error("Not connected to miniQMT")
            return []

        try:
            logger.info("Querying stock trades...")

            trades = None
            if hasattr(self.trader, "query_stock_trades"):
                trades = self.trader.query_stock_trades(self.account)
                logger.info("query_stock_trades returned: %s", trades)

            if hasattr(self.trader, "query_history_trades"):
                try:
                    hist_trades = self.trader.query_history_trades(self.account)
                    logger.info("query_history_trades returned: %s", hist_trades)
                    if hist_trades and not trades:
                        trades = hist_trades
                except Exception as hist_exc:
                    logger.warning(
                        "query_history_trades failed: %s", hist_exc
                    )

            if not trades:
                logger.info("No trades found with any query method")
                return []

            trade_list = []
            for trade in trades:
                try:
                    commission = None
                    for attr in (
                        "commission",
                        "m_dCommission",
                        "traded_commission",
                        "business_commission",
                    ):
                        value = getattr(trade, attr, None)
                        if isinstance(value, (int, float)):
                            commission = float(value)
                            break
                    trade_dict = {
                        "order_id": getattr(trade, "order_id", "N/A"),
                        "stock_code": getattr(trade, "stock_code", "N/A"),
                        "order_type": getattr(trade, "order_type", "N/A"),
                        "traded_id": getattr(trade, "traded_id", ""),
                        "traded_time": getattr(trade, "traded_time", ""),
                        "traded_price": getattr(trade, "traded_price", 0.0),
                        "traded_volume": getattr(trade, "traded_volume", 0),
                        "traded_amount": getattr(trade, "traded_amount", 0.0),
                        "commission": commission,
                        "strategy_name": getattr(trade, "strategy_name", ""),
                        "order_remark": getattr(trade, "order_remark", ""),
                    }
                    trade_list.append(trade_dict)
                except Exception as parse_exc:
                    logger.error("Error parsing trade: %s", parse_exc)
                    logger.error("Trade object: %s", trade)
                    logger.error("Trade attributes: %s", dir(trade))

            logger.info("Found %d trades", len(trade_list))
            return trade_list

        except Exception as exc:
            logger.error("Failed to query stock trades: %s", exc)
            logger.error("Full traceback: %s", traceback.format_exc())
            return []

    # ------------------------------------------------------------------
    # Positions & account
    # ------------------------------------------------------------------

    def get_positions(self) -> Dict[str, PositionInfo]:
        """
        Get current positions via trader.query_position_statistics.

        Direction codes from xtquant:
        - 48 = LONG
        - 49 = SHORT

        Returns:
            Dictionary of PositionInfo keyed by symbol.
        """
        if not self.is_connected:
            logger.error("Not connected to miniQMT")
            return {}

        positions = self.trader.query_position_statistics(self.account)

        position_dict: Dict[str, PositionInfo] = {}

        for pos in positions:
            if hasattr(pos, "instrument_id"):
                symbol = getattr(pos, "instrument_id")
                volume = getattr(pos, "position")
                avg_price = getattr(pos, "avg_price")
                unrealized_pnl = getattr(pos, "float_profit")
                market_value = getattr(pos, "instrument_value")
                direction_code = getattr(pos, "direction")

                if direction_code == 48:
                    direction = "LONG"
                elif direction_code == 49:
                    direction = "SHORT"
                else:
                    direction = f"UNKNOWN_{direction_code}"

                logger.info(
                    "Found position: %s, volume: %s, avg_price: %s",
                    symbol,
                    volume,
                    avg_price,
                )

                # Skip positions with zero volume
                if volume == 0:
                    logger.info("Skipping zero-volume position: %s", symbol)
                    continue

                position_info = PositionInfo(
                    symbol=symbol,
                    volume=volume,
                    avg_price=avg_price,
                    unrealized_pnl=unrealized_pnl,
                    market_value=market_value,
                    direction=direction,
                )

                position_dict[symbol] = position_info

        with self.data_lock:
            self.positions = position_dict

        return position_dict

    def get_account_info(self) -> Optional[Dict[str, Any]]:
        """
        Get account information via trader.query_stock_asset.

        Returns:
            Dictionary with account_id, cash, total_asset,
            market_value, frozen_cash, available_cash.
        """
        if not self.is_connected:
            logger.error("Not connected to miniQMT")
            return None

        try:
            account_info = self.trader.query_stock_asset(self.account)

            return {
                "account_id": self.config.account_id,
                "cash": account_info.m_dCash,
                "total_asset": account_info.m_dTotalAsset,
                "market_value": account_info.m_dMarketValue,
                "frozen_cash": account_info.m_dFrozenCash,
                "available_cash": account_info.m_dCash,
            }

        except Exception as exc:
            logger.error("Failed to get account info: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def set_callbacks(
        self,
        order_callback: Optional[Callable] = None,
        trade_callback: Optional[Callable] = None,
        market_data_callback: Optional[Callable] = None,
        async_response_callback: Optional[Callable] = None,
    ):
        """Set callback functions for order, trade, and market data events."""
        self.order_callback = order_callback
        self.trade_callback = trade_callback
        self.market_data_callback = market_data_callback
        self.async_response_callback = async_response_callback
