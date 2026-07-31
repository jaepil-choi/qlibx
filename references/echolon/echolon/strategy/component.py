"""
Base Component
==============

Abstract base class for strategy components (entry, exit, risk, sizer).

Architecture:
    BaseComponent provides UNIVERSAL functionality only.
    Market/frequency-specific features are added via HOOKS.

    Hooks (added based on trading mode):
    - SessionAwareComponentHook: For intraday (session context helpers)

Responsibilities:
- Store reference to trading engine
- Provide access to market_data, portfolio, frequency_context
- Handle parameter storage and access
- Provide common utility methods for components
- Hook-based extension mechanism

Subclasses include:
- entry_rule: Entry signal generation
- exit_rule: Exit signal and trailing stop management
- risk_manager: Risk checks and circuit breakers
- position_sizer: Position size calculation

Each component receives frequency_context for bar/day conversions.

Example:
    class entry_rule(BaseComponent):
        def __init__(self, trading_engine, frequency_context, **params):
            super().__init__(trading_engine, frequency_context, **params)
            # Use context.days_to_bars() for frequency-aware period conversion
            self.lookback_bars = self.context.days_to_bars(5)  # 5 days in bars

        def generate_signal(self):
            ...
"""

from abc import ABC
from typing import Dict, Any, List, Optional, TYPE_CHECKING
import logging

from .interfaces import (
    ITradingEngine,
    IMarketData,
    IPortfolio,
    ILogger,
)
from echolon.errors import raise_error
from echolon.strategy.schemas import EntrySignalOutput, ExitSignalOutput, RiskOutput, SizerOutput, validate_position_size
from .hooks.component_hook_base import IComponentHook
from echolon.backtest.logging_utils import get_run_context, should_log_details
# decode_session_phase is now accessed via trading_context.decode_phase()

from echolon.config.markets.core.context import TradingContext

if TYPE_CHECKING:
    from .frequency.interface import IFrequencyContext
    from echolon.markets.interface import IMarketAdapter
    from .frequency.session_interface import ISessionContext, SessionContext

module_logger = logging.getLogger(__name__)


class BaseComponent(ABC):
    """
    Abstract base class for strategy components.

    Components are specialized pieces of strategy logic:
    - Entry: Generate entry signals
    - Exit: Manage exits and trailing stops
    - Risk: Risk management and circuit breakers
    - Sizer: Position sizing calculations

    All components share:
    - Access to trading engine interfaces
    - Frequency context for parameter scaling
    - Parameter storage and access
    """

    # ------ Declarative class attributes ------
    # Subclasses may override:
    # - Params: a ``@dataclass`` type defining this component's parameters; if
    #   set, dict/missing ``params`` are auto-promoted to this dataclass.
    # - hooks: declarative list of hook names for the engine to auto-install.
    # - indicators: declarative list of indicator names (per indicator_list schema).
    Params = None
    hooks: tuple[str, ...] = ()
    indicators: tuple[str, ...] = ()

    def __init__(
        self,
        trading_engine: ITradingEngine | None = None,
        frequency_context: 'IFrequencyContext' = None,
        market_adapter: 'IMarketAdapter' = None,
        *,
        params=None,
        **kwargs,
    ):
        """
        Initialize base component.

        Args:
            trading_engine: Trading engine providing all interfaces (optional for
                declarative-surface-only construction in unit tests).
            frequency_context: Frequency context for scaling (optional, uses engine's)
            market_adapter: Market adapter (optional, uses engine's)
            params: Optional Params dataclass instance / dict for the typed
                params surface. If None and ``self.Params`` is set, a default
                ``self.Params()`` instance is constructed.
            **kwargs: Component parameters in dict form (collected into
                ``self._params`` and accessible via ``params.get(...)``).
        """
        # Params/dict promotion:
        # - params=None + self.Params set → construct default self.Params()
        # - dict + self.Params set → promote dict to self.Params(**dict)
        # - instance + self.Params set → store as-is
        # - None or dict or instance + self.Params unset → store as-is (kwargs-dict path)
        #
        # ``self._typed_params`` carries whichever shape was provided; the
        # ``params`` property below returns it when set, otherwise falls back
        # to the kwargs-dict in ``self._params``.
        if params is None and self.Params is not None:
            self._typed_params = self.Params()
        elif self.Params is not None and isinstance(params, dict):
            self._typed_params = self.Params(**params)
        else:
            self._typed_params = params

        # kwargs-dict surface: components like entry/exit/risk/sizer pass
        # ``printlog=...`` etc. as kwargs; collect them so ``self.params.get(...)``
        # works.
        self._params = kwargs

        # Engine wiring — only if an engine was provided (skipped for unit tests
        # that exercise only the Params/hooks/indicators surface).
        self._engine = trading_engine
        if trading_engine is not None:
            # Get contexts from engine if not provided
            self._context = frequency_context or trading_engine.get_frequency_context()
            self._market_adapter = market_adapter or trading_engine.get_market_adapter()
            self._trading_context: TradingContext = trading_engine.get_trading_context()

            # Cache interface references
            self._market_data = trading_engine.get_market_data()
            self._portfolio = trading_engine.get_portfolio()
            self._logger = trading_engine.get_logger()
            self._strategy_logger = trading_engine.get_strategy_logger()

            # Get run context for logging control
            self.run_context = kwargs.get('run_context', 'optimization')

            # Configure logging based on context
            self._configure_component_logging(self.run_context)

            # Component state
            self.is_initialized = False

            # Hook infrastructure (market/frequency-specific features added via hooks)
            self._hooks: List[IComponentHook] = []

            self.log(f"{self.__class__.__name__} component initialized")
        else:
            # Lightweight construction path — declarative surface only.
            self._context = None
            self._market_adapter = None
            self._trading_context = None
            self._market_data = None
            self._portfolio = None
            self._logger = None
            self._strategy_logger = None
            self.run_context = kwargs.get('run_context', 'optimization')
            self.is_initialized = False
            self._hooks: List[IComponentHook] = []
            # Logging: no engine → logging is disabled. Setting _log_enabled=False
            # avoids AttributeError if a hook or subclass calls self.log() on an
            # engineless instance.
            self._log_enabled = False

    def get_indicators(self) -> tuple:
        """Return the declarative ``indicators`` class attribute.

        Subclasses that declare ``indicators = ("rsi_14", "atr_20")`` can call
        ``self.get_indicators()`` to surface them into strategy_indicator_list.json
        construction.
        """
        return self.indicators

    # =========================================================================
    # Properties
    # =========================================================================

    @property
    def engine(self) -> ITradingEngine:
        """Get trading engine."""
        return self._engine

    @property
    def market_data(self) -> IMarketData:
        """Get market data interface."""
        return self._market_data

    @property
    def portfolio(self) -> IPortfolio:
        """Get portfolio interface."""
        return self._portfolio

    @property
    def logger(self) -> ILogger:
        """Get logger interface."""
        return self._logger

    @property
    def context(self) -> 'IFrequencyContext':
        """Get frequency context."""
        return self._context

    @property
    def market_adapter(self) -> 'IMarketAdapter':
        """Get market adapter."""
        return self._market_adapter

    @property
    def session_context_provider(self) -> 'ISessionContext':
        """
        Get session context provider for intraday trading.

        Returns ISessionContext implementation or None if not available.
        """
        if hasattr(self._engine, 'get_session_context_provider'):
            return self._engine.get_session_context_provider()
        return None

    @property
    def params(self) -> Dict[str, Any]:
        """Get component parameters.

        Returns the typed ``Params`` instance when one was supplied or
        auto-constructed (via the ``Params`` class attribute); otherwise
        falls back to the kwargs-dict collected at ``__init__`` time.
        """
        typed = getattr(self, "_typed_params", None)
        if typed is not None:
            return typed
        return self._params

    @property
    def strategy_logger(self):
        """Get strategy logger interface."""
        return self._strategy_logger

    # =========================================================================
    # Hook Infrastructure
    # =========================================================================

    def add_hook(self, hook: IComponentHook) -> None:
        """
        Add component hook for market/frequency-specific features.

        Hooks allow market-specific (SHFE, Crypto) and frequency-specific
        (intraday) features to be added without modifying core component code.

        Args:
            hook: IComponentHook implementation

        Example:
            component.add_hook(SessionAwareComponentHook())
        """
        self._hooks.append(hook)
        hook.on_init(self)
        self.log(f"Hook added: {hook.name}", "debug")

    # =========================================================================
    # Logging Control
    # =========================================================================

    def _configure_component_logging(self, run_context: str):
        """Configure component logging based on execution context."""
        if run_context == "optimization":
            # Minimize logging during optimization
            self._log_enabled = False
        else:
            # Enable detailed logging for debug/best_trial
            self._log_enabled = True

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
        # Skip logging entirely when the component was constructed without a
        # trading engine (declarative-surface unit tests, hooks that fire early).
        if self._logger is None:
            return
        # Skip logging if disabled (during optimization) unless it's error/warning
        if not self._log_enabled and level not in ['error', 'warning']:
            return

        # Add component context to message
        formatted_message = f"[{self.__class__.__name__}] {message}"

        if level == "debug":
            self._logger.debug(formatted_message)
        elif level == "warning":
            self._logger.warning(formatted_message)
        elif level == "error":
            self._logger.error(formatted_message)
        else:
            self._logger.info(formatted_message)

    # =========================================================================
    # Component Interface Method Stubs (Override in derived components)
    # =========================================================================

    def generate_signal(self) -> 'EntrySignalOutput':
        """
        Entry component interface - Override in entry_rule component.

        Raises:
            StrategyStructureError (STR-003): If called on a subclass that
            has not implemented ``generate_signal``.
        """
        raise_error(
            "STR-003",
            file=type(self).__module__,
            class_name=type(self).__name__,
            missing_method="generate_signal",
        )

    def should_exit(self) -> 'ExitSignalOutput':
        """
        Exit component interface - Override in exit_rule component.

        Raises:
            StrategyStructureError (STR-003): If called on a subclass that
            has not implemented ``should_exit``.
        """
        raise_error(
            "STR-003",
            file=type(self).__module__,
            class_name=type(self).__name__,
            missing_method="should_exit",
        )

    def can_trade(self) -> 'RiskOutput':
        """
        Risk component interface - Override in risk_manager component.

        Raises:
            StrategyStructureError (STR-003): If called on a subclass that
            has not implemented ``can_trade``.
        """
        raise_error(
            "STR-003",
            file=type(self).__module__,
            class_name=type(self).__name__,
            missing_method="can_trade",
        )

    def calculate_size(self, signal_data: 'EntrySignalOutput') -> 'SizerOutput':
        """
        Sizer component interface - Override in position_sizer component.

        Parameters:
            signal_data: EntrySignalOutput BaseModel from entry component

        Raises:
            StrategyStructureError (STR-003): If called on a subclass that
            has not implemented ``calculate_size``.
        """
        raise_error(
            "STR-003",
            file=type(self).__module__,
            class_name=type(self).__name__,
            missing_method="calculate_size",
        )

    # =========================================================================
    # Component Output Logging
    # =========================================================================

    def log_entry_output(self, output_data: EntrySignalOutput) -> None:
        """
        Log entry component output to the strategy logger and terminal.

        Parameters
        ----------
        output_data : EntrySignalOutput
            Entry signal output data
        """
        if self._strategy_logger and output_data:
            self._strategy_logger.log_component_output('entry_rule', output_data)

        # Terminal decision logging for debugger_agent (debug/best_trial only)
        if output_data and should_log_details(get_run_context()):
            # ExitSignalOutput / EntrySignalOutput use `entry_reason` / `exit_reason`
            # (no plain `reason` field) — fall back through both for safety.
            reason_text = (
                getattr(output_data, 'entry_reason', None)
                or getattr(output_data, 'reason', None)
                or ""
            )
            self._log_terminal_decision(
                "Entry",
                output_data.signal,
                reason_text,
                intent=output_data.intent.value if hasattr(output_data, 'intent') and output_data.intent else "N/A"
            )

    def log_exit_output(self, output_data: ExitSignalOutput) -> None:
        """
        Log exit component output to the strategy logger and terminal.

        Parameters
        ----------
        output_data : ExitSignalOutput
            Exit signal output data
        """
        if self._strategy_logger and output_data:
            self._strategy_logger.log_component_output('exit_rule', output_data)

        # Terminal decision logging for debugger_agent (debug/best_trial only)
        if output_data and should_log_details(get_run_context()):
            decision = "EXIT_TRIGGERED" if output_data.should_exit else "HOLD_POSITION"
            # ExitSignalOutput uses `exit_reason` (no plain `reason`).  Fall
            # back through both so older outputs still log correctly.
            reason_text = (
                getattr(output_data, 'exit_reason', None)
                or getattr(output_data, 'reason', None)
                or ""
            )
            self._log_terminal_decision(
                "Exit",
                decision,
                reason_text,
                bars_held=output_data.bars_since_entry if hasattr(output_data, 'bars_since_entry') else 0
            )

    def log_risk_output(self, output_data: RiskOutput) -> None:
        """
        Log risk manager component output to the strategy logger and terminal.

        Parameters
        ----------
        output_data : RiskOutput
            Risk output data
        """
        if self._strategy_logger and output_data:
            self._strategy_logger.log_component_output('risk_manager', output_data)

        # Terminal decision logging for debugger_agent (debug/best_trial only)
        if output_data and should_log_details(get_run_context()):
            decision = "TRADING_ALLOWED" if output_data.trading_allowed else "TRADING_BLOCKED"
            self._log_terminal_decision(
                "Risk",
                decision,
                output_data.risk_reason,
                drawdown=f"{output_data.current_drawdown_pct:.2f}%" if hasattr(output_data, 'current_drawdown_pct') else "N/A"
            )

    def log_sizer_output(self, output_data: SizerOutput) -> None:
        """
        Log position sizer component output to the strategy logger and terminal.

        Parameters
        ----------
        output_data : SizerOutput
            Sizer output data
        """
        if self._strategy_logger and output_data:
            self._strategy_logger.log_component_output('position_sizer', output_data)

        # Terminal decision logging for debugger_agent (debug/best_trial only)
        if output_data and should_log_details(get_run_context()):
            self._log_terminal_decision(
                "Sizer",
                f"SIZE={output_data.calculated_size}",
                output_data.reason if hasattr(output_data, 'reason') else "",
                risk_amount=f"{output_data.risk_amount:.2f}" if hasattr(output_data, 'risk_amount') else "N/A"
            )

    def _log_terminal_decision(
        self,
        component: str,
        decision: str,
        reason: str = "",
        **details
    ) -> None:
        """
        Log component decision to terminal for debugger_agent visibility.

        Format: [CONTEXT] Component | DECISION | reason | key1=value1, key2=value2

        Args:
            component: Component name (Entry, Exit, Risk, Sizer)
            decision: Decision made
            reason: Human-readable reason
            **details: Additional diagnostic details
        """
        run_context = get_run_context()
        details_str = ", ".join(f"{k}={v}" for k, v in details.items())
        msg = f"[{run_context.upper()}] {component} | {decision}"
        if reason:
            msg += f" | {reason}"
        if details_str:
            msg += f" | {details_str}"

        module_logger.info(msg)

    # =========================================================================
    # Position Size Validation Helper (for Sizer Components)
    # =========================================================================

    def validate_and_convert_position_size(self, calculated_size: float) -> int:
        """
        Validate and convert position size to non-negative integer.

        CRITICAL: Position sizer components MUST call this method before returning
        position size to ensure:
        1. Logged size matches actual size used for orders
        2. Size is non-negative integer (whole contracts)
        3. Invalid sizes (NaN, negative, infinite) are caught at source

        Parameters
        ----------
        calculated_size : float
            Raw calculated position size (can be float)

        Returns
        -------
        int
            Validated non-negative integer position size

        Raises
        ------
        TypeError
            If size is not numeric
        ValueError
            If size is negative, NaN, or infinite
        """
        return validate_position_size(calculated_size, component_name=self.__class__.__name__)

    # =========================================================================
    # Parameter access
    # =========================================================================

    def get_param(self, key: str, default: Any = None) -> Any:
        """
        Get component parameter with optional default.

        Args:
            key: Parameter key
            default: Default value if not found

        Returns:
            Parameter value or default
        """
        return self._params.get(key, default)

    # =========================================================================
    # Market data utilities
    # =========================================================================

    def get_current_price(self) -> float:
        """Get current price."""
        return self.market_data.get_current_price()

    def get_current_bar(self) -> Dict[str, float]:
        """Get current OHLCV bar."""
        return self.market_data.get_current_bar()

    def get_bar_data(self, bars_back: int = 0) -> Dict[str, float]:
        """Get OHLCV data for specific bar."""
        return self.market_data.get_bar_data(bars_back)

    def get_indicator(self, name: str, index: int = 0) -> float:
        """
        Get indicator value.

        Args:
            name: Indicator name
            index: Bars back (0 = current, 1 = previous, etc.)

        Returns:
            Indicator value
        """
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
            Generic per-window-injectable seam (mirrors ``get_indicator``'s
            own ``name`` parameter): a host app that bakes multiple
            vintage-keyed regime columns onto one feed (e.g.
            ``market_regime__fit20150630``) can point a single component call
            at whichever one applies THIS window, without echolon knowing
            anything about vintages/rebinding — it just reads a different
            numeric column through the SAME registered classifier's
            label_map. Default ``None`` reproduces the exact prior behavior
            byte-for-byte (reads the classifier's own default column name).

        Returns
        -------
        str
            Market regime string

        Raises
        ------
        RuntimeError
            If called in intraday context (use get_session_phase() instead)
        """
        from .frequency.interface import FrequencyType

        if self._context and self._context.frequency_type == FrequencyType.INTRADAY:
            raise RuntimeError(
                "get_market_regime() is not available for intraday trading. "
                "Use get_session_phase() instead."
            )

        # Classifier label_map comes from the registered classifier — host
        # code must call register_regime_classifier(...) at session startup.
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
        from .frequency.interface import FrequencyType

        if not self._context or self._context.frequency_type != FrequencyType.INTRADAY:
            raise RuntimeError(
                "get_session_phase() is only available for intraday trading. "
                "Use get_market_regime() instead."
            )

        numeric_phase = self.market_data.get_indicator('session_phase', index)
        return self._trading_context.decode_phase(int(numeric_phase))

    def get_indicator_series(self, name: str, length: int) -> List[float]:
        """
        Get indicator series.

        Args:
            name: Indicator name
            length: Number of bars

        Returns:
            List of values [oldest, ..., newest]
        """
        return self.market_data.get_indicator_series(name, length)

    def get_close(self, ago: int = 0) -> float:
        """Get close price."""
        return self.market_data.get_close(ago)

    def get_high(self, ago: int = 0) -> float:
        """Get high price."""
        return self.market_data.get_high(ago)

    def get_low(self, ago: int = 0) -> float:
        """Get low price."""
        return self.market_data.get_low(ago)

    def get_open(self, ago: int = 0) -> float:
        """Get open price."""
        return self.market_data.get_open(ago)

    def get_volume(self, ago: int = 0) -> float:
        """Get volume."""
        return self.market_data.get_volume(ago)

    # =========================================================================
    # Session Context Helpers (INJECTED BY SessionAwareComponentHook)
    # =========================================================================
    # The following methods are available ONLY when SessionAwareComponentHook
    # is added (intraday trading). Injected by SessionAwareComponentHook.on_init().
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
    # =========================================================================

    # =========================================================================
    # Position utilities
    # =========================================================================

    def has_position(self) -> bool:
        """Check if there's an open position."""
        position = self.portfolio.get_position()
        return position is not None and position.size != 0

    def get_position_size(self) -> float:
        """Get position size for symbol."""
        position = self.portfolio.get_position()
        return position.size if position else 0.0

    def get_equity(self) -> float:
        """Get current equity."""
        return self.portfolio.get_equity()

    def get_portfolio_value(self) -> float:
        """Get current portfolio value."""
        return self.portfolio.get_total_value()

    def get_cash(self) -> float:
        """Get current cash amount."""
        return self.portfolio.get_cash()

    def is_long_position(self) -> bool:
        """Check if current position is long."""
        position = self.portfolio.get_position()
        return position is not None and position.direction == 'LONG'

    def is_short_position(self) -> bool:
        """Check if current position is short."""
        position = self.portfolio.get_position()
        return position is not None and position.direction == 'SHORT'

    def get_unrealized_pnl(self) -> float:
        """Get unrealized PnL of current position."""
        position = self.portfolio.get_position()
        return position.unrealized_pnl if position else 0.0


    # =========================================================================
    # Validation Helpers
    # =========================================================================

    def validate_params(self) -> bool:
        """
        Validate component parameters. Override in derived components.

        Returns
        -------
        bool
            True if parameters are valid
        """
        return True

    def initialize(self) -> bool:
        """
        Initialize the component. Override in derived components.

        Returns
        -------
        bool
            True if initialization successful
        """
        if self.is_initialized:
            return True

        # Validate parameters
        if not self.validate_params():
            self.log("Parameter validation failed", "error")
            return False

        # Call hook lifecycle: on_initialize
        for hook in self._hooks:
            hook.on_initialize(self)

        self.is_initialized = True
        self.log("Component initialized successfully")
        return True

    # =========================================================================
    # Common Utility Methods
    # =========================================================================

    def safe_get_param(self, param_name: str, default_value: Any = None) -> Any:
        """
        Safely get a parameter value with optional default.

        Parameters
        ----------
        param_name : str
            Parameter name to retrieve
        default_value : Any, optional
            Default value if parameter not found

        Returns
        -------
        Any
            Parameter value or default
        """
        return self._params[param_name] if param_name in self._params else default_value

    def requires_param(self, param_name: str) -> bool:
        """
        Check if a required parameter exists.

        Parameters
        ----------
        param_name : str
            Parameter name to check

        Returns
        -------
        bool
            True if parameter exists
        """
        if param_name not in self._params:
            self.log(f"Required parameter '{param_name}' not found", "error")
            return False
        return True

    def get_component_info(self) -> Dict[str, Any]:
        """
        Get component information for logging/debugging.

        Returns
        -------
        dict
            Component information
        """
        return {
            'component_type': self.__class__.__name__,
            'is_initialized': self.is_initialized,
            'params': self._params,
        }

    # =========================================================================
    # Component State Persistence Infrastructure (Universal for Live Trading)
    # =========================================================================

    def get_state(self) -> Dict[str, Any]:
        """
        Get current component state for persistence during live trading.

        This universal implementation handles common component state.
        Override in derived components to add component-specific state.

        Returns
        -------
        Dict[str, Any]
            Current component state that needs to be preserved
        """
        # Base component state that all components should preserve
        base_state = {
            'is_initialized': self.is_initialized,
            'run_context': self.run_context,
            'component_type': self.__class__.__name__
        }

        # Get component-specific state if implemented
        component_state = self._get_component_specific_state()

        # Merge base state with component-specific state
        return {**base_state, **component_state}

    def restore_state(self, state: Dict[str, Any]) -> None:
        """
        Restore component state from persistence during live trading.

        This universal implementation handles common component state.
        Override in derived components to add component-specific restoration.

        Parameters
        ----------
        state : Dict[str, Any]
            Previously saved state to restore
        """
        if not state:
            self.log("No state to restore - using defaults")
            return

        # Restore base component state
        self.is_initialized = state.get('is_initialized', False)

        # Validate component type matches
        saved_type = state.get('component_type')
        if saved_type and saved_type != self.__class__.__name__:
            self.log(f"State type mismatch: saved={saved_type}, current={self.__class__.__name__}", "warning")

        # Restore component-specific state if implemented
        self._restore_component_specific_state(state)

        self.log(f"Component state restored - initialized: {self.is_initialized}")

    def _get_component_specific_state(self) -> Dict[str, Any]:
        """
        Get component-specific state for persistence.
        Override in derived components to add specific state variables.

        Returns
        -------
        Dict[str, Any]
            Component-specific state (empty dict by default)
        """
        return {}

    def _restore_component_specific_state(self, state: Dict[str, Any]) -> None:
        """
        Restore component-specific state from persistence.
        Override in derived components to restore specific state variables.

        Parameters
        ----------
        state : Dict[str, Any]
            Previously saved state containing component-specific data
        """
        pass

    def _reset_state(self) -> None:
        """
        Reset component-specific state variables to their initial values.

        Called by deploy infrastructure after an exit fill to clear stale
        per-trade state (stop prices, take-profit levels, bar counters)
        so the component is clean for the next trade cycle.

        Override in stateful components (especially exit_rule) to reset
        all instance variables that track per-trade state. The override
        MUST reset every variable returned by _get_component_specific_state().

        Default: no-op (stateless components need no reset).
        """
        pass


# =============================================================================
# Role-specific component aliases
# =============================================================================
# BaseComponent is the universal abstract class; Echolon strategies carry
# specialised entry_rule / exit_rule / risk_manager / position_sizer subclasses
# inside user strategy directories. The aliases below make the role-specific
# contract discoverable by name for documentation, type-checking, and
# catalog-error tests that refer to e.g. EntryComponent explicitly.

EntryComponent = BaseComponent
ExitComponent = BaseComponent
RiskComponent = BaseComponent
SizerComponent = BaseComponent
