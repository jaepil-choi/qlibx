"""
Intraday Market Context for SHFE Trading
=========================================

Industry best practice for intraday futures trading uses a TWO-LAYER context system:

Layer 1: SESSION PHASE (Primary - Time-based, Deterministic)
------------------------------------------------------------
Controls WHEN to trade and base behavior. Simplified to 4 trading phases + 2 breaks:
- night (21:00-01:00): Full night session (European/Asian overlap)
  • Opening buffer: 30 min (avoid gap reaction)
  • Closing buffer: 30 min (position management)
- morning (09:00-11:30): Price discovery + institutional flow
  • Opening buffer: 30 min (overnight gap reaction)
  • No closing buffer (break follows)
- morning_break (10:15-10:30): No trading
- lunch_break (11:30-13:30): No trading
- afternoon (13:30-15:00): Post-lunch + settlement
  • No opening buffer (after break)
  • Closing buffer: 15 min (settlement squaring)

Use bar_of_session and bars_remaining for fine-grained timing control within phases.

Layer 2: VOLATILITY STATE (Secondary - ATR-based, Adaptive)
-----------------------------------------------------------
Controls HOW MUCH to risk (position sizing, stop distances):
- high (2): ATR > 75th percentile -> Smaller size, wider stops
- normal (1): ATR 25th-75th percentile -> Standard parameters
- low (0): ATR < 25th percentile -> Larger size, tighter stops

IMPORTANT: This is NOT a directional signal generator.
The context tells you WHICH STRATEGY to apply, not WHICH DIRECTION to trade.
Your entry/exit rules provide the alpha; context provides the filter.

NOTE: Trend-based regime classification (trending_up/down/ranging/volatile)
does NOT work for intraday trading due to mean-reversion dynamics.
"""

import pandas as pd
import numpy as np
import talib
from typing import Dict, Optional
import logging

from echolon.config.markets.shfe.phases import (
    get_phase_for_time as get_session_phase,
    get_tradeable_phases,
    is_aggregated_bar_size,
)
from echolon.indicators.calculators._utils import _require_columns

logger = logging.getLogger(__name__)


# =============================================================================
# Context Mappings
# =============================================================================

# Volatility state mappings (simple 3-level)
VOLATILITY_STATE_NUMERIC = {
    'high': 2,
    'normal': 1,
    'low': 0,
}

VOLATILITY_STATE_STRING = {
    2: 'high',
    1: 'normal',
    0: 'low',
}

# Session phase trading characteristics (supports both granular and aggregated phases)
# Opening/closing behavior is now controlled via bar_of_session/bars_remaining buffers
SESSION_CHARACTERISTICS = {
    # =========================================================================
    # Granular phases (for 5m, 15m bars)
    # =========================================================================
    'night': {
        'volatility_multiplier': 1.2,  # Average across night sub-phases
        'opening_volatility': 1.6,     # First 30 min higher vol (use bar_of_session <= buffer)
        'closing_volatility': 0.9,     # Last 30 min lower vol (use bars_remaining <= buffer)
        'typical_behavior': 'european_asian_overlap',
        'recommended_action': 'trend_following_with_timing_buffers',
        'is_night': True,
    },
    'morning': {
        'volatility_multiplier': 1.1,  # Average across morning sub-phases
        'opening_volatility': 1.5,     # First 30 min (overnight gap reaction)
        'typical_behavior': 'price_discovery_institutional_flow',
        'recommended_action': 'trend_following_with_opening_buffer',
        'is_night': False,
    },
    'morning_break': {
        'volatility_multiplier': 0.0,
        'typical_behavior': 'no_trading',
        'recommended_action': 'no_new_positions',
        'is_night': False,
    },
    'lunch_break': {
        'volatility_multiplier': 0.0,
        'typical_behavior': 'no_trading',
        'recommended_action': 'no_new_positions',
        'is_night': False,
    },
    'afternoon': {
        'volatility_multiplier': 1.0,  # Average across afternoon sub-phases
        'closing_volatility': 1.3,     # Last 15 min (settlement squaring)
        'typical_behavior': 'settlement_convergence',  # Check autocorrelation for actual pattern
        'recommended_action': 'exit_before_settlement_buffer',
        'is_night': False,
    },
    # =========================================================================
    # Aggregated phases (for 30m, 1h bars)
    # =========================================================================
    'night_session': {
        'volatility_multiplier': 1.2,  # Same as granular 'night'
        'opening_volatility': 1.6,     # First 30 min (1 bar at 30m)
        'closing_volatility': 0.9,     # Last 30 min (1 bar at 30m)
        'typical_behavior': 'european_asian_overlap',
        'recommended_action': 'trend_following_with_timing_buffers',
        'is_night': True,
    },
    'day_session': {
        'volatility_multiplier': 1.05,  # Average of morning (1.1) + afternoon (1.0)
        'opening_volatility': 1.5,      # First 30 min (overnight gap reaction)
        'closing_volatility': 1.3,      # Last 15 min (settlement squaring)
        'typical_behavior': 'price_discovery_to_settlement',
        'recommended_action': 'trend_following_with_buffers',
        'is_night': False,
    },
}


# =============================================================================
# Default Parameters
# =============================================================================

DEFAULT_VOLATILITY_PARAMS = {
    'atr_period': 14,
    'vol_lookback': 100,  # Bars for percentile calculation
    'high_percentile': 75.0,
    'low_percentile': 25.0,
}


# =============================================================================
# Layer 1: Session Phase Classification
# =============================================================================

def session_phase(
    df: pd.DataFrame,
    indicator_name: str = None,
    bar_size: str = None
) -> np.ndarray:
    """
    Classify each bar into a session phase based on timestamp.

    This is the PRIMARY context layer for intraday trading.
    Deterministic classification based purely on time.

    Phase names depend on bar_size:
    - For 5m/15m (or None): 'night', 'morning', 'afternoon' (granular)
    - For 30m/1h: 'night_session', 'day_session' (aggregated)

    Args:
        df: DataFrame with 'datetime' column
        indicator_name: Ignored, for processor compatibility
        bar_size: Optional bar size string ('5m', '15m', '30m', '1h').
                  Controls which phase names are returned.

    Returns:
        Numpy array with session phase strings
    """
    _require_columns(df, ['datetime'], calculator=__name__)

    # Extract time component since get_session_phase expects datetime.time, not Timestamp
    # Pass bar_size to get appropriate phase names (granular vs aggregated)
    return df['datetime'].apply(
        lambda dt: get_session_phase(dt.time(), bar_size=bar_size)
    ).values


def is_tradeable_phase(phase: str) -> bool:
    """
    Check if a session phase allows trading.

    Works with both granular and aggregated phase names.
    """
    # Non-tradeable phases (breaks only exist in granular)
    non_tradeable = {'morning_break', 'lunch_break', None}
    return phase not in non_tradeable


def is_night_phase(phase: str) -> bool:
    """
    Check if a session phase is a night session.

    Works with both granular ('night') and aggregated ('night_session') phases.
    """
    if phase in SESSION_CHARACTERISTICS:
        return SESSION_CHARACTERISTICS[phase].get('is_night', False)
    return phase in ('night', 'night_session')


def get_session_volatility_multiplier(phase: str) -> float:
    """Get the volatility multiplier for a session phase."""
    if phase in SESSION_CHARACTERISTICS:
        return SESSION_CHARACTERISTICS[phase]['volatility_multiplier']
    return 1.0


def get_session_recommended_action(phase: str) -> str:
    """Get the recommended trading action for a session phase."""
    if phase in SESSION_CHARACTERISTICS:
        return SESSION_CHARACTERISTICS[phase]['recommended_action']
    return 'standard'


# =============================================================================
# Layer 2: Volatility State Classification
# =============================================================================

def volatility_state(
    df: pd.DataFrame,
    atr_period: int = 14,
    vol_lookback: int = 100,
    high_percentile: float = 75.0,
    low_percentile: float = 25.0,
    indicator_name: str = None
) -> np.ndarray:
    """
    Classify volatility state using ATR percentile.

    This is the SECONDARY context layer for intraday trading.
    Controls position sizing and stop distances.

    States:
    - high (2): ATR > 75th percentile -> Smaller size, wider stops
    - normal (1): ATR 25th-75th percentile -> Standard parameters
    - low (0): ATR < 25th percentile -> Larger size, tighter stops

    Args:
        df: DataFrame with OHLC data
        atr_period: Period for ATR calculation
        vol_lookback: Lookback for percentile calculation
        high_percentile: Threshold for high volatility
        low_percentile: Threshold for low volatility
        indicator_name: Ignored, for processor compatibility

    Returns:
        Numpy array with volatility state (0=low, 1=normal, 2=high)
    """
    high = df['high'].values
    low = df['low'].values
    close = df['close'].values
    n = len(close)

    # Calculate ATR
    atr = talib.ATR(high, low, close, timeperiod=atr_period)

    # Normalize ATR as percentage of price
    natr = atr / close * 100

    # Calculate rolling percentile
    vol_percentile = _rolling_percentile(natr, vol_lookback)

    # Classify into 3 states
    state = np.ones(n, dtype=np.float64)  # Default: normal (1)

    high_vol_mask = vol_percentile > high_percentile
    low_vol_mask = vol_percentile < low_percentile

    state[high_vol_mask] = VOLATILITY_STATE_NUMERIC['high']
    state[low_vol_mask] = VOLATILITY_STATE_NUMERIC['low']

    # First bars are NaN until we have enough data
    warmup = max(atr_period, vol_lookback)
    state[:warmup] = np.nan

    return state


def _rolling_percentile(values: np.ndarray, lookback: int) -> np.ndarray:
    """Calculate rolling percentile rank."""
    n = len(values)
    result = np.full(n, 50.0, dtype=np.float64)

    for i in range(lookback, n):
        window = values[i - lookback:i]
        valid_window = window[~np.isnan(window)]

        if len(valid_window) > 0 and not np.isnan(values[i]):
            current = values[i]
            result[i] = np.sum(valid_window <= current) / len(valid_window) * 100

    return result


# =============================================================================
# Combined Context
# =============================================================================

def calculate_intraday_context(
    df: pd.DataFrame,
    atr_period: int = 14,
    vol_lookback: int = 100,
    high_percentile: float = 75.0,
    low_percentile: float = 25.0,
    indicator_name: str = None,
    bar_size: str = None,
) -> pd.DataFrame:
    """
    Calculate complete intraday context with both layers.

    Returns DataFrame with:
    - session_phase: Time-based session classification
    - is_tradeable: Whether phase allows trading
    - is_night: Whether current phase is a night session
    - volatility_state: ATR-based volatility level (0, 1, 2)
    - volatility_state_str: String name ('low', 'normal', 'high')
    - position_size_multiplier: Suggested position size multiplier

    Args:
        df: DataFrame with datetime and OHLCV columns
        atr_period: Period for ATR calculation
        vol_lookback: Lookback for volatility percentile
        high_percentile: Threshold for high volatility
        low_percentile: Threshold for low volatility
        indicator_name: For processor compatibility
        bar_size: Optional bar size string ('5m', '15m', '30m', '1h').
                  For 30m/1h, uses aggregated phases (night_session, day_session).

    Returns:
        DataFrame with context columns added
    """
    result = df.copy()

    # Layer 1: Session Phase (bar-size-aware)
    result['session_phase'] = session_phase(result, bar_size=bar_size)
    result['is_tradeable'] = result['session_phase'].apply(is_tradeable_phase)
    result['is_night'] = result['session_phase'].apply(is_night_phase)
    result['session_volatility_mult'] = result['session_phase'].apply(
        get_session_volatility_multiplier
    )
    result['recommended_action'] = result['session_phase'].apply(
        get_session_recommended_action
    )

    # Layer 2: Volatility State
    vol_state = volatility_state(
        result, atr_period, vol_lookback, high_percentile, low_percentile
    )
    result['volatility_state'] = vol_state
    result['volatility_state_str'] = pd.Series(vol_state).map(
        VOLATILITY_STATE_STRING
    ).fillna('normal').values

    # Combined volatility multiplier (session * ATR-based)
    atr_multiplier = np.where(
        vol_state == VOLATILITY_STATE_NUMERIC['high'], 0.7,  # Reduce size
        np.where(vol_state == VOLATILITY_STATE_NUMERIC['low'], 1.3, 1.0)
    )
    result['position_size_multiplier'] = (
        result['session_volatility_mult'] * atr_multiplier
    )

    return result


# =============================================================================
# Conversion Utilities
# =============================================================================

def convert_volatility_to_string(state_value) -> str:
    """Convert volatility state value to string."""
    if pd.isna(state_value):
        return 'unknown'

    if isinstance(state_value, (int, float, np.integer, np.floating)):
        return VOLATILITY_STATE_STRING.get(int(state_value), 'normal')

    if isinstance(state_value, str):
        if state_value in VOLATILITY_STATE_NUMERIC:
            return state_value
        return 'normal'

    return 'normal'


def convert_volatility_to_numeric(state_value) -> int:
    """Convert volatility state value to numeric."""
    if pd.isna(state_value):
        return 1  # Default: normal

    if isinstance(state_value, str):
        return VOLATILITY_STATE_NUMERIC.get(state_value, 1)

    return int(state_value) if not np.isnan(state_value) else 1
