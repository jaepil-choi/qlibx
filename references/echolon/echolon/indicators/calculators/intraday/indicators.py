"""
Intraday Session-Aware Indicators
=================================

Indicators specific to intraday trading:
- VWAP (Volume-Weighted Average Price)
- Session levels (high/low/close for night and day sessions)
- Opening range (high/low for first N minutes)
- Volume percentile (normalized for time-of-day)

These are pre-computed as Tier 2/3 indicators.
"""

import pandas as pd
import numpy as np
from datetime import datetime, time, timedelta
from typing import Optional
import logging

from .market_context import is_night_phase
from echolon.indicators.calculators._utils import _require_columns

logger = logging.getLogger(__name__)


# =============================================================================
# VWAP Calculation
# =============================================================================

def calculate_vwap(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate VWAP (Volume-Weighted Average Price) with session reset.

    VWAP resets at the start of each trading day (21:00 night session).
    Formula: VWAP = Cumulative(Price * Volume) / Cumulative(Volume)

    Args:
        df: DataFrame with datetime, close, volume, trading_date columns

    Returns:
        DataFrame with 'vwap' and 'vwap_distance_pct' columns added
    """
    result = df.copy()

    _require_columns(result, ['trading_date'], calculator=__name__)

    # Calculate typical price
    if 'high' in result.columns and 'low' in result.columns:
        result['typical_price'] = (result['high'] + result['low'] + result['close']) / 3
    else:
        result['typical_price'] = result['close']

    # Calculate price * volume
    result['pv'] = result['typical_price'] * result['volume']

    # Cumulative sums per trading day
    result['cum_pv'] = result.groupby('trading_date')['pv'].cumsum()
    result['cum_volume'] = result.groupby('trading_date')['volume'].cumsum()

    # Calculate VWAP
    result['vwap'] = result['cum_pv'] / result['cum_volume'].replace(0, np.nan)

    # Calculate distance from VWAP as percentage
    result['vwap_distance_pct'] = (result['close'] - result['vwap']) / result['vwap'] * 100

    # Cleanup temp columns
    result = result.drop(columns=['typical_price', 'pv', 'cum_pv', 'cum_volume'])

    return result


# =============================================================================
# Session Level Indicators
# =============================================================================

def calculate_session_levels(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate session high/low levels within current session.

    Adds:
    - session_high: Running high within current session
    - session_low: Running low within current session
    - session_position_pct: Where current price is within session range (0-100)

    Note: prev_session_close is calculated by calculate_previous_session_levels()

    Works with both granular phases (night, morning, afternoon) and
    aggregated phases (night_session, day_session).

    Args:
        df: DataFrame with datetime, OHLC, session_phase columns

    Returns:
        DataFrame with session level columns added
    """
    result = df.copy()

    _require_columns(result, ['session_phase'], calculator=__name__)

    # Group by trading_date and session type (night vs day)
    # Use is_night_phase() to handle both granular and aggregated phases
    result['is_night_session'] = result['session_phase'].apply(is_night_phase)

    # Create session groups
    result['session_group'] = (
        result['trading_date'].astype(str) + '_' +
        result['is_night_session'].astype(str)
    )

    # Running high/low within session
    result['session_high'] = result.groupby('session_group')['high'].cummax()
    result['session_low'] = result.groupby('session_group')['low'].cummin()

    # Session position (where is price within session range)
    session_range = result['session_high'] - result['session_low']
    result['session_position_pct'] = np.where(
        session_range > 0,
        (result['close'] - result['session_low']) / session_range * 100,
        50  # Default to middle if no range
    )

    # Cleanup
    result = result.drop(columns=['is_night_session', 'session_group'])

    return result


# =============================================================================
# Opening Range Indicators
# =============================================================================

def calculate_opening_range(
    df: pd.DataFrame,
    minutes: int = 30,
    bar_size_minutes: int = 5
) -> pd.DataFrame:
    """
    Calculate opening range (first N minutes) indicators.

    Uses bar position (``bar_of_session``) to identify opening-range bars,
    so it's bar-size agnostic.

    Works with both:
    - Granular phases: night, morning, afternoon (5m, 15m bars)
    - Aggregated phases: night_session, day_session (30m, 1h bars)

    Adds:
    - night_or_high: High of night opening range (first N bars of night/night_session)
    - night_or_low: Low of night opening range
    - day_or_high: High of day opening range (first N bars of morning/day_session)
    - day_or_low: Low of day opening range
    - or_breakout: 1 if above range, -1 if below, 0 if inside

    Args:
        df: DataFrame with datetime, OHLC, session_phase, bar_of_session columns
        minutes: Opening range duration in minutes (default 30)
        bar_size_minutes: Bar size in minutes for buffer calculation (default 5)

    Returns:
        DataFrame with opening range columns added
    """
    result = df.copy()

    # Calculate opening range buffer in bars
    opening_buffer_bars = minutes // bar_size_minutes  # e.g., 30 min / 5 min = 6 bars

    # Identify night vs day phases using is_night_phase (works with both granular/aggregated)
    result['_is_night'] = result['session_phase'].apply(is_night_phase)
    result['_is_day'] = ~result['_is_night'] & result['session_phase'].notna()

    # Night opening range: first N bars of night session
    # Using bar_of_session if available, otherwise fall back to position calculation
    if 'bar_of_session' in result.columns:
        night_opening = result['_is_night'] & (result['bar_of_session'] <= opening_buffer_bars)
    else:
        # Fallback: calculate bar position within night session
        night_mask = result['_is_night']
        result['_night_bar_pos'] = 0
        result.loc[night_mask, '_night_bar_pos'] = result[night_mask].groupby('trading_date').cumcount() + 1
        night_opening = night_mask & (result['_night_bar_pos'] <= opening_buffer_bars)

    result['night_or_high'] = result[night_opening].groupby('trading_date')['high'].transform('max')
    result['night_or_low'] = result[night_opening].groupby('trading_date')['low'].transform('min')

    # Forward fill to all bars of the day
    result['night_or_high'] = result.groupby('trading_date')['night_or_high'].ffill()
    result['night_or_low'] = result.groupby('trading_date')['night_or_low'].ffill()

    # Day opening range: first N bars of day session (morning for granular, day_session for aggregated)
    if 'bar_of_session' in result.columns:
        # For day session, bar_of_session resets at session start
        # We need to identify first N bars of day session specifically
        day_mask = result['_is_day']
        result['_day_bar_pos'] = 0
        result.loc[day_mask, '_day_bar_pos'] = result[day_mask].groupby('trading_date').cumcount() + 1
        day_opening = day_mask & (result['_day_bar_pos'] <= opening_buffer_bars)
    else:
        # Fallback: calculate bar position within day session
        day_mask = result['_is_day']
        result['_day_bar_pos'] = 0
        result.loc[day_mask, '_day_bar_pos'] = result[day_mask].groupby('trading_date').cumcount() + 1
        day_opening = day_mask & (result['_day_bar_pos'] <= opening_buffer_bars)

    result['day_or_high'] = result[day_opening].groupby('trading_date')['high'].transform('max')
    result['day_or_low'] = result[day_opening].groupby('trading_date')['low'].transform('min')

    # Forward fill
    result['day_or_high'] = result.groupby('trading_date')['day_or_high'].ffill()
    result['day_or_low'] = result.groupby('trading_date')['day_or_low'].ffill()

    # Opening range breakout signal
    # Use night OR for night session, day OR for day session
    is_night = result['_is_night']

    or_high = np.where(is_night, result['night_or_high'], result['day_or_high'])
    or_low = np.where(is_night, result['night_or_low'], result['day_or_low'])

    result['or_breakout'] = np.where(
        result['close'] > or_high, 1,
        np.where(result['close'] < or_low, -1, 0)
    )

    # Cleanup temporary columns
    temp_cols = ['_night_bar_pos', '_day_bar_pos', '_is_night', '_is_day']
    result = result.drop(columns=[c for c in temp_cols if c in result.columns])

    return result


# =============================================================================
# Volume Indicators
# =============================================================================

def calculate_volume_percentile(
    df: pd.DataFrame,
    lookback: int = None,
    bars_per_day: int = None
) -> pd.DataFrame:
    """
    Calculate volume percentile relative to recent history.

    This helps normalize volume for time-of-day effects.

    Args:
        df: DataFrame with volume column
        lookback: Lookback window in bars (default: bars_per_day)
        bars_per_day: Bars per trading day (used as default for lookback)

    Returns:
        DataFrame with 'volume_percentile' column added
    """
    # Use bars_per_day as default lookback if not specified
    if lookback is None:
        lookback = bars_per_day 
    result = df.copy()

    _require_columns(result, ['volume'], calculator=__name__)

    # Rolling percentile rank
    def percentile_rank(series):
        n = len(series)
        result = np.zeros(n)

        for i in range(lookback, n):
            window = series.iloc[i-lookback:i].values
            current = series.iloc[i]

            if not np.isnan(current):
                result[i] = np.sum(window <= current) / len(window) * 100

        return result

    result['volume_percentile'] = percentile_rank(result['volume'])

    # Also calculate volume relative to session average
    if 'session_phase' in result.columns:
        session_avg = result.groupby('session_phase')['volume'].transform('mean')
        result['volume_vs_session_avg'] = result['volume'] / session_avg.replace(0, np.nan)

    return result


# =============================================================================
# Time-based Indicators
# =============================================================================

def calculate_time_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate time-based features for intraday analysis.

    Adds:
    - hour_of_day: Hour (0-23)
    - minutes_since_session_start: Minutes since current session started
    - minutes_to_session_end: Minutes until current session ends
    - bar_of_day: Bar number within trading day (0-92 for 5-min bars)

    Args:
        df: DataFrame with datetime column

    Returns:
        DataFrame with time feature columns added
    """
    result = df.copy()

    _require_columns(result, ['datetime'], calculator=__name__)

    result['hour_of_day'] = result['datetime'].dt.hour
    result['minute_of_hour'] = result['datetime'].dt.minute

    # Bar of day (cumulative count per trading day)
    result['bar_of_day'] = result.groupby('trading_date').cumcount()

    # Minutes since trading day start (21:00)
    def minutes_since_day_start(dt):
        hour = dt.hour
        minute = dt.minute

        if hour >= 21:
            # Night session after 21:00
            return (hour - 21) * 60 + minute
        elif hour < 1:
            # Night session after midnight
            return (3 * 60) + hour * 60 + minute  # 3 hours from 21:00 to midnight
        elif hour == 1:
            return 4 * 60 + minute  # Night session ending
        else:
            # Day session - add night session duration (240 min) + gap
            # Simplified: just track from 09:00
            return 240 + (hour - 9) * 60 + minute

    result['minutes_since_day_start'] = result['datetime'].apply(minutes_since_day_start)

    return result


# =============================================================================
# Individual Indicator Wrappers (for indicator_mapping.py)
# =============================================================================

def vwap(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """VWAP indicator wrapper - returns vwap column only."""
    result = calculate_vwap(df)
    return result['vwap'].values


def vwap_distance_pct(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """VWAP distance percentage wrapper."""
    result = calculate_vwap(df)
    return result['vwap_distance_pct'].values


def session_high(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Session high wrapper."""
    result = calculate_session_levels(df)
    return result['session_high'].values


def session_low(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Session low wrapper."""
    result = calculate_session_levels(df)
    return result['session_low'].values


def session_position_pct(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Session position percentage wrapper."""
    result = calculate_session_levels(df)
    return result['session_position_pct'].values


def volume_percentile(
    df: pd.DataFrame,
    indicator_name: str = None,
    bars_per_day: int = None,
    **kwargs
) -> np.ndarray:
    """
    Volume percentile wrapper.

    Args:
        df: DataFrame with volume column
        indicator_name: Indicator name (unused)
        bars_per_day: Bars per trading day for lookback 
    """
    result = calculate_volume_percentile(df, bars_per_day=bars_per_day)
    return result['volume_percentile'].values


def volume_vs_session_avg(
    df: pd.DataFrame,
    indicator_name: str = None,
    bars_per_day: int = None,
    **kwargs
) -> np.ndarray:
    """Volume vs session average wrapper."""
    result = calculate_volume_percentile(df, bars_per_day=bars_per_day)
    if 'volume_vs_session_avg' in result.columns:
        return result['volume_vs_session_avg'].values
    return np.full(len(df), np.nan)


def night_or_high(
    df: pd.DataFrame,
    bar_size_minutes: int,
    indicator_name: str = None,
    **kwargs
) -> np.ndarray:
    """Night opening range high wrapper."""
    result = calculate_opening_range(df, bar_size_minutes=bar_size_minutes)
    return result['night_or_high'].values


def night_or_low(
    df: pd.DataFrame,
    bar_size_minutes: int,
    indicator_name: str = None,
    **kwargs
) -> np.ndarray:
    """Night opening range low wrapper."""
    result = calculate_opening_range(df, bar_size_minutes=bar_size_minutes)
    return result['night_or_low'].values


def day_or_high(
    df: pd.DataFrame,
    bar_size_minutes: int,
    indicator_name: str = None,
    **kwargs
) -> np.ndarray:
    """Day opening range high wrapper."""
    result = calculate_opening_range(df, bar_size_minutes=bar_size_minutes)
    return result['day_or_high'].values


def day_or_low(
    df: pd.DataFrame,
    bar_size_minutes: int,
    indicator_name: str = None,
    **kwargs
) -> np.ndarray:
    """Day opening range low wrapper."""
    result = calculate_opening_range(df, bar_size_minutes=bar_size_minutes)
    return result['day_or_low'].values


def or_breakout(
    df: pd.DataFrame,
    bar_size_minutes: int,
    indicator_name: str = None,
    **kwargs
) -> np.ndarray:
    """Opening range breakout signal wrapper."""
    result = calculate_opening_range(df, bar_size_minutes=bar_size_minutes)
    return result['or_breakout'].values


def bar_of_day(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Bar of day wrapper."""
    result = calculate_time_features(df)
    return result['bar_of_day'].values


def bars_remaining(
    df: pd.DataFrame,
    indicator_name: str = None,
    session_availability: 'SessionAvailabilityLoader' = None
) -> np.ndarray:
    """
    Calculate bars remaining in the trading day.

    Uses session availability data for accurate counts on days with
    irregular sessions (e.g., no night session after holidays).

    Args:
        df: DataFrame with datetime and trading_date columns
        indicator_name: Indicator name (unused, for API compatibility)
        session_availability: SessionAvailabilityLoader for expected bar counts

    Returns:
        Array of bars remaining until trading day ends
    """
    result = calculate_time_features(df)
    bar_of_day_values = result['bar_of_day'].values

    # Use expected bar counts per trading date (accounts for has_night)
    total_bars = df['trading_date'].apply(
        lambda td: session_availability.get_expected_total_bars(str(td))
    ).values
    return total_bars - bar_of_day_values - 1



def total_bars_today(
    df: pd.DataFrame,
    indicator_name: str = None,
    session_availability: 'SessionAvailabilityLoader' = None
) -> np.ndarray:
    """
    Get total bars for each trading day.

    Uses session availability data for accurate counts on irregular days.

    Args:
        df: DataFrame with trading_date column
        indicator_name: Indicator name (unused, for API compatibility)
        session_availability: SessionAvailabilityLoader for expected bar counts

    Returns:
        Array of total bars for each row's trading day
    """
    return df['trading_date'].apply(
        lambda td: session_availability.get_expected_total_bars(str(td))
    ).values


def has_night_session(
    df: pd.DataFrame,
    indicator_name: str = None,
    session_availability: 'SessionAvailabilityLoader' = None
) -> np.ndarray:
    """
    Check if each trading day has a night session.

    Args:
        df: DataFrame with trading_date column
        indicator_name: Indicator name (unused, for API compatibility)
        session_availability: Optional SessionAvailabilityLoader

    Returns:
        Boolean array (True if night session exists)
    """
    return df['trading_date'].apply(
        lambda td: session_availability.has_night_session(str(td))
    ).values


def bar_of_session(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """
    Calculate 0-indexed bar position within current session phase.

    Args:
        df: DataFrame with trading_date and session_phase columns

    Returns:
        Array of bar indices within session (0 = first bar of session)
    """

    # Create session group key (trading_date + session_phase)
    session_key = df['trading_date'].astype(str) + '_' + df['session_phase'].astype(str)

    # Cumcount within each session
    return df.groupby(session_key).cumcount().values


def bars_remaining_in_session(
    df: pd.DataFrame,
    indicator_name: str = None,
    session_availability: 'SessionAvailabilityLoader' = None,
) -> np.ndarray:
    """
    Calculate bars remaining in current session phase.

    Args:
        df: DataFrame with trading_date and session_phase columns
        indicator_name: Indicator name (unused, for API compatibility)
        session_availability: SessionAvailabilityLoader for expected bar counts

    Returns:
        Array of bars remaining in current session
    """
    # Get bar_of_session
    bar_pos = bar_of_session(df)

    # Get expected total bars for each session
    session_totals = df.apply(
        lambda row: session_availability.get_expected_session_bars(
            str(row['trading_date']),
            row['session_phase']
        ),
        axis=1
    ).values

    return session_totals - bar_pos - 1


def session_bars_total(
    df: pd.DataFrame,
    indicator_name: str = None,
    session_availability: 'SessionAvailabilityLoader' = None,
) -> np.ndarray:
    """
    Get total bars for the current session phase.

    Args:
        df: DataFrame with trading_date and session_phase columns
        indicator_name: Indicator name (unused, for API compatibility)
        session_availability: SessionAvailabilityLoader for expected bar counts

    Returns:
        Array of total bars for each row's session
    """
    return df.apply(
        lambda row: session_availability.get_expected_session_bars(
            str(row['trading_date']),
            row['session_phase']
        ),
        axis=1
    ).values


# =============================================================================
# Normalization Indicators (Tier 2 - High IC Potential)
# =============================================================================

def _calculate_bbands(df: pd.DataFrame, period: int = 20, nbdev: float = 2.0):
    """
    Calculate Bollinger Bands internally.

    Returns:
        Tuple of (upper, middle, lower) arrays
    """
    try:
        import talib
        upper, middle, lower = talib.BBANDS(
            df['close'].values,
            timeperiod=period,
            nbdevup=nbdev,
            nbdevdn=nbdev,
            matype=0
        )
        return upper, middle, lower
    except ImportError:
        # Fallback without talib
        close = df['close']
        middle = close.rolling(window=period).mean()
        std = close.rolling(window=period).std()
        upper = middle + nbdev * std
        lower = middle - nbdev * std
        return upper.values, middle.values, lower.values


def bbands_pct_b(df: pd.DataFrame, period: int = 20, indicator_name: str = None, **kwargs) -> np.ndarray:
    """
    Bollinger %B - position within Bollinger Bands (0-1 scale).

    Formula: %B = (close - lower) / (upper - lower)

    Interpretation:
    - %B < 0: Price below lower band (oversold)
    - %B = 0: Price at lower band
    - %B = 0.5: Price at middle band
    - %B = 1: Price at upper band
    - %B > 1: Price above upper band (overbought)

    Args:
        df: DataFrame with close column
        period: Bollinger Band period (default 20)

    Returns:
        Array of %B values
    """
    # Calculate BBands internally (self-sufficient)
    upper, middle, lower = _calculate_bbands(df, period=period)

    band_width = upper - lower
    pct_b = np.where(
        band_width > 0,
        (df['close'].values - lower) / band_width,
        0.5  # Default to middle if bands collapsed
    )
    return pct_b


def bbands_bandwidth(df: pd.DataFrame, period: int = 20, indicator_name: str = None, **kwargs) -> np.ndarray:
    """
    Bollinger Bandwidth - band width as percentage of middle band.

    Formula: Bandwidth = (upper - lower) / middle × 100

    Use case: Volatility squeeze detection
    - Low bandwidth indicates consolidation (potential breakout)
    - High bandwidth indicates high volatility

    Args:
        df: DataFrame with close column
        period: Bollinger Band period (default 20)

    Returns:
        Array of bandwidth percentages
    """
    # Calculate BBands internally (self-sufficient)
    upper, middle, lower = _calculate_bbands(df, period=period)

    bandwidth = np.where(
        middle > 0,
        (upper - lower) / middle * 100,
        0
    )
    return bandwidth


def price_zscore(df: pd.DataFrame, period: int = 20, indicator_name: str = None, **kwargs) -> np.ndarray:
    """
    Z-score of price vs moving average.

    Formula: Z = (close - SMA) / stddev

    Interpretation:
    - Z < -2: Price significantly below mean (oversold)
    - Z > +2: Price significantly above mean (overbought)
    - |Z| < 1: Price within normal range

    Args:
        df: DataFrame with close column
        period: Lookback period for SMA and stddev (default 20)

    Returns:
        Array of Z-score values
    """
    close = df['close']
    sma = close.rolling(window=period).mean()
    std = close.rolling(window=period).std()

    zscore = np.where(
        std > 0,
        (close - sma) / std,
        0
    )
    return zscore


def vwap_zscore(df: pd.DataFrame, indicator_name: str = None, **kwargs) -> np.ndarray:
    """
    Z-score of price vs VWAP (standard deviations from VWAP).

    Calculates rolling standard deviation of price within each trading day,
    then computes how many standard deviations price is from VWAP.

    Interpretation:
    - Z < -2: Price significantly below VWAP (institutional selling pressure)
    - Z > +2: Price significantly above VWAP (institutional buying pressure)

    Returns:
        Array of VWAP Z-score values
    """
    result = df.copy()

    # Calculate VWAP if not present
    if 'vwap' not in result.columns:
        result = calculate_vwap(result)

    # Calculate rolling standard deviation within each trading day
    result['price_std'] = result.groupby('trading_date')['close'].transform(
        lambda x: x.expanding().std()
    )

    # Calculate Z-score
    zscore = np.where(
        result['price_std'] > 0,
        (result['close'] - result['vwap']) / result['price_std'],
        0
    )
    return zscore


# =============================================================================
# Keltner Channel Indicators
# =============================================================================

def calculate_keltner_channels(
    df: pd.DataFrame,
    ema_period: int = 20,
    atr_period: int = 20,
    multiplier: float = 2.0
) -> pd.DataFrame:
    """
    Calculate Keltner Channels (ATR-based bands).

    Keltner Channels use ATR instead of standard deviation (like Bollinger),
    making them more robust in trending markets.

    Args:
        df: DataFrame with high, low, close columns
        ema_period: EMA period for middle line
        atr_period: ATR period for band width
        multiplier: ATR multiplier for bands

    Returns:
        DataFrame with kc_upper, kc_lower, kc_middle columns added
    """
    result = df.copy()

    # Middle line: EMA of close
    result['kc_middle'] = result['close'].ewm(span=ema_period, adjust=False).mean()

    # ATR for band width
    high_low = result['high'] - result['low']
    high_close = np.abs(result['high'] - result['close'].shift())
    low_close = np.abs(result['low'] - result['close'].shift())

    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    atr = tr.rolling(window=atr_period).mean()

    # Keltner bands
    result['kc_upper'] = result['kc_middle'] + multiplier * atr
    result['kc_lower'] = result['kc_middle'] - multiplier * atr

    return result


def kc_upper(df: pd.DataFrame, indicator_name: str = None, **kwargs) -> np.ndarray:
    """Keltner Channel upper band wrapper."""
    result = calculate_keltner_channels(df)
    return result['kc_upper'].values


def kc_lower(df: pd.DataFrame, indicator_name: str = None, **kwargs) -> np.ndarray:
    """Keltner Channel lower band wrapper."""
    result = calculate_keltner_channels(df)
    return result['kc_lower'].values


def kc_pct_b(df: pd.DataFrame, indicator_name: str = None, **kwargs) -> np.ndarray:
    """
    Keltner %B - position within Keltner Channels (0-1 scale).

    Similar to Bollinger %B but uses ATR-based bands.

    Returns:
        Array of Keltner %B values
    """
    result = calculate_keltner_channels(df)

    band_width = result['kc_upper'] - result['kc_lower']
    pct_b = np.where(
        band_width > 0,
        (df['close'] - result['kc_lower']) / band_width,
        0.5
    )
    return pct_b


# =============================================================================
# Previous Session Indicators
# =============================================================================

def calculate_previous_session_levels(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate previous session high/low/close levels.

    These are key reference levels for intraday trading.

    Returns:
        DataFrame with prev_session_high, prev_session_low, prev_session_close columns
    """
    result = df.copy()

    _require_columns(result, ['trading_date'], calculator=__name__)

    # Group by trading_date to get session highs/lows
    session_stats = result.groupby('trading_date').agg({
        'high': 'max',
        'low': 'min',
        'close': 'last'
    }).reset_index()

    # Shift to get previous session values
    session_stats['prev_session_high'] = session_stats['high'].shift(1)
    session_stats['prev_session_low'] = session_stats['low'].shift(1)
    session_stats['prev_session_close'] = session_stats['close'].shift(1)

    # Merge back to original dataframe
    result = result.merge(
        session_stats[['trading_date', 'prev_session_high', 'prev_session_low', 'prev_session_close']],
        on='trading_date',
        how='left',
        suffixes=('', '_prev')
    )

    return result


def prev_session_high(df: pd.DataFrame, indicator_name: str = None, **kwargs) -> np.ndarray:
    """Previous session high wrapper."""
    result = calculate_previous_session_levels(df)
    return result['prev_session_high'].values


def prev_session_low(df: pd.DataFrame, indicator_name: str = None, **kwargs) -> np.ndarray:
    """Previous session low wrapper."""
    result = calculate_previous_session_levels(df)
    return result['prev_session_low'].values


def prev_session_close(df: pd.DataFrame, indicator_name: str = None, **kwargs) -> np.ndarray:
    """Previous session close wrapper."""
    result = calculate_previous_session_levels(df)
    return result['prev_session_close'].values


def gap_pct(df: pd.DataFrame, indicator_name: str = None, **kwargs) -> np.ndarray:
    """
    Gap percentage from previous session close.

    Formula: gap_pct = (open - prev_close) / prev_close × 100

    Use case: Gap fade/continuation signals
    - Large gaps often mean-revert (fade)
    - Small gaps may continue (trend)

    Returns:
        Array of gap percentages
    """
    result = calculate_previous_session_levels(df)

    # Get first open of each session
    first_opens = df.groupby('trading_date')['open'].first()
    result = result.merge(
        first_opens.rename('session_open'),
        left_on='trading_date',
        right_index=True,
        how='left'
    )

    gap = np.where(
        result['prev_session_close'] > 0,
        (result['session_open'] - result['prev_session_close']) / result['prev_session_close'] * 100,
        0
    )
    return gap


# =============================================================================
# Pivot Point Indicators
# =============================================================================

def calculate_pivot_points(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate daily pivot points from previous session's high/low/close.

    Standard pivot point formulas:
    - Pivot = (H + L + C) / 3
    - R1 = 2 × Pivot - L
    - S1 = 2 × Pivot - H

    Returns:
        DataFrame with pivot, pivot_r1, pivot_s1, pivot_distance_pct columns
    """
    result = df.copy()

    # Get previous session levels
    result = calculate_previous_session_levels(result)

    # Calculate pivot points
    result['pivot'] = (
        result['prev_session_high'] +
        result['prev_session_low'] +
        result['prev_session_close']
    ) / 3

    result['pivot_r1'] = 2 * result['pivot'] - result['prev_session_low']
    result['pivot_s1'] = 2 * result['pivot'] - result['prev_session_high']

    # Distance from pivot as percentage
    result['pivot_distance_pct'] = np.where(
        result['pivot'] > 0,
        (result['close'] - result['pivot']) / result['pivot'] * 100,
        0
    )

    return result


def pivot(df: pd.DataFrame, indicator_name: str = None, **kwargs) -> np.ndarray:
    """Pivot point wrapper."""
    result = calculate_pivot_points(df)
    return result['pivot'].values


def pivot_r1(df: pd.DataFrame, indicator_name: str = None, **kwargs) -> np.ndarray:
    """Pivot R1 (first resistance) wrapper."""
    result = calculate_pivot_points(df)
    return result['pivot_r1'].values


def pivot_s1(df: pd.DataFrame, indicator_name: str = None, **kwargs) -> np.ndarray:
    """Pivot S1 (first support) wrapper."""
    result = calculate_pivot_points(df)
    return result['pivot_s1'].values


def pivot_distance_pct(df: pd.DataFrame, indicator_name: str = None, **kwargs) -> np.ndarray:
    """Pivot distance percentage wrapper."""
    result = calculate_pivot_points(df)
    return result['pivot_distance_pct'].values


# =============================================================================
# Chaikin Money Flow (CMF)
# =============================================================================

def cmf(df: pd.DataFrame, period: int = 20, indicator_name: str = None, **kwargs) -> np.ndarray:
    """
    Chaikin Money Flow - volume-weighted accumulation/distribution.

    Formula:
    1. Money Flow Multiplier = ((close - low) - (high - close)) / (high - low)
    2. Money Flow Volume = MFM × volume
    3. CMF = SUM(MFV, period) / SUM(volume, period)

    Interpretation:
    - CMF > 0: Buying pressure (accumulation)
    - CMF < 0: Selling pressure (distribution)
    - CMF > 0.25: Strong buying
    - CMF < -0.25: Strong selling

    Args:
        df: DataFrame with high, low, close, volume columns
        period: Lookback period (default 20)

    Returns:
        Array of CMF values (-1 to +1 range)
    """
    high_low = df['high'] - df['low']

    # Money Flow Multiplier
    mfm = np.where(
        high_low > 0,
        ((df['close'] - df['low']) - (df['high'] - df['close'])) / high_low,
        0
    )

    # Money Flow Volume
    mfv = mfm * df['volume']

    # CMF = rolling sum of MFV / rolling sum of volume
    mfv_sum = pd.Series(mfv).rolling(window=period).sum()
    vol_sum = df['volume'].rolling(window=period).sum()

    cmf_values = np.where(
        vol_sum > 0,
        mfv_sum / vol_sum,
        0
    )

    return cmf_values


# =============================================================================
# Entry Point
# =============================================================================

if __name__ == "__main__":
    # Test with sample data
    import pandas as pd
    import numpy as np

    # Create sample intraday data
    n = 100
    np.random.seed(42)

    dates = pd.date_range('2024-01-02 21:00', periods=n, freq='5min')
    close = 20000 + np.cumsum(np.random.randn(n) * 10)
    high = close + np.abs(np.random.randn(n) * 5)
    low = close - np.abs(np.random.randn(n) * 5)
    volume = np.abs(np.random.randn(n) * 1000) + 500

    df = pd.DataFrame({
        'datetime': dates,
        'open': close + np.random.randn(n) * 3,
        'high': high,
        'low': low,
        'close': close,
        'volume': volume,
        'trading_date': dates.date,
        'session_phase': 'night_core',  # Simplified for test
    })

    # Calculate indicators
    df = calculate_vwap(df)
    df = calculate_volume_percentile(df)
    df = calculate_time_features(df)

    print("Sample output:")
    print(df[['datetime', 'close', 'vwap', 'vwap_distance_pct', 'volume_percentile']].head(20))


def hour_of_day(df: pd.DataFrame, indicator_name: str = None, **kwargs) -> np.ndarray:
    """
    Extract hour of day from datetime.
    
    Returns:
        np.ndarray: Hour (0-23)
    """
    return df['datetime'].dt.hour.values


def minute_of_hour(df: pd.DataFrame, indicator_name: str = None, **kwargs) -> np.ndarray:
    """
    Extract minute of hour from datetime.
    
    Returns:
        np.ndarray: Minute (0-59)
    """
    return df['datetime'].dt.minute.values
