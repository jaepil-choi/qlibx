"""
Platform-Agnostic Base Strategy Class
=====================================

Base class for trading strategies, decoupled from any specific platform
(Backtrader, MiniQMT, etc.). Strategies inherit from ``BaseStrategy`` and
interact with the platform via the ``ITradingEngine`` interface.

Architecture:
    BaseStrategy provides UNIVERSAL functionality only.
    Market/frequency-specific features are added via HOOKS.

    Hooks (added based on trading mode):
    - SessionAwareStrategyHook: For intraday (session context helpers)
    - ForcedExitStrategyHook: For interday futures (contract expiry handling)

Features:
- Platform-agnostic design (interfaces, not concrete platform classes)
- Standardized parameter handling
- Common lifecycle methods
- Trade tracking and logging
- Component management (entry, exit, risk, sizer)
- Systematic logging of strategy and component data
- Hook-based extension mechanism
- State persistence infrastructure
- ``market_adapter`` / ``frequency_context`` / ``session_context_provider``
  properties for paradigm-aware code

Hook lifecycle:
1. add_hook() -> hook.on_init(strategy)
2. on_start() -> hook.on_start(strategy)
3. on_bar() -> hook.on_bar_start(strategy), hook.on_bar_end(strategy)
4. on_stop() -> hook.on_stop(strategy)
"""

import dataclasses
from pathlib import Path
from typing import Dict, Any, Optional, List, Union, TYPE_CHECKING
from datetime import datetime
import logging

from .interfaces import (
    ITradingEngine, IStrategyCallbacks, OrderResult, Position, Trade,
    OrderStatus, OrderIntent, IMarketData, IPortfolio, IOrderManager,
    ILogger, IEventBus, IStrategyLogger
)
from .hooks.strategy_hook_base import IStrategyHook
from echolon.backtest.logging_utils import get_run_context, should_log_details

if TYPE_CHECKING:
    from echolon.markets.interface import IMarketAdapter
    from .frequency.interface import IFrequencyContext
    from .frequency.session_interface import ISessionContext, SessionContext

logger = logging.getLogger(__name__)


class BaseStrategy(IStrategyCallbacks):
    """Platform-agnostic base strategy class.

    Provides common functionality for all strategies while remaining
    independent of any specific trading platform. Strategies inherit
    from this class and use the provided interfaces to interact with
    market data, portfolio, and order management.

    Properties:
    - ``market_adapter``: market-specific rules (SHFE, crypto, etc.)
    - ``frequency_context``: time scaling for different bar sizes
    - ``session_context_provider``: intraday session helpers
    """

    def __init__(self, trading_engine: ITradingEngine, **params):
        """
        Initialize the base strategy.

        Parameters
        ----------
        trading_engine : ITradingEngine
            The trading engine providing access to market data, portfolio, etc.
        **params : dict
            Strategy parameters
        """
        # Store trading engine and interfaces.
        self.trading_engine = trading_engine
        self.market_data = trading_engine.get_market_data()
        self.portfolio = trading_engine.get_portfolio()
        self.order_manager = trading_engine.get_order_manager()
        self.logger = trading_engine.get_logger()
        self.event_bus = trading_engine.get_event_bus()
        self.strategy_logger = trading_engine.get_strategy_logger()

        # Store parameters
        self.params = params

        # Get run context for logging control
        self.run_context = params.get('run_context', 'optimization')

        # Configure logging based on context
        self._configure_strategy_logging(self.run_context)

        # Strategy state
        self.is_started = False
        self.is_stopped = False
        self.bar_count = 0

        # Trade tracking
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.total_pnl = 0.0

        # Hook infrastructure (market/frequency-specific features added via hooks)
        self._hooks: List[IStrategyHook] = []

        # Component management
        self.components = {}

        # Performance tracking (additional to base tracking)
        self.total_trades = 0
        self.winning_trades = 0
        self.losing_trades = 0

        # Auto-extract and store component parameters
        self._extract_component_parameters(params)

        # Current trade information
        self.entry_price: Optional[float] = None
        self.entry_time: Optional[datetime] = None
        self.position_type: Optional[str] = None  # 'long' or 'short'

        # Component references
        self.entry_signal = None
        self.exit_rule = None
        self.position_sizer = None
        self.risk_manager = None

        # Strategy directory for StrategyLoader-based component resolution.
        self.strategy_dir: Optional[str] = params.get('strategy_dir')
        # Multi-slot context (only set by PortfolioTradingRunner). slot_id
        # defaults to strategy_dir's basename so logging stays distinct.
        self.slot_id: Optional[str] = (
            Path(self.strategy_dir).name if self.strategy_dir else params.get('slot_id')
        )
        self.strategy_id: Optional[str] = params.get('strategy_id')
        self.indicator_columns: Optional[List[str]] = params.get('indicator_columns')

        # Setup event handlers
        self._setup_event_handlers()

        self.log("Strategy initialized", "info")

    @property
    def market_adapter(self) -> Optional['IMarketAdapter']:
        """Market-specific adapter (SHFE, crypto, etc.). May be None."""
        if hasattr(self.trading_engine, 'get_market_adapter'):
            return self.trading_engine.get_market_adapter()
        return None

    @property
    def frequency_context(self) -> Optional['IFrequencyContext']:
        """Frequency context for time scaling. May be None."""
        if hasattr(self.trading_engine, 'get_frequency_context'):
            return self.trading_engine.get_frequency_context()
        return None

    @property
    def session_context_provider(self) -> Optional['ISessionContext']:
        """Intraday session context (phase, bar position, VWAP, etc.).

        Returns None for daily-only strategies that don't need session context.
        """
        if hasattr(self.trading_engine, 'get_session_context_provider'):
            return self.trading_engine.get_session_context_provider()
        return None

    @property
    def symbol(self) -> str:
        """Get current trading symbol."""
        if hasattr(self.trading_engine, 'get_current_symbol'):
            return self.trading_engine.get_current_symbol()
        return ""

    # ========================================================================
    # Hook Infrastructure
    # ========================================================================

    def add_hook(self, hook: IStrategyHook) -> None:
        """
        Add strategy hook for market/frequency-specific features.

        Hooks allow market-specific (SHFE, Crypto) and frequency-specific
        (intraday, interday) features to be added without modifying
        core strategy code.

        Args:
            hook: IStrategyHook implementation

        Example:
            strategy.add_hook(SessionAwareStrategyHook())
            strategy.add_hook(ForcedExitStrategyHook(market_adapter))
        """
        self._hooks.append(hook)
        hook.on_init(self)
        self.log(f"Hook added: {hook.name}", "debug")

    def _configure_strategy_logging(self, run_context: str):
        """Configure strategy logging based on execution context."""
        if run_context == "optimization":
            # Minimize logging during optimization
            self._log_enabled = False
        else:
            # Enable detailed logging for debug/best_trial
            self._log_enabled = True

    def _setup_event_handlers(self):
        """Setup event handlers for order and trade updates."""
        self.event_bus.on_order_filled(self._on_order_filled)
        self.event_bus.on_trade_closed(self._on_trade_closed)

    def _on_order_filled(self, order_data: Dict[str, Any]):
        """Handle order filled events."""
        # Log order event to strategy logger
        if self.strategy_logger:
            self.strategy_logger.log_order_event(order_data)

    def _on_trade_closed(self, trade: Trade):
        """Handle trade closed events."""
        self.trade_count += 1
        self.total_pnl += trade.pnl

        if trade.pnl > 0:
            self.win_count += 1
            result = "WIN"
        else:
            self.loss_count += 1
            result = "LOSS"

        # Log trade event to strategy logger
        if self.strategy_logger:
            trade_data = {
                'trade_id': trade.trade_id,
                'side': trade.side.value,
                'size': trade.size,
                'entry_price': trade.entry_price,
                'exit_price': trade.exit_price,
                'pnl': trade.pnl,
                'commission': trade.commission,
                'result': result
            }
            self.strategy_logger.log_trade_event(trade_data)

        # Reset entry tracking
        self.entry_price = None
        self.entry_time = None
        self.position_type = None

        # Call strategy's trade notification
        self.on_trade_closed(trade)

    def log(self, message: str, level: str = "info"):
        """
        Log a message with the specified level.

        Parameters
        ----------
        message : str
            Message to log
        level : str
            Log level ('debug', 'info', 'warning', 'error')
        """
        # Skip logging if disabled (during optimization) unless it's error/warning
        if not self._log_enabled and level not in ['error', 'warning']:
            return

        # Add strategy context to message
        formatted_message = f"[{self.__class__.__name__}] {message}"

        if level == "debug":
            self.logger.debug(formatted_message)
        elif level == "warning":
            self.logger.warning(formatted_message)
        elif level == "error":
            self.logger.error(formatted_message)
        else:
            self.logger.info(formatted_message)

    def log_decision(
        self,
        component: str,
        decision: str,
        reason: str = "",
        **details
    ) -> None:
        """
        Log a component decision with structured format for debugger_agent.

        Format: [CONTEXT] Component | DECISION | reason | key1=value1, key2=value2

        Only logs in debug/best_trial contexts, not during optimization.

        Args:
            component: Component name (Entry, Exit, Risk, Sizer)
            decision: Decision made (e.g., "SIGNAL_LONG", "EXIT_TRIGGERED", "TRADING_BLOCKED")
            reason: Human-readable reason for the decision
            **details: Additional diagnostic details as key=value pairs
        """
        run_context = get_run_context()

        # Only log decisions in debug/best_trial mode
        if not should_log_details(run_context):
            return

        details_str = ", ".join(f"{k}={v}" for k, v in details.items())
        msg = f"[{run_context.upper()}] {component} | {decision}"
        if reason:
            msg += f" | {reason}"
        if details_str:
            msg += f" | {details_str}"

        self.logger.info(msg)

    def log_bar_summary(
        self,
        action_taken: str = "NONE",
        **context
    ) -> None:
        """
        Log bar summary with decision context.

        Format: [CONTEXT] Bar N | ACTION | price=X, position=Y, ...

        Args:
            action_taken: What happened this bar (ENTRY_LONG, EXIT, HOLD, etc.)
            **context: Bar context (price, position, signals, etc.)
        """
        run_context = get_run_context()

        # Only log bar summaries in debug/best_trial mode
        if not should_log_details(run_context):
            return

        context_str = ", ".join(f"{k}={v}" for k, v in context.items())
        msg = f"[{run_context.upper()}] Bar {self.bar_count} | {action_taken}"
        if context_str:
            msg += f" | {context_str}"

        self.logger.info(msg)

    def _collect_portfolio_state(self) -> Dict[str, Any]:
        """Collect current portfolio state for logging."""
        position = self.get_position()

        return {
            'total_value': self.portfolio.get_total_value(),
            'cash': self.portfolio.get_cash(),
            'position_size': position.size if position else 0.0,
            'position_value': position.market_value if position else 0.0,
            'unrealized_pnl': position.unrealized_pnl if position else 0.0,
            'realized_pnl': self.portfolio.get_realized_pnl()
        }

    def _collect_strategy_state(self) -> Dict[str, Any]:
        """Collect current strategy state for logging."""
        return {
            'datetime': self.market_data.get_current_datetime(),
            'bar_count': self.bar_count,
            'trade_count': self.trade_count,
            'win_count': self.win_count,
            'loss_count': self.loss_count,
            'total_pnl': self.total_pnl,
            'has_position': self.has_position(),
            'is_long': self.is_long_position(),
            'entry_price': self.entry_price,
            'position_type': self.position_type
        }

    def _log_component_output(self, component_name: str, output: Union[Dict[str, Any], Any]):
        """
        Log component output to strategy logger.

        Accepts both BaseModel instances and plain dicts. The strategy logger
        converts BaseModel to dict automatically for CSV output.
        """
        if self.strategy_logger and output:
            # Handle BaseModel if pydantic is available
            if hasattr(output, 'model_dump'):
                output = output.model_dump()
            self.strategy_logger.log_component_output(component_name, output)

    def _log_effective_params(self) -> None:
        """Write the EFFECTIVE component parameters into the current bar's log row.

        Audit hook for the trial->deployed parameter mapping: values are read
        from the live component instances (the dicts the components actually
        consult via ``self.params[...]``), NOT from selected_robust_trial.json
        or DEFAULT_PARAMS — so a mapping defect (optimized value orphaned,
        default delivered) shows up directly in the strategy log CSV as a
        ``param_{component}_{key}`` column differing from the trial's optimized
        value. Keys are logged verbatim as the component reads them. Scalar
        values only; the CSV logger preserves these as dynamic columns.
        """
        try:
            slogger = self.strategy_logger
            if not slogger or not getattr(slogger, "enabled", False):
                return
            bar = getattr(slogger, "current_bar_data", None)
            if not isinstance(bar, dict) or not bar:
                return  # bar scope not open yet (log_strategy_state opens it)
            for comp_name, comp in (
                ("entry", self.entry_rule),
                ("exit", self.exit_rule),
                ("risk", self.risk_manager),
                ("sizer", self.position_sizer),
            ):
                params = getattr(comp, "params", None)
                if dataclasses.is_dataclass(params) and not isinstance(params, type):
                    params = dataclasses.asdict(params)
                if not isinstance(params, dict):
                    continue
                for key, value in params.items():
                    if isinstance(value, (bool, int, float, str)):
                        bar[f"param_{comp_name}_{key}"] = value
        except Exception:
            pass  # Non-critical logging must never break trading

    # ========================================================================
    # Portfolio and Position Helpers
    # ========================================================================

    def get_portfolio_value(self) -> float:
        """Get current portfolio value."""
        return self.portfolio.get_total_value()

    def get_cash(self) -> float:
        """Get current cash amount."""
        return self.portfolio.get_cash()

    def get_position(self) -> Optional[Position]:
        """Get the current position (since only one position is allowed)."""
        return self.portfolio.get_position()

    def get_position_size(self) -> float:
        """Get current position size."""
        position = self.get_position()
        return position.size if position else 0.0

    def is_long_position(self) -> bool:
        """Check if current position is long."""
        position = self.get_position()
        if position is None:
            return False
        return position.direction == 'LONG'

    def is_short_position(self) -> bool:
        """Check if current position is short."""
        position = self.get_position()
        if position is None:
            return False
        return position.direction == 'SHORT'

    def has_position(self) -> bool:
        """Check if there is an open position."""
        return self.get_position_size() != 0

    def has_pending_orders(self) -> bool:
        """
        Check if there are pending orders awaiting execution.

        CRITICAL for intraday strategies: Backtrader market orders execute at
        NEXT bar's open, not immediately. Without this check, consecutive bars
        with entry signals will submit multiple orders before the first fills,
        resulting in massive unintended positions.

        Example without guard (15-min bars):
        - Bar 1 (09:30): Entry signal → order submitted (pending)
        - Bar 2 (09:45): has_position()=False → ANOTHER order submitted
        - Bar 3 (10:00): has_position()=False → ANOTHER order submitted
        - All orders fill → 3x intended position size

        Returns
        -------
        bool
            True if there are pending/submitted orders
        """
        pending = self.order_manager.get_pending_orders()
        return len(pending) > 0

    def get_unrealized_pnl(self) -> float:
        """Get unrealized PnL of current position."""
        position = self.get_position()
        return position.unrealized_pnl if position else 0.0

    # ========================================================================
    # Order Management Helpers
    # ========================================================================

    def entry(self, intent: OrderIntent, size: float, price: float = None) -> OrderResult:
        """
        Submit an order to enter a new position.

        Parameters
        ----------
        intent : OrderIntent
            ENTRY_LONG or ENTRY_SHORT
        size : float
            Order size
        price : float, optional
            Limit price (if None, market order)

        Returns
        -------
        OrderResult
            Order submission result

        Note
        ----
        The size is automatically capped to the maximum position allowed by
        available margin. A warning is logged if the requested size exceeds
        this limit.
        """
        if intent not in (OrderIntent.ENTRY_LONG, OrderIntent.ENTRY_SHORT):
            raise ValueError(
                f"entry() called with non-entry intent: {intent}. "
                f"Use exit() for EXIT_LONG/EXIT_SHORT."
            )

        # Get current price for margin calculation
        current_price = price if price is not None else self.get_current_price()

        # Cap size to maximum allowed by margin
        max_size = self.get_max_position_by_margin(current_price)
        original_size = size

        if size > max_size:
            self.log(
                f"POSITION SIZE CAPPED: Requested {size} contracts exceeds margin limit. "
                f"Capped to {max_size} contracts (max by margin at price {current_price:.2f})",
                "warning"
            )
            size = max_size

        if size <= 0:
            self.log(
                f"ENTRY BLOCKED: Insufficient margin for any position. "
                f"Requested={original_size}, MaxByMargin={max_size}, Price={current_price:.2f}",
                "error"
            )
            return OrderResult(
                status=OrderStatus.REJECTED,
                order_id=None,
                message="Insufficient margin"
            )

        # IOrderManager.submit_entry_order takes a direction string.
        direction = "LONG" if intent == OrderIntent.ENTRY_LONG else "SHORT"
        result = self.order_manager.submit_entry_order(direction, size)

        # Log order submission
        if self.strategy_logger:
            order_data = {
                'action': 'submit',
                'intent': 'entry',
                'direction': intent.value,
                'size': size,
                'price': price,
                'order_id': result.order_id,
                'status': result.status.value
            }
            self.strategy_logger.log_order_event(order_data)

        return result

    def exit(self, intent: OrderIntent = None, size: float = None, price: float = None) -> OrderResult:
        """
        Submit an order to exit/reduce current position.

        Parameters
        ----------
        intent : OrderIntent
            EXIT_LONG or EXIT_SHORT
        size : float, optional
            Size to exit (if None, exit entire position)
        price : float, optional
            Limit price (if None, market order)

        Returns
        -------
        OrderResult
            Order submission result
        """
        exit_intents = (
            OrderIntent.EXIT_LONG, OrderIntent.EXIT_SHORT,
            OrderIntent.FORCED_EXIT, OrderIntent.ROLLOVER_CLOSE,
        )
        if intent is not None and intent not in exit_intents:
            raise ValueError(
                f"exit() called with non-exit intent: {intent}. "
                f"Use entry() for ENTRY_LONG/ENTRY_SHORT."
            )

        # Get position size if not specified
        if size is None:
            position = self.get_position()
            size = abs(position.size) if position else 0

        result = self.order_manager.submit_exit_order(size)

        # Log order submission
        if self.strategy_logger:
            order_data = {
                'action': 'submit',
                'intent': 'exit',
                'size': size,
                'price': price,
                'order_id': result.order_id,
                'status': result.status.value
            }
            self.strategy_logger.log_order_event(order_data)

        return result

    # ========================================================================
    # Market Data Helpers
    # ========================================================================

    def get_current_price(self) -> float:
        """Get current price."""
        return self.market_data.get_current_price()

    def get_current_bar(self) -> Dict[str, float]:
        """Get current OHLCV bar."""
        return self.market_data.get_current_bar()

    def get_indicator(self, name: str, index: int = 0) -> float:
        """Get indicator value."""
        return self.market_data.get_indicator(name, index)

    def get_market_regime(self, index: int = 0, column: Optional[str] = None) -> str:
        """
        Get market regime as string (INTERDAY ONLY).

        Returns market_regime indicator converted to string:
        'trending_up', 'trending_down', 'ranging', 'volatile', 'unknown'

        Parameters
        ----------
        index : int
            Historical index (0=current, 1=previous bar, etc.)
        column : str, optional
            Read this feed column instead of the default ``'market_regime'``.
            Default ``None`` preserves prior behavior.

        Returns
        -------
        str
            Market regime string

        Raises
        ------
        RuntimeError
            If called in intraday context (use get_session_phase() instead)
        """
        from .hooks.session_aware_strategy_hook import SessionAwareStrategyHook

        # Check if intraday by looking for SessionAwareStrategyHook
        for hook in self._hooks:
            if isinstance(hook, SessionAwareStrategyHook):
                raise RuntimeError(
                    "get_market_regime() is not available for intraday trading. "
                    "Use get_session_phase() instead."
                )

        # Use the canonical numeric→string regime map from indicators.utils so
        # this method agrees with market_metrics, backtest_metrics, and the
        # market_regime calculator. The previous local map ({0: ranging,
        # Classifier label_map comes from the registered classifier — host
        # code must call register_regime_classifier(...) at session startup.
        # Strategies running without a registered classifier raise a clear
        # error rather than silently returning 'unknown'.
        from echolon.indicators.registry import get_regime_classifier
        classifier = get_regime_classifier('market_regime')
        read_column = column if column is not None else 'market_regime'
        numeric_regime = self.market_data.get_indicator(read_column, index)
        return classifier.label_map.get(int(numeric_regime), 'unknown')

    def get_session_phase(self, index: int = 0) -> str:
        """
        Get session phase as string (INTRADAY ONLY).

        Returns session_phase indicator converted to string:
        'night', 'morning', 'afternoon', 'morning_break', 'lunch_break', etc.

        Parameters
        ----------
        index : int
            Historical index (0=current, 1=previous bar, etc.)

        Returns
        -------
        str
            Session phase string

        Raises
        ------
        RuntimeError
            If called in interday context (use get_market_regime() instead)
        """
        from .hooks.session_aware_strategy_hook import SessionAwareStrategyHook

        # Check if intraday by looking for SessionAwareStrategyHook
        is_intraday = False
        for hook in self._hooks:
            if isinstance(hook, SessionAwareStrategyHook):
                is_intraday = True
                break

        if not is_intraday:
            raise RuntimeError(
                "get_session_phase() is only available for intraday trading. "
                "Use get_market_regime() instead."
            )

        numeric_phase = self.market_data.get_indicator('session_phase', index)
        # Use trading_context for market-agnostic phase decoding
        trading_context = self.trading_engine.get_trading_context()
        return trading_context.decode_phase(int(numeric_phase))

    def get_current_datetime(self) -> datetime:
        """Get current market datetime."""
        return self.market_data.get_current_datetime()

    # ========================================================================
    # Session Context Helpers (INJECTED BY SessionAwareStrategyHook)
    # ========================================================================
    # The following methods are available ONLY when SessionAwareStrategyHook
    # is added (intraday trading). Injected by SessionAwareStrategyHook.on_init().
    #
    # NOTE: get_session_phase() and get_market_regime() are BASE METHODS
    # defined above, NOT hook-injected. They include frequency validation.
    #
    # DAY-level helpers (use mandatory bar count indicators):
    #   - get_bar_of_day() -> int: Bar position in trading DAY (0-indexed)
    #   - get_bars_remaining() -> int: Bars until DAY end (holiday-aware)
    #   - get_total_bars_today() -> int: Total bars for the trading day
    #   - get_has_night_session() -> bool: Whether night session exists
    #
    # SESSION-level helpers (use mandatory bar count indicators):
    #   - get_session_context() -> SessionContext: Complete session context
    #   - get_bar_of_session() -> int: Bar position in SESSION (0-indexed)
    #   - get_bars_remaining_in_session() -> int: Bars until SESSION end
    #   - get_session_bars_total() -> int: Total bars for current session
    #   - get_session_index() -> int: Session index (0-based)
    #   - is_first_session() -> bool: First session check
    #   - is_last_session() -> bool: Last session check
    #   - is_session_break() -> bool: Break check
    #   - is_opening_phase() -> bool: Opening phase check
    #   - is_closing_phase() -> bool: Closing phase check
    #   - get_minutes_since_session_open() -> int: Minutes since session open
    #   - get_minutes_to_session_close() -> int: Minutes until session close
    #
    # Price-level helpers (use market_data, NOT mandatory indicators):
    #   - get_vwap() -> float: Session VWAP
    #   - get_opening_range() -> tuple: Opening range (high, low)
    # ========================================================================

    # ========================================================================
    # Component Management
    # ========================================================================

    def setup_components(self) -> bool:
        """
        Universal component setup infrastructure.
        Automatically detects component configurations from strategy parameters.

        Also adds component hooks based on trading mode:
        - SessionAwareComponentHook: For intraday trading (session context)

        Returns
        -------
        bool
            True if all components setup successfully
        """
        # Standard component mapping
        component_mapping = {
            'entry_rule': 'entry_params',
            'exit_rule': 'exit_params',
            'position_sizer': 'sizer_params',
            'risk_manager': 'risk_params'
        }

        component_instances = []

        # Auto-detect and setup components based on available parameters
        for component_name, params_key in component_mapping.items():
            if hasattr(self, params_key):
                component_params = getattr(self, params_key)

                # Import the component class dynamically
                component_class = self._get_component_class(component_name)
                if component_class:
                    component_instance = component_class(self.trading_engine, **component_params)
                    setattr(self, component_name, component_instance)
                    component_instances.append((component_name, component_instance))
                    self.log(f"Created {component_name} component")

        # Add component hooks based on trading mode
        self._add_component_hooks(component_instances)

        # Initialize all components (hooks are added before initialize)
        for name, component in component_instances:
            if component and hasattr(component, 'initialize'):
                success = component.initialize()
                if not success:
                    self.log(f"Failed to initialize {name} component", "error")
                    return False
                else:
                    self.log(f"{name} component initialized")

        self.log("All strategy components initialized successfully")
        return True

    def _add_component_hooks(self, component_instances: List[tuple]) -> None:
        """
        Add component hooks based on trading mode.

        Hook Composition:
            | Frequency | SessionAwareComponentHook |
            |-----------|---------------------------|
            | Intraday  | ✅                        |
            | Interday  | ❌                        |

        Args:
            component_instances: List of (name, component) tuples
        """
        from .frequency.interface import FrequencyType

        frequency_context = self.frequency_context
        if frequency_context is None:
            return

        is_intraday = frequency_context.frequency_type == FrequencyType.INTRADAY

        # SessionAwareComponentHook: For intraday trading
        if is_intraday:
            from .hooks.session_aware_component_hook import SessionAwareComponentHook

            for name, component in component_instances:
                if hasattr(component, 'add_hook'):
                    component.add_hook(SessionAwareComponentHook())
                    self.log(f"Added SessionAwareComponentHook to {name}", "debug")

    def _get_component_class(self, component_name: str):
        """Get component class by name using StrategyLoader."""
        from echolon.strategy.loader import StrategyLoader

        # Map component_name to file name
        file_name_map = {
            'entry_rule': 'entry',
            'exit_rule': 'exit',
            'position_sizer': 'sizer',
            'risk_manager': 'risk',
        }
        file_name = file_name_map.get(component_name, component_name)

        class_name_map = {
            'entry_rule': 'entry_rule',
            'exit_rule': 'exit_rule',
            'position_sizer': 'position_sizer',
            'risk_manager': 'risk_manager',
        }
        class_name = class_name_map.get(component_name, component_name)

        if self.strategy_dir:
            loader = StrategyLoader(Path(self.strategy_dir))
            try:
                return loader.load_class(file_name, class_name)
            except (FileNotFoundError, AttributeError):
                return None
        return None

    def _extract_component_parameters(self, params: Dict[str, Any]) -> None:
        """
        Auto-extract component parameters from main params dict.
        """
        component_param_keys = ['entry_params', 'exit_params', 'sizer_params', 'risk_params']

        for param_key in component_param_keys:
            if param_key in params:
                setattr(self, param_key, params[param_key])
                self.log(f"Extracted {param_key}")

    def validate_components(self) -> bool:
        """Validate that all required components are properly initialized."""
        required_components = ['entry_rule', 'exit_rule', 'position_sizer', 'risk_manager']
        for component_name in required_components:
            component = getattr(self, component_name, None)
            if component is None:
                self.log(f"Required component '{component_name}' not initialized", "error")
                return False
        return True

    # ========================================================================
    # Strategy Lifecycle (IStrategyCallbacks implementation)
    # ========================================================================

    def on_start(self) -> None:
        """
        Called when strategy starts - orchestrates component setup and hooks.

        TEMPLATE METHOD PATTERN: Do NOT override this method.
        Override _on_strategy_start() instead to add custom startup logic.

        This ensures components and hooks are always initialized:
        1. Component setup via setup_components()
        2. Component validation
        3. Hook on_start() calls
        4. _on_strategy_start() for custom logic
        """
        if self.is_started:
            return

        self.is_started = True
        self.log("Strategy started")
        self.log(f"Initial portfolio value: {self.get_portfolio_value():.2f}")

        # Setup components
        self.setup_components()

        # Validate components
        if not self.validate_components():
            raise RuntimeError("Strategy component validation failed")

        # Call hook lifecycle: on_start
        for hook in self._hooks:
            hook.on_start(self)

        self.log("All components initialized and validated")

        # Call subclass hook for custom startup logic
        self._on_strategy_start()

    def _on_strategy_start(self) -> None:
        """
        Override this method to add custom strategy startup logic.

        Called AFTER components and hooks are initialized.
        """
        pass  # Default: no custom startup logic

    def on_bar(self) -> None:
        """
        Called on each new bar - orchestrates hook lifecycle.

        TEMPLATE METHOD PATTERN: Do NOT override this method.
        Override _execute_bar() instead to implement strategy logic.

        This ensures hooks are always called in correct order:
        1. on_bar_start() for all hooks (can skip bar if returns False)
        2. _execute_bar() for strategy-specific logic
        3. on_bar_end() for all hooks (always called for cleanup)
        """
        self.bar_count += 1

        # Hook lifecycle: on_bar_start (hooks can return False to skip rest of bar)
        for hook in self._hooks:
            if not hook.on_bar_start(self):
                # Hook handled this bar (e.g., forced exit processed)
                # Call on_bar_end for cleanup and return
                for h in self._hooks:
                    h.on_bar_end(self)
                return

        # Systematic logging for each bar
        if self.strategy_logger:
            strategy_state = self._collect_strategy_state()
            self.strategy_logger.log_strategy_state(strategy_state)

            portfolio_state = self._collect_portfolio_state()
            self.strategy_logger.log_portfolio_state(portfolio_state)

            # Multi-slot enhanced logging (only if slot_id is set)
            if self.slot_id and hasattr(self.strategy_logger, 'log_market_data'):
                try:
                    bar = self.market_data.get_current_bar()
                    self.strategy_logger.log_market_data(bar)
                    self.strategy_logger.log_capital_state({
                        'equity': self.portfolio.get_total_value(),
                        'cash': self.portfolio.get_cash(),
                        'position_size': self.portfolio.get_position_size(),
                        'unrealized_pnl': self.portfolio.get_unrealized_pnl(),
                    })
                    if self.indicator_columns:
                        ind_vals = {}
                        for col in self.indicator_columns:
                            if self.market_data.has_indicator(col):
                                ind_vals[col] = self.market_data.get_indicator(col)
                        self.strategy_logger.log_indicator_values(ind_vals)
                except Exception:
                    pass  # Non-critical logging should not break trading

            # Effective-params audit: record what the components actually hold
            # this bar (never raises; see _log_effective_params).
            self._log_effective_params()

        # Execute strategy-specific logic (derived classes override this)
        self._execute_bar()

        # Hook lifecycle: on_bar_end (always called for cleanup)
        for hook in self._hooks:
            hook.on_bar_end(self)

    def _execute_bar(self) -> None:
        """
        Execute strategy-specific logic for current bar.

        Override this method in derived strategies to implement trading logic.
        DO NOT override on_bar() - it orchestrates the hook lifecycle.

        This method is called after:
        - bar_count is incremented
        - hook.on_bar_start() for all hooks (unless one returned False)
        - strategy/portfolio state logging

        And before:
        - hook.on_bar_end() for all hooks
        """
        pass  # Base implementation does nothing - derived strategies override

    def on_order_update(self, order_id: str, status: OrderStatus) -> None:
        """Called when order status changes. Override if needed."""
        pass

    def on_trade_closed(self, trade: Trade) -> None:
        """Called when a trade is closed. Override if needed."""
        pass

    def on_stop(self) -> None:
        """Called when strategy stops."""
        if self.is_stopped:
            return

        self.is_stopped = True
        final_value = self.get_portfolio_value()

        self.log("Strategy stopped")
        self.log(f"Final portfolio value: {final_value:.2f}")
        self.log(f"Total trades: {self.trade_count}")

        if self.trade_count > 0:
            win_rate = self.win_count / self.trade_count * 100

        # Hook lifecycle: on_stop
        for hook in self._hooks:
            hook.on_stop(self)

        # Finalize strategy logging
        if self.strategy_logger:
            log_file = self.strategy_logger.finalize_logging()
            if log_file:
                self.log(f"Strategy log saved to: {log_file}")

    # ========================================================================
    # Validation Helpers
    # ========================================================================

    def validate_order_size(self, size: float, price: float) -> bool:
        """
        Validate if an order size is acceptable given margin requirements.

        Uses contract multiplier and margin rate from market adapter.
        """
        if size == 0:
            return False

        available_cash = self.get_cash()

        # Get margin requirement using market adapter if available
        margin_required = self._calculate_margin_required(abs(size), price)

        if margin_required > available_cash:
            self.log(
                f"Insufficient margin for order: Required={margin_required:.2f}, "
                f"Available={available_cash:.2f}, Size={size}",
                "warning"
            )
            return False

        return True

    def get_max_position_by_margin(self, price: float = None) -> int:
        """
        Calculate maximum position size based on available margin.

        Uses contract multiplier and margin rate from market adapter.

        Parameters
        ----------
        price : float, optional
            Price for calculation (uses current price if not specified)

        Returns
        -------
        int
            Maximum whole contracts that can be opened with available margin
        """
        if price is None:
            price = self.get_current_price()

        available_cash = self.get_cash()
        adapter = self.market_adapter

        if adapter is None:
            # Fallback: assume 1:1 (no leverage)
            return int(available_cash / price) if price > 0 else 0

        try:
            symbol = self.symbol
            contract_spec = adapter.get_contract_spec(symbol)
            margin_per_contract = contract_spec.calculate_margin(price, 1.0)

            if margin_per_contract <= 0:
                return 0

            return int(available_cash / margin_per_contract)
        except (KeyError, AttributeError):
            # Fallback if contract spec not available
            return int(available_cash / price) if price > 0 else 0

    def _calculate_margin_required(self, size: float, price: float) -> float:
        """
        Calculate margin required for a position.

        Uses contract multiplier and margin rate from market adapter.

        Parameters
        ----------
        size : float
            Position size (contracts)
        price : float
            Entry price

        Returns
        -------
        float
            Margin required in account currency
        """
        adapter = self.market_adapter

        if adapter is None:
            # Fallback: assume full value required (no leverage)
            return abs(size) * price

        try:
            symbol = self.symbol
            contract_spec = adapter.get_contract_spec(symbol)
            return contract_spec.calculate_margin(price, abs(size))
        except (KeyError, AttributeError):
            # Fallback if contract spec not available
            return abs(size) * price

    def calculate_risk_per_trade(self, entry_price: float, stop_price: float,
                                position_size: float) -> float:
        """
        Calculate risk per trade as percentage of portfolio.

        Uses contract multiplier from market adapter for accurate risk calculation.
        """
        adapter = self.market_adapter
        multiplier = 1.0

        if adapter is not None:
            try:
                symbol = self.symbol
                contract_spec = adapter.get_contract_spec(symbol)
                multiplier = contract_spec.multiplier
            except (KeyError, AttributeError):
                pass

        risk_per_contract = abs(entry_price - stop_price) * multiplier
        total_risk = risk_per_contract * abs(position_size)
        portfolio_value = self.get_portfolio_value()

        return total_risk / portfolio_value if portfolio_value > 0 else 0.0

    # ========================================================================
    # Infrastructure Utilities for Strategy Coordination
    # ========================================================================

    def execute_entry_order(self, instruction: Dict[str, Any]) -> OrderResult:
        """Execute entry order based on instruction."""
        direction = instruction['direction']
        size = instruction['size']
        price = instruction.get('price', None)

        if direction == 'LONG':
            intent = OrderIntent.ENTRY_LONG
        elif direction == 'SHORT':
            intent = OrderIntent.ENTRY_SHORT
        else:
            raise ValueError(f"Invalid entry direction: {direction}")

        return self.entry(intent, size, price)

    def execute_exit_order(self, instruction: Dict[str, Any]) -> OrderResult:
        """Execute exit order based on instruction."""
        position = self.get_position()
        if not position:
            self.log("No position to exit", "warning")
            return None

        size = instruction.get('size', abs(position.size))
        price = instruction.get('price', None)

        if position.direction == 'LONG':
            intent = OrderIntent.EXIT_LONG
        else:
            intent = OrderIntent.EXIT_SHORT

        return self.exit(intent, size, price)

    def register_component(self, name: str, component) -> None:
        """Register a strategy component."""
        setattr(self, name, component)
        self.log(f"Registered component: {name}")

    def log_all_component_outputs(self, component_names: List[str]) -> None:
        """Log outputs from specified components."""
        for name in component_names:
            component = getattr(self, name, None)
            if component and hasattr(component, 'get_last_output'):
                output = component.get_last_output()
                if output:
                    self._log_component_output(name, output)

    def validate_order_instruction(self, instruction: Dict[str, Any], order_type: str) -> bool:
        """Validate order instruction format."""
        required_fields = {
            'entry': ['direction', 'size'],
            'exit': ['size']
        }

        required = required_fields.get(order_type, [])
        for field in required:
            if field not in instruction:
                self.log(f"Missing required field '{field}' in {order_type} instruction", "error")
                return False

        size = instruction.get('size', 0)
        if size <= 0:
            self.log(f"Invalid size {size} in {order_type} instruction", "error")
            return False

        return True

    def get_component_status(self, component_names: List[str]) -> Dict[str, Any]:
        """Get status of specified components."""
        status = {}
        for name in component_names:
            component = getattr(self, name, None)
            if component:
                if hasattr(component, 'get_status'):
                    status[name] = component.get_status()
                elif hasattr(component, 'is_initialized'):
                    status[name] = {'initialized': component.is_initialized}
                else:
                    status[name] = {'exists': True}
            else:
                status[name] = {'exists': False}
        return status

    # ========================================================================
    # Forced Exit Infrastructure (INJECTED BY ForcedExitStrategyHook)
    # ========================================================================
    # The following methods are available ONLY when ForcedExitStrategyHook
    # is added (interday futures trading):
    #
    # - check_and_process_forced_exits() -> bool
    # - signal_forced_exit(reason, contract_code, position_size, observer_date)
    # - check_contract_expiry() -> bool
    # - _has_forced_exit_signal() -> bool
    #
    # These are injected by ForcedExitStrategyHook.on_init() for interday futures.
    # The hook also automatically processes forced exits in on_bar_start().
    # ========================================================================

    # ========================================================================
    # Strategy State Persistence Infrastructure (Universal)
    # ========================================================================

    def save_state(self, state_path: str) -> None:
        """Save strategy + component state to disk."""
        from .state_manager import StateManager

        sm = StateManager(state_path=state_path)
        sm.load_state()
        sm.update_last_processed(datetime.now())
        sm.set_custom('strategy', {
            'bar_count': self.bar_count,
            'total_trades': self.total_trades,
            'winning_trades': self.winning_trades,
            'losing_trades': self.losing_trades,
        })
        sm.set_custom('components', self._collect_component_states())
        sm.save_state()

    def restore_state(self, state_path: str) -> None:
        """Restore strategy + component state from disk."""
        from .state_manager import StateManager

        sm = StateManager(state_path=state_path)
        state = sm.load_state()

        if not state.last_processed_datetime:
            self.log("No previous state found -- starting fresh")
            return

        self.log(
            f"State restored: last_processed={state.last_processed_datetime}, "
            f"position_side={state.position_side}, "
            f"position_size={state.position_size}"
        )

        strategy_data = state.custom.get('strategy', {})
        self.bar_count = strategy_data.get('bar_count', 0)
        self.total_trades = strategy_data.get('total_trades', 0)
        self.winning_trades = strategy_data.get('winning_trades', 0)
        self.losing_trades = strategy_data.get('losing_trades', 0)

        component_states = state.custom.get('components', {})
        if component_states:
            self._restore_component_states(component_states)

        self.log("Strategy and component states restored")

    def _collect_component_states(self) -> Dict[str, Any]:
        """Collect state from all components."""
        component_states = {}
        component_names = ['exit_rule', 'risk_manager', 'position_sizer', 'entry_rule']

        for comp_name in component_names:
            component = getattr(self, comp_name, None)
            if component and hasattr(component, 'get_state'):
                component_states[comp_name] = component.get_state()

        return component_states

    def _restore_component_states(self, component_states: Dict[str, Any]) -> None:
        """Restore state to all components."""
        component_names = ['exit_rule', 'risk_manager', 'position_sizer', 'entry_rule']

        for comp_name in component_names:
            component = getattr(self, comp_name, None)
            if component and hasattr(component, 'restore_state'):
                comp_state = component_states.get(comp_name, {})
                component.restore_state(comp_state)
                self.log(f"Restored {comp_name} state")
