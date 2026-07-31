"""
Session-Aware Component Hook
============================

Hook for intraday trading with session context support for components.

This hook adds session context helpers to BaseComponent:

DAY-level helpers (use mandatory bar count indicators):
- get_bar_of_day(): Bar position in trading DAY (0-indexed)
- get_bars_remaining(): Bars until DAY end (holiday-aware)
- get_total_bars_today(): Total bars for the trading day
- get_has_night_session(): Whether night session exists

SESSION-level helpers:
- get_session_context(): Complete session context
- get_bar_of_session(): Bar position in SESSION (0-indexed)
- get_bars_remaining_in_session(): Bars until SESSION end (not day end)
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

When to use:
- Intraday trading (any market)
- Components that need session context (entry, exit, risk, sizer)
- NOT needed for interday/daily strategies
"""

from typing import Optional, Tuple, TYPE_CHECKING
import logging

from .component_hook_base import IComponentHook

if TYPE_CHECKING:
    from ..component import BaseComponent
    from echolon.strategy.frequency.session_interface import SessionContext

logger = logging.getLogger(__name__)


class SessionAwareComponentHook(IComponentHook):
    """
    Hook for intraday trading with session context awareness.

    Injects session context helper methods into BaseComponent instance,
    enabling components to access:
    - Session phase (opening, active, closing)
    - Bar position within session
    - Session-aware indicators (VWAP, opening range)

    The actual session data comes from the engine's market_data component,
    which gets it from the session context provider.
    """

    @property
    def name(self) -> str:
        return "SessionAwareComponentHook"

    def on_init(self, component: 'BaseComponent') -> None:
        """
        Inject session helper methods into component instance.
        """
        # Store reference to component for helper methods
        self._component = component

        # DAY-level helpers (use mandatory bar count indicators)
        component.get_bar_of_day = self._get_bar_of_day
        component.get_bars_remaining = self._get_bars_remaining
        component.get_total_bars_today = self._get_total_bars_today
        component.get_has_night_session = self._get_has_night_session

        # SESSION-level helpers (get_session_phase is a base method, not hook-injected)
        component.get_session_context = self._get_session_context
        component.get_bar_of_session = self._get_bar_of_session
        component.get_bars_remaining_in_session = self._get_bars_remaining_in_session
        component.get_session_bars_total = self._get_session_bars_total
        component.get_session_index = self._get_session_index
        component.is_first_session = self._is_first_session
        component.is_last_session = self._is_last_session
        component.is_session_break = self._is_session_break
        component.is_opening_phase = self._is_opening_phase
        component.is_closing_phase = self._is_closing_phase
        component.get_minutes_since_session_open = self._get_minutes_since_session_open
        component.get_minutes_to_session_close = self._get_minutes_to_session_close

        # Price-level helpers
        component.get_vwap = self._get_vwap
        component.get_opening_range = self._get_opening_range

        logger.debug(f"[{self.name}] Session and day helpers injected into {component.__class__.__name__}")

    def on_initialize(self, component: 'BaseComponent') -> None:
        """No action needed on initialize."""
        pass

    # =========================================================================
    # DAY-Level Helper Methods (use mandatory bar count indicators)
    # =========================================================================

    def _get_bar_of_day(self) -> int:
        """
        Get current bar position within trading DAY (0-indexed).

        Uses the pre-computed `bar_of_day` indicator.
        Returns 0 if indicator not available.
        """
        try:
            return int(self._component.get_indicator('bar_of_day'))
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
            return int(self._component.get_indicator('bars_remaining'))
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
            return int(self._component.get_indicator('total_bars_today'))
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
            return bool(self._component.get_indicator('has_night_session'))
        except (KeyError, TypeError, AttributeError):
            return False

    # =========================================================================
    # SESSION-Level Helper Methods (injected into component)
    # =========================================================================

    def _get_session_context(self) -> Optional['SessionContext']:
        """
        Get complete session context for current bar.

        Returns SessionContext with session details, or None if not available.
        """
        if hasattr(self._component.market_data, 'get_session_context'):
            return self._component.market_data.get_session_context()
        return None

    def _get_bar_of_session(self) -> int:
        """Get current bar position within session (0-indexed)."""
        try:
            return int(self._component.get_indicator('bar_of_session'))
        except (KeyError, TypeError, AttributeError):
            return 0

    def _get_bars_remaining_in_session(self) -> int:
        """Get bars remaining until SESSION end (not day end)."""
        try:
            return int(self._component.get_indicator('bars_remaining_in_session'))
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
            return int(self._component.get_indicator('session_bars_total'))
        except (KeyError, TypeError, AttributeError):
            return 0

    # =========================================================================
    # Price-Level Helper Methods (use market_data, NOT mandatory indicators)
    # =========================================================================

    def _get_vwap(self) -> Optional[float]:
        """Get session VWAP (Volume Weighted Average Price)."""
        if hasattr(self._component.market_data, 'get_vwap'):
            return self._component.market_data.get_vwap()
        return None

    def _get_opening_range(self) -> Tuple[Optional[float], Optional[float]]:
        """Get opening range high and low."""
        if hasattr(self._component.market_data, 'get_opening_range'):
            return self._component.market_data.get_opening_range()
        return (None, None)

    def _is_opening_phase(self) -> bool:
        """Check if within opening phase of session."""
        if hasattr(self._component.market_data, 'is_opening_phase'):
            return self._component.market_data.is_opening_phase()
        return False

    def _is_closing_phase(self) -> bool:
        """Check if within closing phase of session."""
        if hasattr(self._component.market_data, 'is_closing_phase'):
            return self._component.market_data.is_closing_phase()
        return False

    def _get_minutes_since_session_open(self) -> int:
        """Get minutes since current session started."""
        if hasattr(self._component.market_data, 'get_minutes_since_session_open'):
            return self._component.market_data.get_minutes_since_session_open()
        return 0

    def _get_minutes_to_session_close(self) -> int:
        """Get minutes until current session ends."""
        if hasattr(self._component.market_data, 'get_minutes_to_session_close'):
            return self._component.market_data.get_minutes_to_session_close()
        return 0

    def _get_session_index(self) -> int:
        """Get 0-based index of current session."""
        if hasattr(self._component.market_data, 'get_session_index'):
            return self._component.market_data.get_session_index()
        return 0

    def _is_first_session(self) -> bool:
        """Check if in first session of trading day."""
        if hasattr(self._component.market_data, 'is_first_session'):
            return self._component.market_data.is_first_session()
        return False

    def _is_last_session(self) -> bool:
        """Check if in last session of trading day."""
        if hasattr(self._component.market_data, 'is_last_session'):
            return self._component.market_data.is_last_session()
        return False

    def _is_session_break(self) -> bool:
        """Check if in a session break (lunch, morning break)."""
        if hasattr(self._component.market_data, 'is_session_break'):
            return self._component.market_data.is_session_break()
        return False

    def __repr__(self) -> str:
        return f"SessionAwareComponentHook()"
