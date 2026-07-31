"""
Core type definitions for market configuration.

This module contains market-agnostic dataclasses used across all markets.
These types define the contracts that market-specific modules must fulfill.
"""

from dataclasses import dataclass, field
from datetime import time
from typing import List, Optional


@dataclass
class SessionWindow:
    """
    Trading session time window.

    Represents a continuous trading period within a trading day.
    Examples: night session (21:00-01:00), morning session (09:00-11:30)
    """
    name: str
    start: time
    end: time
    crosses_midnight: bool = False

    @property
    def duration_minutes(self) -> int:
        """Calculate session duration in minutes."""
        start_mins = self.start.hour * 60 + self.start.minute
        end_mins = self.end.hour * 60 + self.end.minute
        if self.crosses_midnight:
            return (24 * 60 - start_mins) + end_mins
        return end_mins - start_mins

    def contains_time(self, t: time) -> bool:
        """Check if a time falls within this session window."""
        if self.crosses_midnight:
            return t >= self.start or t < self.end
        return self.start <= t < self.end


@dataclass
class SessionPhaseSpec:
    """
    Intraday session phase specification.

    Provides finer granularity than SessionWindow for intraday strategies.
    Examples: night, morning, lunch_break, afternoon

    DESIGN PRINCIPLE:
        Infrastructure provides FACTUAL DATA only.
        Strategy logic (volatility adjustments, sizing factors) belongs in
        strategy components, NOT in configuration.

    WARNING - EMBEDDED BREAKS:
        Some phases may CONTAIN embedded non-trading breaks within their
        time range. For example, SHFE's 'morning' phase (09:00-11:30)
        contains 'morning_break' (10:15-10:30).

        The duration_minutes and bar_count properties return the TOTAL
        time span, not actual trading time. For accurate bar counts,
        use market-specific helpers like get_phase_trading_bars().
    """
    name: str
    start: time
    end: time
    session_type: str  # 'day' | 'night'
    is_opening: bool = False
    is_closing: bool = False
    is_trading: bool = True  # False for breaks (lunch, morning break)
    crosses_midnight: bool = False

    @property
    def duration_minutes(self) -> int:
        """Calculate phase duration in minutes (total time span).

        WARNING: Does not account for embedded breaks. For SHFE morning
        phase, this returns 150 min but actual trading time is 135 min.
        """
        start_mins = self.start.hour * 60 + self.start.minute
        end_mins = self.end.hour * 60 + self.end.minute
        if self.crosses_midnight:
            return (24 * 60 - start_mins) + end_mins
        return end_mins - start_mins

    @property
    def bar_count_5min(self) -> int:
        """Number of 5-minute bars based on duration (may overcount).

        WARNING: Does not account for embedded breaks. Use market-specific
        get_phase_trading_bars() for accurate tradeable bar counts.
        """
        return self.duration_minutes // 5

    @property
    def bar_count_15min(self) -> int:
        """Number of 15-minute bars based on duration (may overcount).

        WARNING: Does not account for embedded breaks. Use market-specific
        get_phase_trading_bars() for accurate tradeable bar counts.
        """
        return self.duration_minutes // 15

    def contains_time(self, t: time) -> bool:
        """Check if a time falls within this phase."""
        if self.crosses_midnight:
            return t >= self.start or t < self.end
        return self.start <= t < self.end

    def contains(self, check_time: time) -> bool:
        """Check if a time is within this phase. Alias for contains_time()."""
        return self.contains_time(check_time)

    def __repr__(self) -> str:
        return (
            f"SessionPhaseSpec({self.name}: "
            f"{self.start.strftime('%H:%M')}-{self.end.strftime('%H:%M')}, "
            f"trading={self.is_trading})"
        )


@dataclass
class InstrumentSpec:
    """
    Complete instrument specification.

    Contains all information needed to trade an instrument:
    - Contract specifications (multiplier, tick size, margin)
    - Commission structure
    - Session information
    """
    # Basic identification
    code: str                           # Short code: 'al', 'cu'
    name: str                           # Full name: 'Aluminum', 'Copper'
    market: str                         # Market code: 'SHFE'

    # Contract specifications
    multiplier: float                   # Contract size multiplier
    tick_size: float                    # Minimum price movement
    margin_rate: float                  # Margin requirement (decimal, e.g., 0.08 = 8%)
    commission: float                   # Commission amount or rate
    commission_type: str                # 'per_contract' or 'percentage'
    close_today_commission: Optional[float] = None  # Same unit/mode as commission

    # Trading details
    currency: str = 'CNY'
    trading_unit: str = 'lots'
    min_order_size: float = 1.0

    # Session info
    has_night_session: bool = False
    sessions: List[SessionWindow] = field(default_factory=list)

    def calculate_commission(
        self,
        price: float,
        size: int,
        close_today: bool = False,
    ) -> float:
        """Calculate commission for a trade."""
        commission = (
            self.close_today_commission
            if close_today and self.close_today_commission is not None
            else self.commission
        )
        if self.commission_type == 'per_contract':
            return abs(size) * commission
        elif self.commission_type == 'percentage':
            contract_value = abs(size) * price * self.multiplier
            return contract_value * commission
        return 0.0

    def calculate_margin(self, price: float, size: int) -> float:
        """Calculate required margin."""
        contract_value = abs(size) * price * self.multiplier
        return contract_value * self.margin_rate

    def calculate_contract_value(self, price: float, size: int) -> float:
        """Calculate total contract value."""
        return abs(size) * price * self.multiplier


@dataclass
class MarketConfig:
    """
    Market-level configuration.

    Aggregates all information about a trading market/exchange.
    """
    code: str                           # 'SHFE', 'DCE', 'BINANCE'
    name: str                           # Short name
    full_name: str                      # Full official name
    timezone: str                       # 'Asia/Shanghai', 'UTC'
    currency: str                       # 'CNY', 'USD', 'USDT'

    # Optional localization
    chinese_name: Optional[str] = None
    xuntou_code: Optional[str] = None   # For broker integration

    # Feature flags
    supports_overnight: bool = True
    has_contract_expiry: bool = True    # False for crypto perpetuals
    is_24h: bool = False                # True for crypto

    # Trading calendar settings
    trading_days_per_week: float = 5.0  # 7.0 for 24h markets
    trading_days_per_year: int = 250    # 365 for 24h markets
    min_position_unit: float = 1.0      # 0.001 for crypto fractional

    # Aggregated data (populated by market module)
    instruments: dict = field(default_factory=dict)  # code -> InstrumentSpec
    sessions: dict = field(default_factory=dict)     # name -> SessionWindow
    phases: dict = field(default_factory=dict)       # name -> SessionPhaseSpec

    @property
    def instrument_codes(self) -> List[str]:
        """List of all instrument codes for this market."""
        return list(self.instruments.keys())

    @property
    def all_sessions(self) -> List[SessionWindow]:
        """All session windows in chronological order."""
        return list(self.sessions.values())

    @property
    def trading_phases(self) -> List[SessionPhaseSpec]:
        """Only trading phases (excludes breaks)."""
        return [p for p in self.phases.values() if p.is_trading]
