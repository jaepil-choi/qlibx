"""
Intraday Context
================

Frequency context for intraday bar trading (15-min, 1-hour, etc.).

Infrastructure context for intraday strategies:
- frequency_type: INTRADAY
- bar_size: Configurable (MINUTE_15, HOUR_1, etc.)
- bars_per_day: Provided by caller (from TradingContext or market adapter)
- Session flattening: Can force exit before session close

Intraday strategies define their own parameters directly - no scaling is applied.
The strategy logic is designed specifically for intraday trading.

DESIGN PRINCIPLE:
    Infrastructure provides FACTUAL DATA only.
    bars_per_day comes from config/markets/ via TradingContext or engine_factory.
"""

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from .interface import (
    IFrequencyContext,
    FrequencyType,
    BarSize
)

if TYPE_CHECKING:
    from echolon.markets.interface import IMarketAdapter


class IntradayContext(IFrequencyContext):
    """
    Frequency context for intraday bar trading.

    Provides FACTUAL infrastructure for intraday strategies:
    - Bar size and bars per day
    - Session close timing
    - Bar/day conversions

    DESIGN PRINCIPLE:
        Infrastructure provides FACTUAL DATA only.
        bars_per_day should be provided by caller from TradingContext or
        calculated from market adapter sessions.

    Parameters:
        bar_size: Size of each bar (default: MINUTE_15)
        bars_per_day: Bars per trading day (required for accurate calculations)
        flatten_before_close: Flatten positions before close (default: True)
        flatten_bars_before_close: Bars before close to flatten (default: 2)
    """

    def __init__(
        self,
        bar_size: BarSize = BarSize.MINUTE_15,
        bars_per_day: int = 96,
        flatten_before_close: bool = True,
        flatten_bars_before_close: int = 2,
    ):
        """
        Initialize intraday context.

        Args:
            bar_size: Bar size enum
            bars_per_day: Bars per trading day (from TradingContext or market adapter)
            flatten_before_close: Whether to flatten at session close
            flatten_bars_before_close: How many bars before close to flatten
        """
        self._bar_size = bar_size
        self._flatten_before_close = flatten_before_close
        self._flatten_bars = flatten_bars_before_close
        self._bars_per_day = bars_per_day

    @property
    def frequency_type(self) -> FrequencyType:
        """Returns INTRADAY."""
        return FrequencyType.INTRADAY

    @property
    def bar_size(self) -> BarSize:
        """Returns configured bar size."""
        return self._bar_size

    @property
    def bars_per_day(self) -> int:
        """Returns bars per trading day."""
        return self._bars_per_day

    @property
    def flatten_at_close(self) -> bool:
        """Returns whether to flatten at session close."""
        return self._flatten_before_close

    def should_flatten_for_close(
        self,
        bars_remaining: Optional[int] = None,
    ) -> bool:
        """
        Check if near day close for position flattening.

        Returns True if:
        1. flatten_before_close is enabled
        2. We're within flatten_bars_before_close of day end

        Args:
            bars_remaining: Pre-computed bars remaining indicator (preferred).
                           This is the `bars_remaining` indicator which is
                           holiday-aware and accounts for actual bar counts.

        Returns:
            True if should flatten positions

        Note:
            Prefer using bars_remaining indicator as it is:
            - Holiday-aware (accounts for cancelled night sessions)
            - Bar-size agnostic (computed from actual data)
            - Pre-computed by indicator engine
        """
        if not self._flatten_before_close:
            return False

        # Preferred: Use pre-computed bars_remaining indicator
        return bars_remaining <= self._flatten_bars


    def bars_until_close(
        self,
        current_time: datetime,
        market_adapter: 'IMarketAdapter'
    ) -> int:
        """
        Calculate bars remaining until session close.

        Args:
            current_time: Current datetime
            market_adapter: Market adapter for session times

        Returns:
            Number of bars until close
        """
        session_close = market_adapter.get_session_close_time(current_time.date())
        time_until_close = session_close - current_time

        if time_until_close.total_seconds() <= 0:
            return 0

        bar_minutes = self._bar_size.minutes
        minutes_until_close = time_until_close.total_seconds() / 60
        return int(minutes_until_close / bar_minutes)

    def __repr__(self) -> str:
        return (
            f"IntradayContext("
            f"bar_size={self._bar_size.label}, "
            f"bars_per_day={self._bars_per_day}, "
            f"flatten_at_close={self._flatten_before_close})"
        )
