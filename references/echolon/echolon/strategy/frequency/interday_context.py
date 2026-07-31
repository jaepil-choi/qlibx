"""
Interday Context
================

Frequency context for daily bar trading (interday).

FACTUAL infrastructure context for interday strategies:
- frequency_type: INTERDAY
- bar_size: DAILY
- bars_per_day: 1
- Never flattens for session close (positions held overnight)

DESIGN PRINCIPLE:
    Infrastructure provides FACTUAL DATA only.
    Strategy decides trade frequency, position sizing, etc.
"""

from typing import Optional

from .interface import (
    IFrequencyContext,
    FrequencyType,
    BarSize
)


class InterdayContext(IFrequencyContext):
    """
    Frequency context for daily bar trading.

    Provides FACTUAL infrastructure for:
    - Daily bar strategies
    - Swing trading
    - Position trading
    - Any strategy holding overnight

    No parameters - all values are fixed for daily bars.
    Trade limiting belongs in strategy parameters, not infrastructure.
    """

    def __init__(self):
        """Initialize interday context."""
        pass

    @property
    def frequency_type(self) -> FrequencyType:
        """Returns INTERDAY."""
        return FrequencyType.INTERDAY

    @property
    def bar_size(self) -> BarSize:
        """Returns DAILY."""
        return BarSize.DAILY

    @property
    def bars_per_day(self) -> int:
        """Returns 1 (one bar per day)."""
        return 1

    @property
    def flatten_at_close(self) -> bool:
        """
        Returns False - interday strategies don't flatten at session close.

        Positions are held overnight.
        """
        return False

    def should_flatten_for_close(
        self,
        bars_remaining: Optional[int] = None,  # noqa: ARG002
    ) -> bool:
        """
        Always returns False for interday strategies.

        Interday strategies hold positions overnight and don't
        need to flatten before day close.

        Args:
            bars_remaining: Ignored for interday strategies

        Returns:
            False
        """
        return False

    def __repr__(self) -> str:
        return f"InterdayContext(bar_size={self.bar_size.label})"
