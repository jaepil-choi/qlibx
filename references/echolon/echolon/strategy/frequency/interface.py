"""
Frequency Context Interface
===========================

Abstract interface for trading frequency infrastructure.

Provides FACTUAL infrastructure context for strategies.
Strategies are designed separately for intraday vs interday - NO scaling is performed.

DESIGN PRINCIPLE:
    Infrastructure provides FACTUAL DATA only.
    Strategy decides trade frequency, position sizing, etc.

Enums:
- FrequencyType: INTERDAY or INTRADAY
- BarSize: MINUTE_1, MINUTE_5, MINUTE_15, MINUTE_30, HOUR_1, HOUR_4, DAILY, WEEKLY

Infrastructure methods (factual data only):
- should_flatten_for_close(time, adapter): Check if near session close (intraday)
- bars_per_day: Number of bars in trading day
- bar_size: Size of each bar

Note: Trade limiting (min_bars_between_trades, daily_trade_limit) belongs in
strategy parameters, NOT infrastructure.
"""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Optional


class FrequencyType(Enum):
    """Trading frequency type."""
    INTERDAY = "interday"  # Daily bars, hold overnight
    INTRADAY = "intraday"  # Sub-daily bars, may flatten at close


class BarSize(Enum):
    """Bar size enumeration with minute values."""
    MINUTE_1 = ("1min", 1)
    MINUTE_5 = ("5min", 5)
    MINUTE_15 = ("15min", 15)
    MINUTE_30 = ("30min", 30)
    HOUR_1 = ("1h", 60)
    HOUR_4 = ("4h", 240)
    DAILY = ("1d", 1440)  # 24 * 60
    WEEKLY = ("1w", 10080)  # 7 * 24 * 60

    def __init__(self, label: str, minutes: int):
        self._label = label
        self._minutes = minutes

    @property
    def label(self) -> str:
        """Human-readable label."""
        return self._label

    @property
    def minutes(self) -> int:
        """Bar size in minutes."""
        return self._minutes

    @classmethod
    def from_string(cls, value: str) -> 'BarSize':
        """Create BarSize from string label."""
        for bar_size in cls:
            if bar_size.label == value:
                return bar_size
        raise ValueError(f"Unknown bar size: {value}")

    @classmethod
    def from_minutes(cls, minutes: int) -> 'BarSize':
        """Create BarSize from minutes."""
        for bar_size in cls:
            if bar_size.minutes == minutes:
                return bar_size
        raise ValueError(f"Unknown bar size for {minutes} minutes")


class IFrequencyContext(ABC):
    """
    Abstract interface for trading frequency infrastructure.

    Provides infrastructure context for strategies. Strategies are designed
    separately for intraday vs interday with their own parameters.
    No parameter scaling is performed.
    """

    @property
    @abstractmethod
    def frequency_type(self) -> FrequencyType:
        """Whether this is interday or intraday trading."""
        pass

    @property
    @abstractmethod
    def bar_size(self) -> BarSize:
        """Size of each bar."""
        pass

    @property
    @abstractmethod
    def bars_per_day(self) -> int:
        """
        Number of bars in a typical trading day.

        For daily: 1
        For 15-min SHFE: ~23 (accounting for session breaks)
        For 1-hour crypto: 24
        """
        pass

    @property
    @abstractmethod
    def flatten_at_close(self) -> bool:
        """Whether positions should be flattened at session close."""
        pass

    @abstractmethod
    def should_flatten_for_close(
        self,
        bars_remaining: Optional[int] = None,
    ) -> bool:
        """
        Check if positions should be flattened for day close.

        For intraday strategies, this returns True when approaching
        day end (typically 1-2 bars before close).

        For interday strategies, always returns False.

        Args:
            bars_remaining: Pre-computed bars_remaining indicator value.
                           This is holiday-aware and bar-size agnostic.
                           For interday, this parameter is ignored.

        Returns:
            True if should flatten positions
        """
        pass

    def is_intraday(self) -> bool:
        """Check if this is an intraday frequency."""
        return self.frequency_type == FrequencyType.INTRADAY

    def is_interday(self) -> bool:
        """Check if this is an interday frequency."""
        return self.frequency_type == FrequencyType.INTERDAY

    def bars_to_days(self, bars: int) -> float:
        """Convert bars to equivalent days."""
        return bars / self.bars_per_day

    def days_to_bars(self, days: float) -> int:
        """Convert days to equivalent bars."""
        return int(days * self.bars_per_day)
