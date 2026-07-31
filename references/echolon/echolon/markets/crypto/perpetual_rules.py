"""
Perpetual Contract Rules
========================

Rules and utilities for cryptocurrency perpetual contracts.

Perpetual contract characteristics:
- No expiry date
- No delivery
- Funding mechanism anchors price to spot

Funding rate logic:
- Paid/received every 8 hours (00:00, 08:00, 16:00 UTC typical)
- Rate = (Perpetual Price - Spot Price) / Spot Price
- Positive rate: Longs pay shorts
- Negative rate: Shorts pay longs
- Typical range: -0.1% to +0.1% per 8 hours

Functions:
- get_next_funding_time(current_time): Next funding timestamp
- estimate_funding_payment(position_value, rate): Estimate payment
- is_near_funding(current_time, minutes_before): Check if near funding

Position management:
- No rollover needed (unlike futures)
- Consider funding costs for long holds
- High funding may signal overcrowded positions
"""

from datetime import datetime, time, timedelta
from typing import List, Tuple

# =============================================================================
# Funding Time Configuration
# =============================================================================

# Standard funding times (UTC)
# Most exchanges use 00:00, 08:00, 16:00 UTC
FUNDING_TIMES: List[time] = [
    time(0, 0),   # 00:00 UTC
    time(8, 0),   # 08:00 UTC
    time(16, 0),  # 16:00 UTC
]

# Funding interval in hours
FUNDING_INTERVAL_HOURS = 8


# =============================================================================
# Funding Time Functions
# =============================================================================

def get_funding_times() -> List[time]:
    """
    Get the standard funding times.

    Returns:
        List of funding times (UTC)
    """
    return FUNDING_TIMES.copy()


def get_next_funding_time(current_time: datetime) -> datetime:
    """
    Get the next funding time after current time.

    Args:
        current_time: Current datetime (UTC)

    Returns:
        Next funding datetime (UTC)
    """
    current_t = current_time.time()
    current_date = current_time.date()

    # Find next funding time today
    for funding_t in FUNDING_TIMES:
        if funding_t > current_t:
            return datetime.combine(current_date, funding_t)

    # No more funding times today - use first funding time tomorrow
    next_date = current_date + timedelta(days=1)
    return datetime.combine(next_date, FUNDING_TIMES[0])


def get_previous_funding_time(current_time: datetime) -> datetime:
    """
    Get the most recent funding time before current time.

    Args:
        current_time: Current datetime (UTC)

    Returns:
        Previous funding datetime (UTC)
    """
    current_t = current_time.time()
    current_date = current_time.date()

    # Find most recent funding time today
    for funding_t in reversed(FUNDING_TIMES):
        if funding_t <= current_t:
            return datetime.combine(current_date, funding_t)

    # No funding times today yet - use last funding time yesterday
    prev_date = current_date - timedelta(days=1)
    return datetime.combine(prev_date, FUNDING_TIMES[-1])


def is_near_funding(
    current_time: datetime,
    minutes_before: int = 15
) -> bool:
    """
    Check if current time is near a funding time.

    Useful for avoiding trades near funding when funding rate is high.

    Args:
        current_time: Current datetime (UTC)
        minutes_before: Minutes before funding to consider "near"

    Returns:
        True if within minutes_before of next funding
    """
    next_funding = get_next_funding_time(current_time)
    time_until_funding = (next_funding - current_time).total_seconds() / 60
    return 0 <= time_until_funding <= minutes_before


def minutes_until_funding(current_time: datetime) -> float:
    """
    Get minutes until next funding time.

    Args:
        current_time: Current datetime (UTC)

    Returns:
        Minutes until next funding
    """
    next_funding = get_next_funding_time(current_time)
    return (next_funding - current_time).total_seconds() / 60


# =============================================================================
# Funding Payment Calculations
# =============================================================================

def estimate_funding_payment(
    position_value: float,
    funding_rate: float,
    is_long: bool
) -> float:
    """
    Estimate funding payment for a position.

    Args:
        position_value: Absolute position value (in quote currency)
        funding_rate: Funding rate as decimal (e.g., 0.0001 = 0.01%)
        is_long: True if long position, False if short

    Returns:
        Payment amount (positive = pay, negative = receive)

    Examples:
        >>> # Long position with positive funding (longs pay)
        >>> estimate_funding_payment(10000, 0.0001, is_long=True)
        1.0  # Pay $1

        >>> # Short position with positive funding (shorts receive)
        >>> estimate_funding_payment(10000, 0.0001, is_long=False)
        -1.0  # Receive $1
    """
    payment = abs(position_value) * abs(funding_rate)

    if funding_rate >= 0:
        # Positive funding: longs pay, shorts receive
        return payment if is_long else -payment
    else:
        # Negative funding: shorts pay, longs receive
        return -payment if is_long else payment


def estimate_daily_funding_cost(
    position_value: float,
    avg_funding_rate: float,
    is_long: bool
) -> float:
    """
    Estimate daily funding cost based on average rate.

    Args:
        position_value: Position value
        avg_funding_rate: Average funding rate per 8 hours
        is_long: True if long position

    Returns:
        Estimated daily funding cost (positive = pay, negative = receive)
    """
    # 3 funding periods per day
    single_payment = estimate_funding_payment(
        position_value, avg_funding_rate, is_long
    )
    return single_payment * 3


def annualized_funding_rate(funding_rate_8h: float) -> float:
    """
    Convert 8-hour funding rate to annualized rate.

    Args:
        funding_rate_8h: 8-hour funding rate as decimal

    Returns:
        Annualized rate as decimal

    Examples:
        >>> annualized_funding_rate(0.0001)  # 0.01% per 8h
        0.10950  # ~10.95% APR
    """
    # 3 fundings per day * 365 days
    return funding_rate_8h * 3 * 365


# =============================================================================
# Funding Rate Validation
# =============================================================================

def is_extreme_funding(
    funding_rate: float,
    extreme_threshold: float = 0.001
) -> bool:
    """
    Check if funding rate is extreme.

    Extreme funding may indicate:
    - Overcrowded positions
    - High market volatility
    - Potential mean reversion opportunity

    Args:
        funding_rate: Funding rate as decimal
        extreme_threshold: Threshold to consider extreme (default 0.1%)

    Returns:
        True if funding rate exceeds threshold
    """
    return abs(funding_rate) >= extreme_threshold


def get_funding_bias(funding_rate: float) -> str:
    """
    Get the directional bias from funding rate.

    Args:
        funding_rate: Funding rate as decimal

    Returns:
        'bullish' (negative rate), 'bearish' (positive rate), or 'neutral'
    """
    if funding_rate > 0.0001:  # > 0.01%
        return "bearish"  # Market is long-biased, shorts are favored
    elif funding_rate < -0.0001:  # < -0.01%
        return "bullish"  # Market is short-biased, longs are favored
    return "neutral"
