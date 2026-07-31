"""
Backtrader Strategy Bridge
==========================

Bridge between Backtrader's bt.Strategy and platform-agnostic strategy code.

This module provides get_strategy_class() which returns a configured
BacktraderStrategyBridge class that:
1. Implements Backtrader's bt.Strategy interface
2. Delegates trading logic to platform-agnostic strategy components
3. Uses ITradingEngine for all market data and order operations
4. Integrates with strategy logger for systematic output

Hook-Based Architecture:
    Market/frequency-specific features are handled via strategy hooks:
    - ForcedExitStrategyHook: Contract expiry handling (interday futures)
    - SessionAwareStrategyHook: Session context (intraday trading)

    Hooks are added to the strategy and called during BaseStrategy.on_bar()
    lifecycle via the Template Method pattern.

Architecture:
    BacktraderStrategyBridge (bt.Strategy)
        └── strategy_main (platform-agnostic)
                ├── hooks (ForcedExit, SessionAware, etc.)
                ├── entry_rule
                ├── exit_rule
                ├── risk_manager
                └── position_sizer
"""

from typing import Dict, Any, Type, Optional, TYPE_CHECKING
import backtrader as bt
import logging
from echolon.data.loaders.backtest_data_loader import load_indicator_metadata
from echolon.strategy.interfaces import OrderStatus
from echolon.backtest.logging_utils import get_run_context, should_log_details

if TYPE_CHECKING:
    from .backtrader_engine import BacktraderEngine

module_logger = logging.getLogger(__name__)


class BacktraderStrategyBridge(bt.Strategy):
    """
    Bridge between Backtrader and platform-agnostic strategy.

    Hook-based architecture:
    - Market/frequency-specific features handled via strategy hooks
    - ForcedExitStrategyHook: Processes forced exits in on_bar_start()
    - SessionAwareStrategyHook: Provides session context helpers

    This class:
    1. Receives bar events from Backtrader (next())
    2. Updates engine's market data references
    3. Delegates to platform-agnostic strategy via on_bar()
       (hooks are called automatically in BaseStrategy.on_bar())
    4. Logs all events to strategy logger
    """

    params = (
        ('engine', None),
        ('strategy_name', 'default'),
        ('market', 'SHFE'),
        ('instrument', 'aluminum'),  # Full name for metadata paths
        ('instrument_code', 'al'),   # Code for trading operations
        ('strategy_params', {}),
        ('printlog', True),
    )

    def __init__(self):
        """Initialize bridge with engine reference."""
        self._engine: Optional['BacktraderEngine'] = self.params.engine
        self._strategy_name = self.params.strategy_name
        self._market = self.params.market
        self._instrument = self.params.instrument  # Full name for metadata paths
        self._instrument_code = self.params.instrument_code  # Code for trading
        self._strategy_params = self.params.strategy_params
        self._printlog = self.params.printlog

        # Update engine components with Backtrader data feed
        if self._engine is not None:
            self._engine._market_data.set_data_feed(self.data)
            self._engine._portfolio.set_data_feed(self.data)
            self._engine._portfolio.set_broker(self.broker)
            self._engine._order_manager.set_strategy(self)
            self._engine._order_manager.set_data_feed(self.data)
            self._engine._order_manager.set_symbol(self._instrument_code)

        # Trade tracking
        self._trade_count = 0
        self._pending_orders = {}
        self._bar_count = 0

        # Cache strategy logger reference (avoids repeated method calls)
        self._strategy_logger = self._engine.get_strategy_logger() if self._engine else None

        # Register all available indicators with the trading engine BEFORE creating strategy
        self._register_indicators()

        # Initialize platform-agnostic strategy immediately
        self._agnostic_strategy = None
        self._start_called = False
        self._initialize_strategy()

        self.log(f"BacktraderStrategyBridge initialized: {self._strategy_name}")
        self.log(f"  Market: {self._market}, Instrument: {self._instrument} ({self._instrument_code})")
        freq_ctx = self._engine.get_frequency_context()
        if freq_ctx is not None:
            self.log(f"  Frequency: {freq_ctx.bar_size}")

    @property
    def agnostic_strategy(self):
        """Expose agnostic strategy for observers (e.g., contract expiry observer)."""
        return self._agnostic_strategy

    def log(self, txt: str, dt=None):
        """Log message with timestamp."""
        if self._printlog:
            dt = dt or self.data.datetime.date(0)
            print(f'{dt.isoformat()} {txt}')

    def _register_indicators(self):
        """
        Register all available data feed indicators with the trading engine.

        This method reads indicator metadata and registers each indicator line
        from the Backtrader data feed with the market data interface.
        """
        ctx = self._engine.get_trading_context()
        # Use per-slot metadata path if strategy_code_dir is set. The runner
        # threads indicators_backtest_dir into strategy params via
        # get_strategy_class — required for slot lookup, no env fallback.
        code_dir = self.p.strategy_code_dir
        from pathlib import Path
        ind_dir_param = getattr(self.p, 'indicators_backtest_dir', None)
        if ind_dir_param is None:
            from echolon.errors import raise_error
            raise_error(
                "CFG-003",
                function="BacktraderStrategyBridge._register_indicators",
                param="indicators_backtest_dir strategy param",
                paths_field="indicators_backtest_dir",
            )
        indicators_backtest_dir = Path(ind_dir_param)
        if code_dir is not None:
            slot_meta = indicators_backtest_dir / Path(code_dir).name / "strategy_indicator_metadata.json"
            if slot_meta.exists():
                metadata = load_indicator_metadata(ctx=ctx, metadata_path=str(slot_meta))
            else:
                metadata = load_indicator_metadata(ctx=ctx, indicator_dir=indicators_backtest_dir)
        else:
            metadata = load_indicator_metadata(ctx=ctx, indicator_dir=indicators_backtest_dir)

        registered_indicators = []
        failed_indicators = []

        if 'indicator_columns' in metadata:
            # Filter out non-numeric columns
            excluded_columns = {'date', 'contract', 'unnamed: 14', 'trading_date'}
            indicator_columns = [col for col in metadata['indicator_columns']
                               if col.lower() not in excluded_columns]

            for col in indicator_columns:
                # Convert to lowercase for line name (backtrader convention)
                line_name = col.lower()

                # Try to get the indicator from the data feed
                if hasattr(self.data, line_name):
                    indicator = getattr(self.data, line_name)
                    # Check if it's a line (indicator) by seeing if it has array-like access
                    if hasattr(indicator, '__getitem__'):
                        self._engine._market_data.register_indicator(line_name, indicator)
                        registered_indicators.append(line_name)
                    else:
                        failed_indicators.append(f"{line_name} (not array-like)")
                else:
                    failed_indicators.append(f"{line_name} (not found)")

        # Log indicator registration
        if module_logger.isEnabledFor(logging.INFO):
            module_logger.info(f"[STRATEGY_BRIDGE] Indicators | registered={len(registered_indicators)}")
            if failed_indicators:
                module_logger.warning(f"[STRATEGY_BRIDGE] Indicators | failed={len(failed_indicators)} (first 10: {failed_indicators[:10]})")

    def _initialize_strategy(self):
        """
        Initialize platform-agnostic strategy with appropriate hooks.

        Called once in __init__. Adds strategy hooks based on trading mode:
        - ForcedExitStrategyHook: For interday futures (contract expiry)
        - SessionAwareStrategyHook: For intraday trading (session context)

        Loads the strategy from `strategy_code_dir` (a required strategy
        param). The runner / EngineFactory caller is responsible for
        injecting it — typically defaulted from `paths.strategy_code_dir`
        via `BacktestRunner.__init__`. No env fallback: if the param
        wasn't injected, raise CFG-003 fail-loud rather than silently
        resolving against cwd / `ECHOLON_PROJECT_ROOT`.
        """
        from pathlib import Path
        from echolon.strategy.loader import StrategyLoader

        code_dir = self.p.strategy_code_dir
        if code_dir is None:
            from echolon.errors import raise_error
            raise_error(
                "CFG-003",
                function="BacktraderStrategyBridge._initialize_strategy",
                param="strategy_code_dir strategy param",
                paths_field="strategy_code_dir",
            )
        loader = StrategyLoader(Path(code_dir))
        strategy_main = loader.load_function("strategy", "strategy_main")
        strategy_dir_path = str(code_dir)

        # Pass strategy_dir so BaseStrategy resolves components via StrategyLoader.
        extra_kwargs = {'strategy_dir': strategy_dir_path}

        self._agnostic_strategy = strategy_main(
            trading_engine=self._engine,
            **self._strategy_params,
            **extra_kwargs,
        )

        # Add strategy hooks based on trading mode
        self._add_strategy_hooks()

        # Strategy's on_start is called in start() method
        # This matches the old architecture where on_start is called once

    def _add_strategy_hooks(self):
        """
        Add strategy hooks based on engine's market adapter and frequency context.

        Hook Composition:
            | Market | Frequency | ForcedExitHook | SessionAwareHook |
            |--------|-----------|----------------|------------------|
            | SHFE   | Interday  | ✅             | ❌               |
            | SHFE   | Intraday  | ❌             | ✅               |
            | Crypto | Intraday  | ❌             | ✅               |
            | Crypto | Interday  | ❌             | ❌               |
        """
        from echolon.strategy.frequency.interface import FrequencyType

        market_adapter = self._engine.get_market_adapter()
        frequency_context = self._engine.get_frequency_context()

        if market_adapter is None or frequency_context is None:
            return

        has_contract_expiry = getattr(market_adapter, 'has_contract_expiry', False)
        is_interday = frequency_context.frequency_type == FrequencyType.INTERDAY
        is_intraday = frequency_context.frequency_type == FrequencyType.INTRADAY

        hooks_added = []

        # ForcedExitStrategyHook: For interday futures trading
        if has_contract_expiry and is_interday:
            from echolon.strategy.hooks.forced_exit_strategy_hook import ForcedExitStrategyHook
            self._agnostic_strategy.add_hook(ForcedExitStrategyHook(market_adapter))
            hooks_added.append("ForcedExitStrategyHook")

        # SessionAwareStrategyHook: For intraday trading
        if is_intraday:
            from echolon.strategy.hooks.session_aware_strategy_hook import SessionAwareStrategyHook
            self._agnostic_strategy.add_hook(SessionAwareStrategyHook())
            hooks_added.append("SessionAwareStrategyHook")

        if hooks_added:
            self.log(f"Strategy hooks added: {', '.join(hooks_added)}")

    def start(self):
        """
        Called when the strategy starts (Backtrader lifecycle).

        Following old architecture pattern: call on_start() once here.
        """
        if not self._start_called:
            self._agnostic_strategy.on_start()
            self._start_called = True

    def notify_order(self, order):
        """Handle Backtrader order notifications, logging to the strategy logger."""
        # Update order status in order manager
        status_map = {
            order.Submitted: OrderStatus.SUBMITTED,
            order.Accepted: OrderStatus.ACCEPTED,
            order.Completed: OrderStatus.FILLED,
            order.Canceled: OrderStatus.CANCELLED,
            order.Margin: OrderStatus.REJECTED,
            order.Rejected: OrderStatus.REJECTED,
        }
        new_status = status_map.get(order.status, OrderStatus.PENDING)
        self._engine._order_manager.update_order_status(order.ref, new_status)

        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status == order.Completed:
            action = 'BUY' if order.isbuy() else 'SELL'
            # Per-trade prints gated by run_context (debug/best_trial only).
            # In summary/optimization mode this would drown the one-line
            # Sharpe summary; rejection paths below stay unconditional.
            if should_log_details(get_run_context()):
                self.log(f'{action} EXECUTED: Price={order.executed.price:.2f}, '
                         f'Size={order.executed.size}, Comm={order.executed.comm:.2f}')

            # Log to strategy logger
            if self._strategy_logger is not None:
                self._strategy_logger.log_order_event({
                    'action': 'executed',
                    'status': 'Executed',
                    'ref': order.ref,
                    'side': action,
                    'price': order.executed.price,
                    'size': order.executed.size,
                    'commission': order.executed.comm,
                    'datetime': self.data.datetime.datetime(0).isoformat(),
                })

        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            status_name = order.Status[order.status]
            self.log(f'Order Failed: {status_name}')

            # Log to strategy logger
            if self._strategy_logger is not None:
                self._strategy_logger.log_order_event({
                    'action': 'failed',
                    'status': status_name,
                    'ref': order.ref,
                    'datetime': self.data.datetime.datetime(0).isoformat(),
                })

    def notify_trade(self, trade):
        """Handle Backtrader trade notifications, logging to the strategy logger."""
        if not trade.isclosed:
            return

        self._trade_count += 1
        # Per-trade prints gated by run_context (debug/best_trial only).
        if should_log_details(get_run_context()):
            self.log(f'TRADE #{self._trade_count} CLOSED: '
                     f'PnL Gross={trade.pnl:.2f}, Net={trade.pnlcomm:.2f}')

        # Add realized PnL to portfolio tracker
        self._engine._portfolio.add_realized_pnl(trade.pnlcomm)

        # Log to strategy logger
        if self._strategy_logger is not None:
            self._strategy_logger.log_trade_event({
                'trade_id': self._trade_count,
                'pnl_gross': trade.pnl,
                'pnl_net': trade.pnlcomm,
                'commission': trade.commission,
                'datetime': self.data.datetime.datetime(0).isoformat(),
            })

    def next(self):
        """
        Called on each bar - main entry point for strategy logic.

        Hook-based architecture: All market/frequency-specific features
        (forced exits, session context) are handled via strategy hooks
        in BaseStrategy.on_bar() lifecycle:
        1. hook.on_bar_start() - ForcedExitStrategyHook processes exits here
        2. strategy._execute_bar() - Strategy-specific logic
        3. hook.on_bar_end() - Cleanup
        """
        self._bar_count += 1

        # Get context for conditional logging
        run_context = get_run_context()
        log_details = should_log_details(run_context)

        # Log bar start (debug/best_trial only)
        if log_details:
            current_price = self.data.close[0]
            position_size = self.broker.getposition(self.data).size
            module_logger.info(
                f"[{run_context.upper()}] Bar {self._bar_count} | START | "
                f"datetime={self.data.datetime.datetime(0).isoformat()}, "
                f"price={current_price:.2f}, position={position_size}"
            )

        # Start new bar in strategy logger
        if self._strategy_logger is not None and hasattr(self._strategy_logger, 'start_new_bar'):
            self._strategy_logger.start_new_bar()
            self._strategy_logger.log_strategy_state({
                'bar_count': self._bar_count,
                'datetime': self.data.datetime.datetime(0).strftime('%Y-%m-%d %H:%M:%S'),
            })

        # Delegate to platform-agnostic strategy
        # Hook lifecycle (forced exits, session context) handled in on_bar()
        # BT-001: translate raw strategy exceptions into EchelonError with bar context
        try:
            self._agnostic_strategy.on_bar()
        except Exception as exc:
            _wrap_on_bar_exception(
                exc=exc,
                bar_index=len(self),  # backtrader convention
                trading_date=(
                    self.data.datetime.date(0)
                    if hasattr(self.data, "datetime") else None
                ),
                contract=(
                    str(self.data._name) if hasattr(self.data, "_name") else None
                ),
                position_size=(self.position.size if self.position else 0),
                file=(
                    type(self._agnostic_strategy).__module__
                    if self._agnostic_strategy is not None else __name__
                ),
            )

        # Log bar end with position change detection (debug/best_trial only)
        if log_details:
            new_position_size = self.broker.getposition(self.data).size
            position_changed = new_position_size != position_size
            equity = self.broker.getvalue()
            module_logger.info(
                f"[{run_context.upper()}] Bar {self._bar_count} | END | "
                f"position={new_position_size}, changed={position_changed}, equity={equity:.2f}"
            )

        # Finalize bar in strategy logger
        if self._strategy_logger is not None and hasattr(self._strategy_logger, 'finalize_bar'):
            self._strategy_logger.finalize_bar()

    def stop(self):
        """Called when backtest ends."""
        # Call strategy's on_stop if available
        self._agnostic_strategy.on_stop()

        # Finalize strategy logger
        if self._strategy_logger is not None:
            log_path = self._strategy_logger.finalize_logging()
            if log_path:
                self.log(f'Strategy log saved to: {log_path}')

        self.log(f'Strategy finished. Total trades: {self._trade_count}')
        self.log(f'Final Portfolio Value: {self.broker.getvalue():,.2f}')


# Cache for dynamically created strategy classes (for pickle compatibility)
_STRATEGY_CLASS_CACHE: Dict[str, Type[bt.Strategy]] = {}

from echolon.config.markets.core.context import TradingContext


def get_strategy_class(
    ctx: TradingContext,
    strategy_code_dir: Optional[str] = None,
    indicators_backtest_dir: Optional[str] = None,
) -> Type[bt.Strategy]:
    """Get Backtrader-compatible strategy class based on TradingContext.

    Args:
        ctx: TradingContext (single source of truth for market/instrument config)
        strategy_code_dir: Optional path to strategy code directory.
        indicators_backtest_dir: Optional indicators-backtest root used to
            resolve per-slot ``strategy_indicator_metadata.json``.
    """
    strategy_name = 'default'
    market = ctx.market_code
    instrument = ctx.instrument_name
    instrument_code = ctx.instrument_code

    cache_key = (
        f"{strategy_name}_{market}_{instrument}_{instrument_code}"
        f"_{strategy_code_dir or 'default'}_{indicators_backtest_dir or 'default'}"
    )

    # Return cached class if exists (required for pickle compatibility)
    if cache_key in _STRATEGY_CLASS_CACHE:
        return _STRATEGY_CLASS_CACHE[cache_key]

    # Create class name that's valid for pickle
    class_name = f'Bridge_{strategy_name}'

    # Create subclass with config-based params
    # Engine will be injected by engine.setup() via strategy_params
    strategy_class = type(
        class_name,
        (BacktraderStrategyBridge,),
        {
            'params': (
                ('engine', None),  # Injected by engine.setup()
                ('strategy_name', strategy_name),
                ('market', market),
                ('instrument', instrument),  # Full name for metadata paths
                ('instrument_code', instrument_code),  # Code for trading
                ('strategy_params', {}),
                ('strategy_code_dir', strategy_code_dir),  # Custom strategy dir (None = platform_agnostic)
                ('indicators_backtest_dir', indicators_backtest_dir),
                ('printlog', True),
            )
        }
    )

    # Register class in module namespace for pickle compatibility
    # Pickle requires the class to be findable via module.class_name
    strategy_class.__module__ = __name__
    strategy_class.__qualname__ = class_name
    globals()[class_name] = strategy_class

    # Cache the class
    _STRATEGY_CLASS_CACHE[cache_key] = strategy_class

    return strategy_class


# =============================================================================
# BT-001 helper: translate raw strategy exceptions into EchelonError
# =============================================================================

from echolon.errors import raise_error


def _wrap_on_bar_exception(
    exc: Exception,
    bar_index: int,
    trading_date,
    contract,
    position_size,
    file: str,
) -> None:
    """Translate a raw strategy exception into a BT-001 EchelonError with
    bar-level context so an LLM reading logs can locate the failure."""
    raise_error(
        "BT-001",
        file=file,
        bar_index=bar_index,
        trading_date=str(trading_date),
        contract=str(contract),
        position_size=position_size,
        exception_repr=f"{type(exc).__name__}: {exc}",
    )
