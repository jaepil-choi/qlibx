"""
Session Availability Builder
=============================

Data models and expected-bar computation for session availability.

This module provides:
- ``SessionDayInfo``: dataclass representing per-trading-date session info
  (loaded from session_availability.csv by SessionAvailabilityLoader)
- ``build_expected_bars``: computes expected bar counts per phase from SHFE
  phase configuration given a bar_size_minutes + optional bar_size string.

This logic is deliberately separated from the file-loading concern in
``echolon.data.loaders.session_availability_loader`` so that callers who only
need the expected-bar computation (without a CSV on disk) can import it
directly.

Related: ``echolon/data/transformers/shfe_session_analyzer.py`` — builds the
session_availability.csv from raw OHLCV data.
"""

from dataclasses import dataclass
from typing import Dict, Optional

from echolon.config.markets.shfe.phases import (
    get_phase_trading_bars,
    get_tradeable_phases,
    is_aggregated_bar_size,
)


@dataclass
class SessionDayInfo:
    """
    Session availability information for a single trading date.

    Supports both granular phases (night, morning, afternoon) and
    aggregated phases (night_session, day_session) depending on bar_size.

    Attributes:
        trading_date: Trading date in YYYYMMDD format
        phase_availability: Dict mapping phase_name -> bool (has session)
        phase_bars: Dict mapping phase_name -> int (bar count)
        total_bars: Total bars for the trading day
        tradeable_phases: List of phase names for this schema
    """
    trading_date: str
    phase_availability: Dict[str, bool]
    phase_bars: Dict[str, int]
    total_bars: int
    tradeable_phases: list

    # Convenience accessors for individual phases.
    @property
    def has_night(self) -> bool:
        """Whether night session exists (granular or aggregated)."""
        return self.phase_availability.get('night', False) or \
               self.phase_availability.get('night_session', False)

    @property
    def has_morning(self) -> bool:
        """Whether morning session exists (granular only)."""
        return self.phase_availability.get('morning', False)

    @property
    def has_afternoon(self) -> bool:
        """Whether afternoon session exists (granular only)."""
        return self.phase_availability.get('afternoon', False)

    @property
    def has_day_session(self) -> bool:
        """Whether day session exists (aggregated only)."""
        return self.phase_availability.get('day_session', False)

    @property
    def has_night_session(self) -> bool:
        """Whether night session exists (aggregated only)."""
        return self.phase_availability.get('night_session', False)

    @property
    def night_bars(self) -> int:
        """Bar count in night session (granular or aggregated)."""
        return self.phase_bars.get('night', 0) or \
               self.phase_bars.get('night_session', 0)

    @property
    def morning_bars(self) -> int:
        """Bar count in morning session (granular only)."""
        return self.phase_bars.get('morning', 0)

    @property
    def afternoon_bars(self) -> int:
        """Bar count in afternoon session (granular only)."""
        return self.phase_bars.get('afternoon', 0)

    @property
    def day_session_bars(self) -> int:
        """Bar count in day session (aggregated only)."""
        return self.phase_bars.get('day_session', 0)

    @property
    def night_session_bars(self) -> int:
        """Bar count in night session (aggregated only)."""
        return self.phase_bars.get('night_session', 0)

    @property
    def sessions_active(self) -> list:
        """Get list of active session names."""
        return [phase for phase in self.tradeable_phases
                if self.phase_availability.get(phase, False)]

    def get_session_bars(self, session_phase: str) -> int:
        """Get bar count for a specific session phase."""
        return self.phase_bars.get(session_phase, 0)

    def has_session(self, session_phase: str) -> bool:
        """Check if a specific session phase is available."""
        return self.phase_availability.get(session_phase, False)


def build_expected_bars(
    bar_size_minutes: int,
    bar_size: Optional[str] = None,
) -> Dict[str, int]:
    """
    Compute expected bar counts per trading phase from SHFE phase configuration.

    This is the "analysis" side of session availability — it derives expected
    counts purely from the bar_size and SHFE phase definitions, without reading
    any CSV file.

    Args:
        bar_size_minutes: Bar size in minutes (e.g. 5, 15, 30, 60).
        bar_size: Optional bar size string ('5m', '15m', '30m', '1h').
                  When '30m' or '1h', uses aggregated phases
                  (night_session, day_session) instead of granular.

    Returns:
        Dict mapping phase_name -> expected_bar_count for each tradeable phase.
    """
    tradeable_phases = get_tradeable_phases(bar_size)
    return {
        phase: get_phase_trading_bars(phase, bar_size_minutes, bar_size=bar_size)
        for phase in tradeable_phases
    }


__all__ = [
    'SessionDayInfo',
    'build_expected_bars',
]
