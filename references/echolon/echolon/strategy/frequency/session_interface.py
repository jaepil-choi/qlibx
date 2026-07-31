"""
Session Context Interface
=========================

Interfaces and data classes for intraday session context.

This module provides:
- SessionContext: Rich data object with session information
- ISessionContext: Interface for session context access
- ISessionIndicators: Interface for session-aware indicators

DESIGN PRINCIPLE:
    Infrastructure provides FACTUAL DATA only.
    Strategy decides HOW TO USE this data.

Example:
    Infrastructure: "It's night phase, bar 3 of 48"
    Strategy: "I'll check bar_of_session against opening buffer"

The volatility multipliers, sizing factors, and trading rules belong
in strategy components, NOT in infrastructure configuration.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, time
from typing import Optional, Tuple


# =============================================================================
# Session Context Data Class
# =============================================================================

@dataclass
class SessionContext:
    """
    Rich session context for strategy consumption.

    INFRASTRUCTURE: Provides factual data only.
    STRATEGY: Decides how to use this data.

    This is a frozen snapshot of session state at a point in time.
    All values are computed by infrastructure and consumed by strategy.

    Attributes:
        session_type: 'night' or 'day'
        session_phase: Current phase name (e.g., 'night', 'morning', 'afternoon')

        Bar Position:
        bar_of_session: 0-indexed bar position within session
        bars_remaining_in_session: Bars until SESSION end (not day end)
        total_bars_in_session: Total bars in current session
        session_progress: 0.0 to 1.0 progress through session

        Time Position (minutes-based):
        minutes_since_session_open: Minutes since session started
        minutes_to_session_close: Minutes until session ends
        minutes_to_next_session: Minutes until next session (None if in session)

        Session Index:
        session_index: 0-based index of current session
        total_sessions_per_day: Total sessions in trading day
        is_first_session: True if first session of day
        is_last_session: True if last session of day

        Boundary Flags:
        is_first_bar: True if first bar of session
        is_last_bar: True if last bar of session
        is_opening_phase: True if within opening phase (first N bars)
        is_closing_phase: True if within closing phase (last N bars)
        is_trading_allowed: False during breaks
        is_session_break: True if between sessions

        Gap Context:
        gap_pct: Percentage gap from previous session close
        prev_session_close: Previous session closing price
        gap_direction: 1=up, -1=down, 0=flat

        Opening Range:
        or_high: Opening range high (None if not yet defined)
        or_low: Opening range low (None if not yet defined)
        or_defined: Whether opening range is fully defined
        or_width: Opening range width (high - low)

        Session Levels:
        session_high: Session high so far
        session_low: Session low so far
        vwap: Volume-weighted average price

        Price Context:
        current_price: Current price (for convenience)
        timestamp: Timestamp of this context snapshot
    """
    # Session Identification
    session_type: str               # 'night', 'day'
    session_phase: str              # 'night', 'morning', 'afternoon', etc.

    # Bar Position (Numerical Facts)
    bar_of_session: int             # 0-indexed position
    bars_remaining_in_session: int  # Bars until SESSION end (not day end)
    total_bars_in_session: int      # Total bars in current session
    session_progress: float         # 0.0 to 1.0

    # Time Position (Minutes-based Facts) - merged from SessionHandler
    minutes_since_session_open: int = 0     # Minutes since session started
    minutes_to_session_close: int = 0       # Minutes until session ends
    minutes_to_next_session: Optional[int] = None  # Minutes until next session (if in break)

    # Session Index (for multi-session days)
    session_index: int = 0          # 0-based index of current session
    total_sessions_per_day: int = 1 # Total sessions in trading day
    is_first_session: bool = False  # First session of day
    is_last_session: bool = False   # Last session of day

    # Boundary Flags (Boolean Facts)
    is_first_bar: bool = False
    is_last_bar: bool = False
    is_opening_phase: bool = False  # Within first N bars
    is_closing_phase: bool = False  # Within last N bars
    is_trading_allowed: bool = True # False during breaks
    is_session_break: bool = False  # Between sessions (lunch break, etc.)

    # Gap Context
    gap_pct: Optional[float] = None         # Gap from previous session
    prev_session_close: Optional[float] = None
    gap_direction: int = 0                  # 1=up, -1=down, 0=flat/unknown

    # Opening Range (None if not yet defined)
    or_high: Optional[float] = None
    or_low: Optional[float] = None
    or_defined: bool = False
    or_width: Optional[float] = None        # OR high - OR low

    # Session Levels
    session_high: Optional[float] = None
    session_low: Optional[float] = None

    # Price Context
    current_price: Optional[float] = None
    vwap: Optional[float] = None

    # Timestamp
    timestamp: Optional[datetime] = None

    def __post_init__(self):
        """Compute derived fields."""
        # Compute OR width if both bounds are defined
        if self.or_high is not None and self.or_low is not None:
            self.or_width = self.or_high - self.or_low
            self.or_defined = True

        # Compute gap direction
        if self.gap_pct is not None:
            if self.gap_pct > 0.1:  # > 0.1% threshold
                self.gap_direction = 1
            elif self.gap_pct < -0.1:
                self.gap_direction = -1
            else:
                self.gap_direction = 0

    @property
    def is_night_session(self) -> bool:
        """Check if currently in night session."""
        return self.session_type == 'night'

    @property
    def is_day_session(self) -> bool:
        """Check if currently in day session."""
        return self.session_type == 'day'

    @property
    def price_vs_vwap(self) -> Optional[float]:
        """Get price deviation from VWAP as percentage."""
        if self.current_price is None or self.vwap is None or self.vwap == 0:
            return None
        return ((self.current_price - self.vwap) / self.vwap) * 100

    @property
    def price_vs_or_high(self) -> Optional[float]:
        """Get price vs opening range high as percentage."""
        if self.current_price is None or self.or_high is None:
            return None
        return ((self.current_price - self.or_high) / self.or_high) * 100

    @property
    def price_vs_or_low(self) -> Optional[float]:
        """Get price vs opening range low as percentage."""
        if self.current_price is None or self.or_low is None:
            return None
        return ((self.current_price - self.or_low) / self.or_low) * 100

    @property
    def or_breakout_status(self) -> int:
        """
        Get opening range breakout status.

        Returns:
            1 if price above OR high (bullish breakout)
            -1 if price below OR low (bearish breakout)
            0 if price inside OR or OR not defined
        """
        if not self.or_defined or self.current_price is None:
            return 0
        if self.current_price > self.or_high:
            return 1
        if self.current_price < self.or_low:
            return -1
        return 0

    def to_dict(self) -> dict:
        """Convert to dictionary for logging."""
        return {
            'session_type': self.session_type,
            'session_phase': self.session_phase,
            'bar_of_session': self.bar_of_session,
            'bars_remaining': self.bars_remaining,
            'session_progress': round(self.session_progress, 3),
            'minutes_since_session_open': self.minutes_since_session_open,
            'minutes_to_session_close': self.minutes_to_session_close,
            'session_index': self.session_index,
            'is_first_session': self.is_first_session,
            'is_last_session': self.is_last_session,
            'is_first_bar': self.is_first_bar,
            'is_last_bar': self.is_last_bar,
            'is_opening_phase': self.is_opening_phase,
            'is_closing_phase': self.is_closing_phase,
            'is_session_break': self.is_session_break,
            'gap_pct': round(self.gap_pct, 4) if self.gap_pct else None,
            'or_high': self.or_high,
            'or_low': self.or_low,
            'or_defined': self.or_defined,
            'session_high': self.session_high,
            'session_low': self.session_low,
            'vwap': self.vwap,
        }


# =============================================================================
# Session Phase Configuration
# =============================================================================
# NOTE: SessionPhaseSpec is defined in config/markets/core/types.py
# Import from there: from echolon.config.markets.core.types import SessionPhaseSpec


# =============================================================================
# Session Context Interface
# =============================================================================

class ISessionContext(ABC):
    """
    Interface for session context access.

    DESIGN PRINCIPLE:
        Infrastructure provides FACTUAL DATA only.
        Strategy decides how to interpret this data.

    Factual data provided:
        - get_bar_of_session(): Current bar position in SESSION (0-indexed)
        - get_bars_remaining_in_session(): Bars until SESSION end
        - get_session_type(): 'night', 'day', or 'break'
        - get_session_phase(): Phase name from market config

    Strategy decides:
        - What constitutes "opening phase" (e.g., bar_of_session < 6)
        - What constitutes "closing phase" (e.g., bars_remaining_in_session < 3)
        - When to flatten positions
    """

    @abstractmethod
    def get_session_context(self, current_time: datetime) -> SessionContext:
        """
        Get complete session context for current bar.

        Args:
            current_time: Current datetime

        Returns:
            SessionContext with factual session information
        """
        pass

    @abstractmethod
    def get_session_type(self, current_time: datetime) -> str:
        """
        Get current session type.

        Args:
            current_time: Current datetime

        Returns:
            'night', 'day', or 'break'
        """
        pass

    @abstractmethod
    def get_session_phase(self, current_time: datetime) -> Optional[str]:
        """
        Get current session phase name.

        Args:
            current_time: Current datetime

        Returns:
            Phase name (e.g., 'night', 'morning', 'afternoon') or None if not in session
        """
        pass

    @abstractmethod
    def get_bar_of_session(self, current_time: datetime) -> int:
        """
        Get 0-indexed bar position within session.

        Strategy uses this to determine opening phase:
            if bar_of_session < my_opening_bars: ...

        Args:
            current_time: Current datetime

        Returns:
            Bar index (0 = first bar of session)
        """
        pass

    @abstractmethod
    def get_bars_remaining_in_session(self, current_time: datetime) -> int:
        """
        Get bars remaining until SESSION end (not day end).

        Strategy uses this to determine closing phase:
            if bars_remaining_in_session < my_closing_bars: ...

        Args:
            current_time: Current datetime

        Returns:
            Number of bars remaining in current session
        """
        pass

    @abstractmethod
    def is_trading_allowed(self, current_time: datetime) -> bool:
        """
        Check if trading is allowed (not in break).

        Args:
            current_time: Current datetime

        Returns:
            True if trading is allowed
        """
        pass


# =============================================================================
# Session Indicators Interface
# =============================================================================

class ISessionIndicators(ABC):
    """
    Interface for session-aware indicators.

    These indicators reset at session/trading day boundaries
    and are specific to intraday trading.
    """

    @abstractmethod
    def get_vwap(self, index: int = 0) -> Optional[float]:
        """
        Get VWAP (Volume Weighted Average Price).

        VWAP resets at trading day boundary (21:00 for SHFE).

        Args:
            index: Historical index (0=current, 1=previous, etc.)

        Returns:
            VWAP value or None if not available
        """
        pass

    @abstractmethod
    def get_vwap_deviation(self, index: int = 0) -> Optional[float]:
        """
        Get price deviation from VWAP as percentage.

        Args:
            index: Historical index

        Returns:
            Deviation percentage or None
        """
        pass

    @abstractmethod
    def get_opening_range(self) -> Tuple[Optional[float], Optional[float]]:
        """
        Get opening range high and low.

        Opening range is defined by first N bars of session.

        Returns:
            Tuple of (OR high, OR low) or (None, None) if not yet defined
        """
        pass

    @abstractmethod
    def is_opening_range_defined(self) -> bool:
        """
        Check if opening range is fully defined.

        Returns:
            True if OR is defined (first N bars completed)
        """
        pass

    @abstractmethod
    def get_opening_range_width(self) -> Optional[float]:
        """
        Get opening range width (high - low).

        Returns:
            OR width or None if not defined
        """
        pass

    @abstractmethod
    def get_session_high(self) -> Optional[float]:
        """
        Get session high so far.

        Returns:
            Session high or None
        """
        pass

    @abstractmethod
    def get_session_low(self) -> Optional[float]:
        """
        Get session low so far.

        Returns:
            Session low or None
        """
        pass

    @abstractmethod
    def get_volume_percentile(self) -> Optional[float]:
        """
        Get current bar volume as session percentile (0-100).

        Returns:
            Volume percentile or None
        """
        pass

    @abstractmethod
    def get_relative_volume(self) -> Optional[float]:
        """
        Get current volume relative to session average.

        Returns:
            Relative volume (1.0 = average) or None
        """
        pass


# =============================================================================
# Trading Constraints Interface
# =============================================================================

class ITradingConstraints(ABC):
    """
    Interface for infrastructure-level trading constraints.

    These are HARD CONSTRAINTS from infrastructure, not strategy decisions.
    Examples:
    - Can't trade during breaks
    - Can't open positions in last N bars (configurable)
    - Must close before contract expiry
    """

    @abstractmethod
    def can_open_new_position(self, current_time: datetime) -> Tuple[bool, str]:
        """
        Check if new positions can be opened.

        Infrastructure constraint, not strategy decision.

        Args:
            current_time: Current datetime

        Returns:
            Tuple of (allowed, reason)
            Examples:
            - (False, "Market closed for break")
            - (False, "Too close to session end")
            - (True, "Trading allowed")
        """
        pass

    @abstractmethod
    def must_close_position_before(self, current_time: datetime) -> Optional[datetime]:
        """
        Get deadline for position closure if applicable.

        Examples:
        - Contract expiry deadline
        - End of session for intraday-only positions

        Args:
            current_time: Current datetime

        Returns:
            Deadline datetime or None if no deadline
        """
        pass

    @abstractmethod
    def get_no_entry_bars(self) -> int:
        """
        Get number of bars before session end where no new entries allowed.

        This is a configurable constraint (via parameters), not hardcoded.

        Returns:
            Number of bars
        """
        pass

    @abstractmethod
    def get_opening_range_bars(self) -> int:
        """
        Get number of bars that define the opening range.

        This is a configurable constraint (via parameters).

        Returns:
            Number of bars
        """
        pass
