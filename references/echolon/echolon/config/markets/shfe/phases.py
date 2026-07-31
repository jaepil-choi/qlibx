"""
SHFE Session Phase Configuration.

Two-tier session phase system based on bar size:

GRANULAR PHASES (for 5m, 15m bars):
- night (21:00-01:00): Consolidated night session
- morning (09:00-11:30): Price discovery + institutional flow
- morning_break (10:15-10:30): No trading
- lunch_break (11:30-13:30): No trading
- afternoon (13:30-15:00): Post-lunch + settlement

AGGREGATED PHASES (for 30m, 1h bars):
- night_session (21:00-01:00): Same as night, 8 bars at 30m, 4 bars at 1h
- day_session (09:00-15:00): Combines morning + afternoon, spans lunch break
                             7-8 bars at 30m, 5-6 bars at 1h

DESIGN PRINCIPLE:
    Phase = WHEN to trade (structural market condition)
    Bar Position = Fine-grained timing control (bar_of_session, bars_remaining)
    Bar Size = Determines which phase granularity to use

The old opening/closing sub-phases are replaced by time-based buffers:
    - Opening buffer: bar_of_session <= N (avoid gap reaction volatility)
    - Closing buffer: bars_remaining <= N (reserve exit window)

RESEARCH BASIS (for aggregated phases):
    Academic research on Chinese futures markets shows:
    1. First-half-hour return predicts last-half-hour return (intraday momentum)
    2. Cross-session holding is standard practice for larger bar sizes
    3. Lunch break gap is acceptable with proper risk management
"""

from datetime import time
from typing import Dict, List, Optional

from ..core.types import SessionPhaseSpec
from ..core.encoding import register_encoder, register_decoder


# =============================================================================
# Simplified Session Phase Definitions (5 phases)
# =============================================================================

PHASES: Dict[str, SessionPhaseSpec] = {
    # =========================================================================
    # Night session (21:00-01:00) - 4 hours, consolidated from 4 sub-phases
    # =========================================================================
    'night': SessionPhaseSpec(
        name='night',
        start=time(21, 0),
        end=time(1, 0),
        crosses_midnight=True,
        session_type='night',
        # 240 min = 48 bars at 5-min
        # Opening buffer: 30 min (avoid gap reaction after day close)
        # Closing buffer: 30 min (position management before overnight break)
    ),

    # =========================================================================
    # Day session phases (09:00-15:00) - consolidated
    # =========================================================================
    'morning': SessionPhaseSpec(
        name='morning',
        start=time(9, 0),
        end=time(11, 30),
        session_type='day',
        is_opening=True,  # Contains the day opening
        # Time span: 150 min, but ACTUAL TRADING: 135 min = 27 bars at 5-min
        # (morning_break 10:15-10:30 is embedded within this phase)
        # Use PHASE_TRADING_MINUTES['morning'] or get_phase_trading_bars() for bar counts
        # Opening buffer: 30 min (avoid overnight gap reaction)
        # No closing buffer (break follows)
    ),

    'morning_break': SessionPhaseSpec(
        name='morning_break',
        start=time(10, 15),
        end=time(10, 30),
        is_trading=False,
        session_type='day',
        # 15 min break - no trading
    ),

    'lunch_break': SessionPhaseSpec(
        name='lunch_break',
        start=time(11, 30),
        end=time(13, 30),
        is_trading=False,
        session_type='day',
        # 120 min break - no trading
    ),

    'afternoon': SessionPhaseSpec(
        name='afternoon',
        start=time(13, 30),
        end=time(15, 0),
        session_type='day',
        is_closing=True,  # Contains the day closing
        # 90 min = 18 bars at 5-min (merged afternoon + day_closing)
        # No opening buffer (after break, no gap)
        # Closing buffer: 15 min (settlement squaring)
    ),
}


# Trading phases only (excludes breaks)
TRADING_PHASES: List[SessionPhaseSpec] = [
    phase for phase in PHASES.values()
    if phase.is_trading
]

# List of tradeable phase names (for entry logic) - GRANULAR (5m, 15m)
TRADEABLE_PHASES: List[str] = ['night', 'morning', 'afternoon']


# =============================================================================
# Aggregated Session Phase Definitions (for 30m, 1h bars)
# =============================================================================
# For larger bar sizes, individual sessions don't have enough bars:
#   - afternoon: only 3 bars at 30m, 1-2 bars at 1h
#   - morning: only 4-5 bars at 30m, 2 bars at 1h
#
# Solution: Aggregate into larger logical sessions that provide sufficient bars.

PHASES_AGGREGATED: Dict[str, SessionPhaseSpec] = {
    # =========================================================================
    # Night session (21:00-01:00) - same as granular 'night'
    # =========================================================================
    'night_session': SessionPhaseSpec(
        name='night_session',
        start=time(21, 0),
        end=time(1, 0),
        crosses_midnight=True,
        session_type='night',
        is_opening=True,  # Contains night opening
        is_closing=True,  # Contains night closing
        # 240 min = 8 bars at 30m, 4 bars at 1h
        # Opening buffer: 30 min (gap reaction from day close)
        # Closing buffer: 30 min (position management before overnight)
    ),

    # =========================================================================
    # Day session (09:00-15:00) - aggregates morning + afternoon
    # =========================================================================
    'day_session': SessionPhaseSpec(
        name='day_session',
        start=time(9, 0),
        end=time(15, 0),
        crosses_midnight=False,
        session_type='day',
        is_opening=True,  # Contains day opening
        is_closing=True,  # Contains day closing (settlement)
        # Gross: 360 min, but actual trading: 225 min (135 morning + 90 afternoon)
        # Spans: morning (09:00-11:30) + lunch_break (11:30-13:30) + afternoon (13:30-15:00)
        # Bar counts: 7-8 bars at 30m, 5-6 bars at 1h
        # Opening buffer: 30 min (overnight gap reaction)
        # Closing buffer: 15 min (settlement squaring)
    ),
}

# Aggregated trading phases only
TRADING_PHASES_AGGREGATED: List[SessionPhaseSpec] = [
    phase for phase in PHASES_AGGREGATED.values()
]

# List of tradeable phase names - AGGREGATED (30m, 1h)
TRADEABLE_PHASES_AGGREGATED: List[str] = ['night_session', 'day_session']


# =============================================================================
# Timing Buffers (bar-size agnostic, in MINUTES)
# =============================================================================
# Convert to bars at runtime: buffer_bars = buffer_minutes // bar_size_minutes
#
# Buffer windows around session boundaries:
#   - night_opening (30 min) → night with opening buffer
#   - night_closing (30 min) → night with closing buffer
#   - day_opening (30 min) → morning with opening buffer
#   - day_closing (15 min) → afternoon with closing buffer

PHASE_BUFFERS_MINUTES: Dict[str, Dict[str, int]] = {
    # Granular phases (5m, 15m)
    'night': {
        'opening': 30,   # Avoid first 30 min (gap reaction after day close)
        'closing': 30,   # Reserve last 30 min (position management)
    },
    'morning': {
        'opening': 30,   # Avoid first 30 min (overnight gap reaction)
        'closing': 0,    # No closing buffer (morning_break follows)
    },
    'afternoon': {
        'opening': 0,    # No opening buffer (after lunch_break, no gap)
        'closing': 15,   # Reserve last 15 min (settlement squaring)
    },
    # Aggregated phases (30m, 1h)
    'night_session': {
        'opening': 30,   # Avoid first 30 min (gap reaction from day close)
        'closing': 30,   # Reserve last 30 min (position management before overnight)
    },
    'day_session': {
        'opening': 30,   # Avoid first 30 min (overnight gap reaction)
        'closing': 15,   # Reserve last 15 min (settlement squaring at 15:00)
    },
}


# =============================================================================
# Actual Trading Minutes per Phase (accounting for embedded breaks)
# =============================================================================
# IMPORTANT: The 'morning' phase (09:00-11:30) CONTAINS the morning_break
# (10:15-10:30), so actual trading time is 150 - 15 = 135 minutes.
#
# Use PHASE_TRADING_MINUTES for bar count calculations, NOT phase.duration_minutes.

PHASE_TRADING_MINUTES: Dict[str, int] = {
    # Granular phases (5m, 15m)
    'night': 240,       # 21:00-01:00, no breaks, 240 min
    'morning': 135,     # 09:00-11:30 minus morning_break (15 min) = 135 min
    'afternoon': 90,    # 13:30-15:00, no breaks, 90 min
    # Aggregated phases (30m, 1h)
    'night_session': 240,  # Same as night: 21:00-01:00, 240 min
    'day_session': 225,    # morning (135) + afternoon (90) = 225 min
                           # Lunch break is a gap WITHIN the session, not subtracted
}


def is_aggregated_bar_size(bar_size: str) -> bool:
    """
    Check if bar size should use aggregated phases.

    Args:
        bar_size: Bar size string ('5m', '15m', '30m', '1h', etc.)

    Returns:
        True if bar size should use aggregated phases (night_session, day_session)
        False if bar size should use granular phases (night, morning, afternoon)
    """
    if bar_size is None:
        return False
    bar_size_lower = bar_size.lower()
    # 30m and 1h use aggregated phases
    return bar_size_lower in ('30m', '30min', '1h', '60m', '60min')


def is_aggregated_bar_size_minutes(bar_size_minutes: int) -> bool:
    """
    Check if bar size (in minutes) should use aggregated phases.

    Args:
        bar_size_minutes: Bar size in minutes (e.g., 5, 15, 30, 60)

    Returns:
        True if bar size should use aggregated phases (night_session, day_session)
        False if bar size should use granular phases (night, morning, afternoon)
    """
    # 30m (30 minutes) and 1h (60 minutes) use aggregated phases
    return bar_size_minutes >= 30


def _normalize_phase_for_bar_size(phase: str, bar_size: Optional[str]) -> str:
    """
    Normalize phase name based on bar size.

    If bar_size indicates aggregated phases and a granular phase is given,
    converts to the corresponding aggregated phase.

    Args:
        phase: Phase name (granular or aggregated)
        bar_size: Optional bar size string. If None, returns phase unchanged.

    Returns:
        Normalized phase name appropriate for bar_size
    """
    if bar_size is None:
        return phase
    if is_aggregated_bar_size(bar_size) and phase in PHASE_GRANULAR_TO_AGGREGATED:
        return PHASE_GRANULAR_TO_AGGREGATED[phase]
    return phase


def get_phase_trading_bars(
    phase: str,
    bar_size_minutes: int,
    bar_size: Optional[str] = None
) -> int:
    """
    Get actual tradeable bar count for a phase.

    IMPORTANT: Use this instead of phase.duration_minutes // bar_size
    because 'morning' phase contains an embedded break (morning_break).

    Args:
        phase: Phase name ('night', 'morning', 'afternoon', 'night_session', 'day_session')
        bar_size_minutes: Bar size in minutes (5, 15, 30, 60)
        bar_size: Optional bar size string ('5m', '30m', etc.) for auto phase normalization.
                  If provided and is aggregated (30m/1h), granular phases are converted
                  to aggregated equivalents.

    Returns:
        Number of tradeable bars in this phase

    Example:
        >>> get_phase_trading_bars('morning', 5)
        27  # 135 min / 5 min = 27 bars (NOT 30!)
        >>> get_phase_trading_bars('night', 5)
        48  # 240 min / 5 min = 48 bars
        >>> get_phase_trading_bars('morning', 30, bar_size='30m')
        7  # Auto-converts to day_session: 225 min / 30 = 7 bars
    """
    # Normalize phase if bar_size indicates aggregated phases
    phase = _normalize_phase_for_bar_size(phase, bar_size)
    trading_minutes = PHASE_TRADING_MINUTES.get(phase, 0)
    return trading_minutes // bar_size_minutes


def get_phase_buffer_bars(
    phase: str,
    buffer_type: str,
    bar_size_minutes: int,
    bar_size: Optional[str] = None
) -> int:
    """
    Convert time-based buffer to bar count.

    Args:
        phase: Phase name ('night', 'morning', 'afternoon', 'night_session', 'day_session')
        buffer_type: Buffer type ('opening' or 'closing')
        bar_size_minutes: Bar size in minutes (5, 15, 30, 60)
        bar_size: Optional bar size string ('5m', '30m', etc.) for auto phase normalization.

    Returns:
        Number of bars to use as buffer (integer division)

    Example:
        >>> get_phase_buffer_bars('night', 'opening', 5)
        6  # 30 min / 5 min = 6 bars
        >>> get_phase_buffer_bars('night', 'opening', 15)
        2  # 30 min / 15 min = 2 bars
        >>> get_phase_buffer_bars('afternoon', 'closing', 30)
        0  # 15 min / 30 min = 0 bars (buffer < bar size)
    """
    # Normalize phase if bar_size indicates aggregated phases
    phase = _normalize_phase_for_bar_size(phase, bar_size)
    if phase not in PHASE_BUFFERS_MINUTES:
        return 0
    buffer_minutes = PHASE_BUFFERS_MINUTES[phase].get(buffer_type, 0)
    return buffer_minutes // bar_size_minutes


# =============================================================================
# Numeric Encoding (for Backtrader data feed lines)
# =============================================================================
# Simplified encoding: 1-5 instead of 1-11

# Granular phase encoding (5m, 15m)
PHASE_ENCODING: Dict[str, int] = {
    'night': 1,          # 21:00-01:00 (full night session)
    'morning': 2,        # 09:00-11:30 (before and after morning break)
    'morning_break': 3,  # 10:15-10:30 (no trading)
    'lunch_break': 4,    # 11:30-13:30 (no trading)
    'afternoon': 5,      # 13:30-15:00 (until day close)
}

# Reverse mapping: numeric -> string
PHASE_DECODING: Dict[int, str] = {v: k for k, v in PHASE_ENCODING.items()}

# Aggregated phase encoding (30m, 1h)
PHASE_ENCODING_AGGREGATED: Dict[str, int] = {
    'night_session': 1,  # 21:00-01:00 (same time as 'night')
    'day_session': 2,    # 09:00-15:00 (spans morning + lunch + afternoon)
    'overnight_gap': 0,  # 01:00-09:00 (between sessions)
}

PHASE_DECODING_AGGREGATED: Dict[int, str] = {
    v: k for k, v in PHASE_ENCODING_AGGREGATED.items()
}

# Mapping from granular to aggregated phases
PHASE_GRANULAR_TO_AGGREGATED: Dict[str, str] = {
    'night': 'night_session',
    'morning': 'day_session',
    'morning_break': 'day_session',  # Break is within day_session
    'lunch_break': 'day_session',    # Break is within day_session
    'afternoon': 'day_session',
}


# =============================================================================
# Encoding/Decoding Functions
# =============================================================================

def encode_phase(phase_str: str, bar_size: Optional[str] = None) -> int:
    """
    Convert session phase string to numeric encoding.

    Uses bar_size to determine which encoding to apply:
    - Granular (5m/15m or None): 'night'->1, 'morning'->2, etc.
    - Aggregated (30m/1h): 'night_session'->1, 'day_session'->2

    Args:
        phase_str: Session phase name
        bar_size: Bar size string ('5m', '30m', etc.) to select encoding

    Returns:
        Numeric encoding or 0 if unknown/None
    """
    if phase_str is None:
        return 0

    # Handle NaN
    if isinstance(phase_str, float) and phase_str != phase_str:
        return 0

    phase_lower = str(phase_str).lower().strip()

    # Select encoding based on bar_size
    if is_aggregated_bar_size(bar_size):
        return PHASE_ENCODING_AGGREGATED.get(phase_lower, 0)
    else:
        return PHASE_ENCODING.get(phase_lower, 0)


def decode_phase(phase_code: int, bar_size: Optional[str] = None) -> str:
    """
    Convert numeric session phase code to string.

    Uses bar_size to determine which decoding to apply:
    - Granular (5m/15m or None): 1->'night', 2->'morning', etc.
    - Aggregated (30m/1h): 1->'night_session', 2->'day_session'

    Args:
        phase_code: Numeric encoding
        bar_size: Bar size string ('5m', '30m', etc.) to select decoding

    Returns:
        Session phase name or 'unknown' if code not recognized
    """
    if phase_code is None:
        return 'unknown'

    # Handle NaN
    if isinstance(phase_code, float) and phase_code != phase_code:
        return 'unknown'

    # Select decoding based on bar_size
    if is_aggregated_bar_size(bar_size):
        return PHASE_DECODING_AGGREGATED.get(int(phase_code), 'unknown')
    else:
        return PHASE_DECODING.get(int(phase_code), 'unknown')


def get_phase_for_time(t: time, bar_size: Optional[str] = None) -> Optional[str]:
    """
    Get the phase name for a given time.

    Args:
        t: Time to check
        bar_size: Optional bar size string ('5m', '30m', etc.).
                  If aggregated (30m/1h), returns aggregated phase names.

    Returns:
        Phase name or None if outside trading hours.
        - For granular (5m/15m or None): 'night', 'morning', 'afternoon', 'morning_break', 'lunch_break'
        - For aggregated (30m/1h): 'night_session', 'day_session'

    Note:
        Morning phase spans the entire 09:00-11:30 window, even though
        morning_break (10:15-10:30) is a non-trading period within it.
        This is intentional - morning_break is a separate phase that
        takes precedence when checking for trading status.
    """
    # For aggregated bar sizes, use aggregated phases
    if bar_size is not None and is_aggregated_bar_size(bar_size):
        for name, phase in PHASES_AGGREGATED.items():
            if phase.contains_time(t):
                return name
        return None

    # For granular bar sizes (default behavior)
    # Check breaks first (they have higher priority within their parent phase)
    for name in ['morning_break', 'lunch_break']:
        if PHASES[name].contains_time(t):
            return name

    # Then check trading phases
    for name, phase in PHASES.items():
        if name in ['morning_break', 'lunch_break']:
            continue
        if phase.contains_time(t):
            return name

    return None


def is_trading_time(t: time) -> bool:
    """
    Check if time is during trading hours (not in a break).

    Args:
        t: Time to check

    Returns:
        True if during active trading, False otherwise
    """
    phase_name = get_phase_for_time(t)
    if phase_name is None:
        return False
    return PHASES[phase_name].is_trading


def is_within_buffer(
    phase: str,
    bar_of_session: int,
    bars_remaining: int,
    bar_size_minutes: int,
    bar_size: Optional[str] = None
) -> bool:
    """
    Check if current position is within opening or closing buffer.

    Args:
        phase: Current phase name (granular or aggregated)
        bar_of_session: Current bar number within session (1-indexed)
        bars_remaining: Bars remaining until session/phase end
        bar_size_minutes: Bar size in minutes
        bar_size: Optional bar size string for auto phase normalization

    Returns:
        True if within buffer zone (should avoid entry), False otherwise
    """
    opening_buffer = get_phase_buffer_bars(phase, 'opening', bar_size_minutes, bar_size)
    closing_buffer = get_phase_buffer_bars(phase, 'closing', bar_size_minutes, bar_size)

    if bar_of_session <= opening_buffer:
        return True
    if bars_remaining <= closing_buffer:
        return True

    return False


def get_tradeable_phases(bar_size: Optional[str] = None) -> List[str]:
    """
    Get list of tradeable phase names.

    Args:
        bar_size: Optional bar size string ('5m', '30m', etc.).
                  If aggregated (30m/1h), returns aggregated phases.

    Returns:
        List of tradeable phase names:
        - ['night', 'morning', 'afternoon'] for 5m, 15m (or None)
        - ['night_session', 'day_session'] for 30m, 1h
    """
    if bar_size is not None and is_aggregated_bar_size(bar_size):
        return TRADEABLE_PHASES_AGGREGATED
    return TRADEABLE_PHASES


def get_phases(bar_size: Optional[str] = None) -> Dict[str, SessionPhaseSpec]:
    """
    Get phase definitions.

    Args:
        bar_size: Optional bar size string ('5m', '30m', etc.).
                  If aggregated (30m/1h), returns aggregated phases.

    Returns:
        Dictionary of phase_name -> SessionPhaseSpec
    """
    if bar_size is not None and is_aggregated_bar_size(bar_size):
        return PHASES_AGGREGATED
    return PHASES


# =============================================================================
# Register with global encoding system
# =============================================================================

register_encoder('SHFE', encode_phase)
register_decoder('SHFE', decode_phase)


# =============================================================================
# Design Paradigm Helpers
# =============================================================================

def granular_to_aggregated_phase(granular_phase: str) -> str:
    """
    Convert a granular phase name to its aggregated equivalent.

    Args:
        granular_phase: Granular phase name ('night', 'morning', 'afternoon', etc.)

    Returns:
        Aggregated phase name ('night_session' or 'day_session')
    """
    return PHASE_GRANULAR_TO_AGGREGATED.get(granular_phase, granular_phase)


def get_design_paradigm_description(bar_size: Optional[str] = None) -> str:
    """
    Get a description of the design paradigm for a bar size.

    Args:
        bar_size: Bar size string

    Returns:
        Human-readable description of the design approach
    """
    if is_aggregated_bar_size(bar_size):
        return (
            "Aggregated session-based design: Uses night_session and day_session "
            "as primary filters. Day session spans morning + afternoon, holding "
            "through lunch break. Suitable for 30m and 1h bars."
        )
    return (
        "Granular session-based design: Uses night, morning, and afternoon "
        "as primary filters. Each session is traded independently. "
        "Suitable for 5m and 15m bars."
    )
