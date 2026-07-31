"""
Session-Aware Strategy Hook
===========================

Hook for intraday trading with session context support and forced day-end flatten.

This hook provides:

1. SESSION & DAY CONTEXT HELPERS (injected into BaseStrategy):

   DAY-level helpers:
   - get_bar_of_day(): Bar position in trading DAY (0-indexed)
   - get_bars_remaining(): Bars until DAY end (holiday-aware)
   - get_total_bars_today(): Total bars for the trading day
   - get_has_night_session(): Whether night session exists (False after holidays)

   SESSION-level helpers:
   - get_session_context(): Complete session context
   - get_bar_of_session(): Bar position in SESSION (0-indexed)
   - get_bars_remaining_in_session(): Bars until SESSION end
   - get_session_bars_total(): Total bars for current session
   - get_session_index(): Session index (0-based)
   - is_first_session(): First session check
   - is_last_session(): Last session check
   - is_session_break(): Break check
   - is_opening_phase(): Opening phase check
   - is_closing_phase(): Closing phase check
   - get_minutes_since_session_open(): Minutes since session open
   - get_minutes_to_session_close(): Minutes until session close

   Price-level helpers:
   - get_vwap(): Session VWAP
   - get_opening_range(): Opening range high/low

2. INFRASTRUCTURE-LEVEL DAY-END FLATTEN:
   - On each bar, checks if `bars_remaining <= flatten_bars_before_close`
   - If position exists, forces exit BEFORE strategy logic runs
   - Similar to ForcedExitStrategyHook for contract expiry

When to use:
- Intraday trading (any market)
- Strategies that need session context (opening range, session phase, etc.)
- NOT needed for interday/daily strategies
"""

from typing import Optional, Tuple, TYPE_CHECKING
import logging

from .strategy_hook_base import IStrategyHook
from ..interfaces import OrderIntent

if TYPE_CHECKING:
    from ..base import BaseStrategy
    from echolon.strategy.frequency.session_interface import SessionContext
    from echolon.strategy.frequency.interface import IFrequencyContext

logger = logging.getLogger(__name__)


class SessionAwareStrategyHook(IStrategyHook):
    """
    Hook for intraday trading with session context awareness.

    Injects session context helper methods into BaseStrategy instance,
    enabling strategies to access:
    - Session phase (opening, active, closing)
    - Bar position within session
    - Session-aware indicators (VWAP, opening range)

    The actual session data comes from the engine's market_data component,
    which gets it from the session context provider.
    """

    @property
    def name(self) -> str:
        return "SessionAwareStrategyHook"

    def on_init(self, strategy: 'BaseStrategy') -> None:
        """
        Inject session helper methods into strategy instance.
        """
        # Store reference to strategy for helper methods
        self._strategy = strategy

        # Get frequency context for flatten logic
        self._frequency_context: Optional['IFrequencyContext'] = None
        if hasattr(strategy, 'trading_engine') and strategy.trading_engine is not None:
            if hasattr(strategy.trading_engine, 'get_frequency_context'):
                self._frequency_context = strategy.trading_engine.get_frequency_context()

        # Inject helper methods as bound methods

        # DAY-level helpers
        strategy.get_bar_of_day = self._get_bar_of_day
        strategy.get_bars_remaining = self._get_bars_remaining  # DAY end, not session
        strategy.get_total_bars_today = self._get_total_bars_today
        strategy.get_has_night_session = self._get_has_night_session

        # SESSION-level helpers (get_session_phase is a base method, not hook-injected)
        strategy.get_session_context = self._get_session_context
        strategy.get_bar_of_session = self._get_bar_of_session
        strategy.get_bars_remaining_in_session = self._get_bars_remaining_in_session
        strategy.get_session_bars_total = self._get_session_bars_total
        strategy.get_session_index = self._get_session_index
        strategy.is_first_session = self._is_first_session
        strategy.is_last_session = self._is_last_session
        strategy.is_session_break = self._is_session_break
        strategy.is_opening_phase = self._is_opening_phase
        strategy.is_closing_phase = self._is_closing_phase
        strategy.get_minutes_since_session_open = self._get_minutes_since_session_open
        strategy.get_minutes_to_session_close = self._get_minutes_to_session_close

        # Price-level helpers
        strategy.get_vwap = self._get_vwap
        strategy.get_opening_range = self._get_opening_range

        logger.debug(f"[{self.name}] Session and day helpers injected into strategy")

    def on_start(self, strategy: 'BaseStrategy') -> None:
        """No action needed on start."""
        pass

    def on_bar_start(self, strategy: 'BaseStrategy') -> bool:
        """
        Check for day-end flatten BEFORE strategy logic runs.

        If position exists and we're within flatten_bars_before_close of day end,
        force exit the position. This is infrastructure-level enforcement similar
        to ForcedExitStrategyHook for contract expiry.

        Returns:
            True to continue processing, False if forced flatten was executed
        """
        # Skip if no frequency context or flatten not enabled
        if self._frequency_context is None:
            return True

        if not self._frequency_context.flatten_at_close:
            return True

        # Skip if no position
        if not strategy.has_position():
            return True

        # Skip if pending orders (avoid duplicate exits)
        if strategy.has_pending_orders():
            return True

        # Get bars_remaining indicator (day-level, holiday-aware)
        bars_remaining = strategy.get_indicator('bars_remaining')

        # Check if should flatten
        if self._frequency_context.should_flatten_for_close(int(bars_remaining)):
            # Force exit position
            current_price = strategy.get_current_price()
            position_size = abs(strategy.get_position_size())

            if strategy.is_long_position():
                intent = OrderIntent.EXIT_LONG
            else:
                intent = OrderIntent.EXIT_SHORT

            # Log to both strategy logger and console for visibility
            flatten_msg = (
                f"[DAY_END_FLATTEN] Forced exit triggered: "
                f"bars_remaining={int(bars_remaining)}, "
                f"size={position_size}, price={current_price:.2f}"
            )
            strategy.log(flatten_msg)
            print(flatten_msg)

            # Submit exit order
            result = strategy.exit(intent=intent, size=position_size)

            if result.status.name in ['SUBMITTED', 'ACCEPTED']:
                # Log to strategy logger if available
                if hasattr(strategy, 'strategy_logger') and strategy.strategy_logger:
                    strategy.strategy_logger.log_order_event({
                        'action': 'submit',
                        'side': intent.value,
                        'size': position_size,
                        'status': result.status.value,
                        'order_id': result.order_id,
                        'is_forced_exit': True,
                        'forced_exit_reason': f'Day-end flatten: bars_remaining={int(bars_remaining)}',
                    })
                return False  # Skip strategy logic this bar

            strategy.log(f"[DAY_END_FLATTEN] Exit order failed: {result.message}", "error")

        return True  # Continue with strategy logic

    def on_bar_end(self, strategy: 'BaseStrategy') -> None:
        """No action needed on bar end."""
        pass

    def on_stop(self, strategy: 'BaseStrategy') -> None:
        """No action needed on stop."""
        pass

    # =========================================================================
    # Session Helper Methods (injected into strategy)
    # =========================================================================

    def _get_session_context(self) -> Optional['SessionContext']:
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

        Returns None if session context provider not available.
        """
        if hasattr(self._strategy.market_data, 'get_session_context'):
            return self._strategy.market_data.get_session_context()
        return None

    # =========================================================================
    # DAY-Level Helpers
    # =========================================================================

    def _get_bar_of_day(self) -> int:
        """
        Get current bar position within trading DAY (0-indexed).

        Uses the pre-computed `bar_of_day` indicator.
        Returns 0 if indicator not available.
        """
        try:
            return int(self._strategy.get_indicator('bar_of_day'))
        except (KeyError, TypeError, AttributeError):
            return 0

    def _get_total_bars_today(self) -> int:
        """
        Get total bars for this trading day.

        Uses the pre-computed `total_bars_today` indicator which varies by:
        - Bar size (smaller bars = more bars per day)
        - Holiday schedule (no night session = fewer bars)

        Returns 0 if indicator not available.
        """
        try:
            return int(self._strategy.get_indicator('total_bars_today'))
        except (KeyError, TypeError, AttributeError):
            return 0

    def _get_has_night_session(self) -> bool:
        """
        Check if this trading day has a night session.

        Uses the pre-computed `has_night_session` indicator.
        Returns False after Chinese holidays when night session is cancelled.

        Returns False if indicator not available.
        """
        try:
            return bool(self._strategy.get_indicator('has_night_session'))
        except (KeyError, TypeError, AttributeError):
            return False

    # =========================================================================
    # SESSION-Level Helpers
    # =========================================================================

    def _get_bar_of_session(self) -> int:
        """
        Get current bar position within session (0-indexed).

        Uses the pre-computed `bar_of_session` indicator.
        Returns 0 if indicator not available.
        """
        try:
            return int(self._strategy.get_indicator('bar_of_session'))
        except (KeyError, TypeError, AttributeError):
            return 0

    def _get_bars_remaining(self) -> int:
        """
        Get bars remaining until DAY end (not session end).

        Uses the pre-computed `bars_remaining` indicator which is:
        - Holiday-aware (accounts for cancelled night sessions)
        - Counts down to the end of the trading DAY
        - Pre-computed during data preparation

        For bars remaining in current SESSION, use get_bars_remaining_in_session().

        Returns 0 if indicator not available.
        """
        try:
            return int(self._strategy.get_indicator('bars_remaining'))
        except (KeyError, TypeError, AttributeError):
            return 0

    def _get_bars_remaining_in_session(self) -> int:
        """
        Get bars remaining until current SESSION ends.

        Uses the pre-computed `bars_remaining_in_session` indicator.
        Use for session-specific exit timing.

        For bars remaining until DAY end, use get_bars_remaining().

        Returns 0 if indicator not available.
        """
        try:
            return int(self._strategy.get_indicator('bars_remaining_in_session'))
        except (KeyError, TypeError, AttributeError):
            return 0

    def _get_session_bars_total(self) -> int:
        """
        Get total bars for current session.

        Uses the pre-computed `session_bars_total` indicator which varies by:
        - Bar size (smaller bars = more bars per session)
        - Session type (night, morning, afternoon have different durations)

        Returns 0 if indicator not available.
        """
        try:
            return int(self._strategy.get_indicator('session_bars_total'))
        except (KeyError, TypeError, AttributeError):
            return 0

    # =========================================================================
    # Price-Level Helpers
    # =========================================================================

    def _get_vwap(self) -> Optional[float]:
        """
        Get session VWAP (Volume Weighted Average Price).

        Returns None if session context not available.
        """
        if hasattr(self._strategy.market_data, 'get_vwap'):
            return self._strategy.market_data.get_vwap()
        return None

    def _get_opening_range(self) -> Tuple[Optional[float], Optional[float]]:
        """
        Get opening range high and low.

        Returns:
            Tuple of (OR high, OR low) or (None, None) if not defined
        """
        if hasattr(self._strategy.market_data, 'get_opening_range'):
            return self._strategy.market_data.get_opening_range()
        return (None, None)

    def _is_opening_phase(self) -> bool:
        """Check if within opening phase of session."""
        if hasattr(self._strategy.market_data, 'is_opening_phase'):
            return self._strategy.market_data.is_opening_phase()
        return False

    def _is_closing_phase(self) -> bool:
        """Check if within closing phase of session."""
        if hasattr(self._strategy.market_data, 'is_closing_phase'):
            return self._strategy.market_data.is_closing_phase()
        return False

    def _get_minutes_since_session_open(self) -> int:
        """Get minutes since current session started."""
        if hasattr(self._strategy.market_data, 'get_minutes_since_session_open'):
            return self._strategy.market_data.get_minutes_since_session_open()
        return 0

    def _get_minutes_to_session_close(self) -> int:
        """Get minutes until current session ends."""
        if hasattr(self._strategy.market_data, 'get_minutes_to_session_close'):
            return self._strategy.market_data.get_minutes_to_session_close()
        return 0

    def _get_session_index(self) -> int:
        """Get 0-based index of current session."""
        if hasattr(self._strategy.market_data, 'get_session_index'):
            return self._strategy.market_data.get_session_index()
        return 0

    def _is_first_session(self) -> bool:
        """Check if in first session of trading day."""
        if hasattr(self._strategy.market_data, 'is_first_session'):
            return self._strategy.market_data.is_first_session()
        return False

    def _is_last_session(self) -> bool:
        """Check if in last session of trading day."""
        if hasattr(self._strategy.market_data, 'is_last_session'):
            return self._strategy.market_data.is_last_session()
        return False

    def _is_session_break(self) -> bool:
        """Check if in a session break (lunch, morning break)."""
        if hasattr(self._strategy.market_data, 'is_session_break'):
            return self._strategy.market_data.is_session_break()
        return False

    def __repr__(self) -> str:
        return f"SessionAwareStrategyHook()"
