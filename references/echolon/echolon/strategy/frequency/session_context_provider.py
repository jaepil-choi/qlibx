"""
Session Context Provider (Base Class)
======================================

Abstract base class for session context providers.

This module provides the base infrastructure for session context,
with market-specific implementations in market_adapters/.

DESIGN PRINCIPLE:
    Infrastructure provides FACTUAL DATA only.
    Strategy decides how to use this data (opening range bars,
    closing phase thresholds, etc.).

Market-specific implementations:
- SHFESessionProvider: modules/quant_engine/market_adapters/shfe/
- CryptoSessionProvider: modules/quant_engine/market_adapters/crypto/

Usage:
    # Get provider from market adapter
    provider = market_adapter.create_session_provider(bar_size_minutes=5)
    ctx = provider.get_session_context(current_time)

    # Strategy uses factual data: ctx.bar_of_session, ctx.bars_remaining, etc.
    # Strategy decides: if ctx.bar_of_session < my_opening_bars_threshold: ...
"""

import logging
from abc import abstractmethod
from datetime import datetime, time
from typing import Optional, Dict, TYPE_CHECKING

from .session_interface import (
    SessionContext,
    ISessionContext,
)
from echolon.config.markets.core.types import SessionPhaseSpec

if TYPE_CHECKING:
    from echolon.markets.interface import IMarketAdapter

logger = logging.getLogger(__name__)


class BaseSessionContextProvider(ISessionContext):
    """
    Abstract base class for session context providers.

    Provides FACTUAL session context data. Market-specific implementations
    override abstract methods.

    DESIGN PRINCIPLE:
        Infrastructure provides factual data only:
        - bar_of_session, bars_remaining (factual positions)
        - session_type, session_phase (factual phase info)
        - session_high, session_low, vwap (factual price data)

        Strategy decides:
        - What constitutes "opening phase" (first N bars)
        - What constitutes "closing phase" (last N bars)
        - When to flatten positions

    Parameters:
        market_adapter: Market adapter for session/calendar info
        bar_size_minutes: Bar size in minutes (default: 5)
    """

    def __init__(
        self,
        market_adapter: 'IMarketAdapter' = None,
        bar_size_minutes: int = 5,
    ):
        self._market_adapter = market_adapter
        self._bar_size_minutes = bar_size_minutes

        # Load session phases (market-specific)
        self._session_phases = self._load_session_phases()

        # Session state tracking (reset at session boundaries)
        self._current_session_start: Optional[datetime] = None
        self._session_bar_count: int = 0
        self._session_high: Optional[float] = None
        self._session_low: Optional[float] = None
        self._prev_session_close: Optional[float] = None
        self._vwap_numerator: float = 0.0
        self._vwap_denominator: float = 0.0

        # NOTE: Bars per phase is NOT calculated here because phases may contain
        # embedded breaks (e.g., SHFE morning phase includes morning_break).
        # Use market-specific get_phase_trading_bars() for accurate bar counts.

        logger.debug(
            f"{self.__class__.__name__} initialized: "
            f"bar_size={bar_size_minutes}min"
        )

    # =========================================================================
    # Abstract Methods (market-specific implementations required)
    # =========================================================================

    @abstractmethod
    def _load_session_phases(self) -> Dict[str, SessionPhaseSpec]:
        """
        Load session phases for this market.

        Returns:
            Dictionary of phase_name -> SessionPhaseSpec
        """
        pass

    @abstractmethod
    def _get_session_start_time(self, session_type: str) -> time:
        """
        Get the start time for a session type.

        Args:
            session_type: 'night', 'day', or market-specific type

        Returns:
            Time when session starts
        """
        pass

    @abstractmethod
    def _get_session_end_time(self, session_type: str) -> time:
        """
        Get the end time for a session type.

        Args:
            session_type: 'night', 'day', or market-specific type

        Returns:
            Time when session ends
        """
        pass

    @abstractmethod
    def _get_break_minutes_before(self, current_time: datetime) -> int:
        """
        Get total break minutes that occurred before current_time in this session.

        Args:
            current_time: Current datetime

        Returns:
            Minutes of breaks that have passed
        """
        pass

    @abstractmethod
    def _get_total_bars_in_session(self, session_type: str) -> int:
        """
        Get total bars in a session type.

        Args:
            session_type: 'night', 'day', etc.

        Returns:
            Total number of bars in session
        """
        pass

    @abstractmethod
    def get_total_sessions_per_day(self) -> int:
        """Get total number of sessions per trading day."""
        pass

    # =========================================================================
    # ISessionContext Implementation (generic logic)
    # =========================================================================

    def get_session_context(self, current_time: datetime) -> SessionContext:
        """
        Get complete session context for current bar.

        Provides FACTUAL data only. Strategy decides how to interpret:
        - bar_of_session: Strategy decides if this is "opening phase"
        - bars_remaining: Strategy decides if this is "closing phase"

        Args:
            current_time: Current datetime

        Returns:
            SessionContext with factual session information
        """
        phase_name = self.get_session_phase(current_time)
        phase_spec = self._session_phases.get(phase_name) if phase_name else None

        session_type = phase_spec.session_type if phase_spec else 'unknown'
        is_trading = phase_spec.is_trading if phase_spec else False
        # Phase-defined opening/closing (from market config, not strategy params)
        is_opening_phase_flag = phase_spec.is_opening if phase_spec else False
        is_closing_phase_flag = phase_spec.is_closing if phase_spec else False

        bar_of_session = self.get_bar_of_session(current_time)
        bars_remaining = self.get_bars_remaining_in_session(current_time)
        total_bars = self._get_total_bars_in_session(session_type)

        # Calculate session progress
        if total_bars > 0:
            session_progress = bar_of_session / total_bars
        else:
            session_progress = 0.0

        # Gap calculation
        gap_pct = None
        if self._prev_session_close is not None and self._session_high is not None:
            session_open = (self._session_high + self._session_low) / 2 if self._session_low else self._session_high
            gap_pct = ((session_open - self._prev_session_close) / self._prev_session_close) * 100

        # VWAP calculation
        vwap = None
        if self._vwap_denominator > 0:
            vwap = self._vwap_numerator / self._vwap_denominator

        # Minutes-based timing
        minutes_since_open = self.get_minutes_since_session_open(current_time)
        minutes_to_close = self.get_minutes_to_session_close(current_time)
        minutes_to_next = self.get_minutes_to_next_session(current_time)

        # Session index
        session_idx = self.get_session_index(current_time)
        total_sessions = self.get_total_sessions_per_day()

        return SessionContext(
            session_type=session_type,
            session_phase=phase_name or 'unknown',
            bar_of_session=bar_of_session,
            bars_remaining_in_session=bars_remaining,  # SESSION-level, not day
            total_bars_in_session=total_bars,
            session_progress=min(1.0, max(0.0, session_progress)),
            # Minutes-based timing
            minutes_since_session_open=minutes_since_open,
            minutes_to_session_close=minutes_to_close,
            minutes_to_next_session=minutes_to_next,
            # Session index
            session_index=max(0, session_idx),
            total_sessions_per_day=total_sessions,
            is_first_session=self.is_first_session(current_time),
            is_last_session=self.is_last_session(current_time),
            # Boundary flags (factual)
            is_first_bar=(bar_of_session == 0),
            is_last_bar=(bars_remaining <= 0),  # bars_remaining here is SESSION-level
            # Phase flags from market config (factual phase definitions)
            is_opening_phase=is_opening_phase_flag,
            is_closing_phase=is_closing_phase_flag,
            is_trading_allowed=is_trading,
            is_session_break=self.is_session_break(current_time),
            # Gap and levels
            gap_pct=gap_pct,
            prev_session_close=self._prev_session_close,
            # Opening range not tracked by infrastructure - strategy calculates
            or_high=None,
            or_low=None,
            or_defined=False,
            session_high=self._session_high,
            session_low=self._session_low,
            vwap=vwap,
            timestamp=current_time,
        )

    def get_session_type(self, current_time: datetime) -> str:
        """Get current session type ('night', 'day', or 'break')."""
        phase = self.get_session_phase(current_time)
        if phase is None:
            return 'break'

        spec = self._session_phases.get(phase)
        if spec is None:
            return 'unknown'

        if not spec.is_trading:
            return 'break'

        return spec.session_type

    def get_session_phase(self, current_time: datetime) -> Optional[str]:
        """Get current session phase name."""
        check_time = current_time.time()

        for name, spec in self._session_phases.items():
            if spec.contains_time(check_time):
                return name

        return None

    def get_bar_of_session(self, current_time: datetime) -> int:
        """Get 0-indexed bar position within session."""
        session_type = self.get_session_type(current_time)
        if session_type in ('break', 'unknown'):
            return 0

        # Get session start
        session_start_time = self._get_session_start_time(session_type)
        session_start = current_time.replace(
            hour=session_start_time.hour,
            minute=session_start_time.minute,
            second=0,
            microsecond=0
        )

        # Handle sessions that cross midnight
        if current_time.time() < session_start_time:
            # We might be past midnight in a session that started yesterday
            from datetime import timedelta
            session_start -= timedelta(days=1)

        # Calculate minutes since session start
        delta = current_time - session_start
        minutes_elapsed = delta.total_seconds() / 60

        # Subtract break times
        break_minutes = self._get_break_minutes_before(current_time)
        minutes_elapsed -= break_minutes

        return max(0, int(minutes_elapsed // self._bar_size_minutes))

    def get_bars_remaining_in_session(self, current_time: datetime) -> int:
        """Get bars remaining until SESSION end (not day end)."""
        session_type = self.get_session_type(current_time)
        total_bars = self._get_total_bars_in_session(session_type)
        bar_of_session = self.get_bar_of_session(current_time)
        return max(0, total_bars - bar_of_session - 1)

    def is_trading_allowed(self, current_time: datetime) -> bool:
        """Check if trading is allowed (not in break)."""
        phase = self.get_session_phase(current_time)
        if phase is None:
            return False
        spec = self._session_phases.get(phase)
        return spec.is_trading if spec else False

    def get_minutes_since_session_open(self, current_time: datetime) -> int:
        """Get minutes since current session started."""
        session_type = self.get_session_type(current_time)
        if session_type in ('break', 'unknown'):
            return 0

        bar_of_session = self.get_bar_of_session(current_time)
        return bar_of_session * self._bar_size_minutes

    def get_minutes_to_session_close(self, current_time: datetime) -> int:
        """Get minutes until current session ends."""
        session_type = self.get_session_type(current_time)
        if session_type in ('break', 'unknown'):
            return 0

        bars_remaining = self.get_bars_remaining_in_session(current_time)
        return bars_remaining * self._bar_size_minutes

    def get_minutes_to_next_session(self, current_time: datetime) -> Optional[int]:
        """Get minutes until next session starts."""
        if self.is_trading_allowed(current_time):
            return None  # Already in session
        # Market-specific implementations should override for accuracy
        return None

    def get_session_index(self, current_time: datetime) -> int:
        """Get 0-based index of current session within trading day."""
        session_type = self.get_session_type(current_time)
        if session_type == 'break':
            return -1
        # Default: single session
        return 0

    def is_session_break(self, current_time: datetime) -> bool:
        """Check if currently in a session break."""
        phase = self.get_session_phase(current_time)
        if phase is None:
            return True

        spec = self._session_phases.get(phase)
        if spec is None:
            return True

        return not spec.is_trading

    def is_first_session(self, current_time: datetime) -> bool:
        """Check if currently in first session of trading day."""
        return self.get_session_index(current_time) == 0

    def is_last_session(self, current_time: datetime) -> bool:
        """Check if currently in last session of trading day."""
        idx = self.get_session_index(current_time)
        return idx == self.get_total_sessions_per_day() - 1 and idx >= 0

    # =========================================================================
    # State Update Methods (called by data processor)
    # =========================================================================

    def update_bar(
        self,
        current_time: datetime,
        high: float,
        low: float,
        close: float,
        volume: float,
        typical_price: float = None,
    ) -> None:
        """
        Update session state with new bar data.

        Called by data processor on each new bar.
        Tracks FACTUAL data only (session high/low, VWAP).
        Opening range tracking is strategy's responsibility.

        Args:
            current_time: Bar timestamp
            high: Bar high
            low: Bar low
            close: Bar close
            volume: Bar volume
            typical_price: (H+L+C)/3 for VWAP (computed if not provided)
        """
        bar_of_session = self.get_bar_of_session(current_time)

        if bar_of_session == 0:
            self._on_session_start(current_time, close)

        # Update session high/low (factual)
        if self._session_high is None or high > self._session_high:
            self._session_high = high
        if self._session_low is None or low < self._session_low:
            self._session_low = low

        # Update VWAP (factual)
        if typical_price is None:
            typical_price = (high + low + close) / 3
        self._vwap_numerator += typical_price * volume
        self._vwap_denominator += volume

        self._session_bar_count = bar_of_session + 1

    def _on_session_start(self, current_time: datetime, first_price: float) -> None:
        """Handle session start - reset state and capture gap."""
        if self._session_high is not None:
            self._prev_session_close = first_price

        self._current_session_start = current_time
        self._session_bar_count = 0
        self._session_high = None
        self._session_low = None
        self._vwap_numerator = 0.0
        self._vwap_denominator = 0.0

        logger.debug(
            f"Session started: {current_time}, prev_close={self._prev_session_close}"
        )

    def set_previous_session_close(self, close_price: float) -> None:
        """Set previous session close for gap calculation."""
        self._prev_session_close = close_price

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def get_phase_spec(self, phase_name: str) -> Optional[SessionPhaseSpec]:
        """Get phase specification by name."""
        return self._session_phases.get(phase_name)

    def get_all_phases(self) -> Dict[str, SessionPhaseSpec]:
        """Get all session phase specifications."""
        return self._session_phases.copy()

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(bar_size={self._bar_size_minutes}min)"
