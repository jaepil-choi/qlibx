"""
Trading Context - Runtime context for market-specific trading operations.

TradingContext encapsulates all market, instrument, and frequency information
needed by trading modules. Build it with :class:`MarketFactory.create` and
pass to modules via dependency injection.

Usage:
    from echolon.config.markets.factory import MarketFactory

    ctx = MarketFactory.create(
        market='SHFE', instrument='al', frequency='interday', bar_size='1d',
    )

    commission = ctx.instrument.calculate_commission(price, size)
    phase = ctx.encode_phase("morning")
    bars = ctx.bars_per_day
"""

from dataclasses import dataclass, field
from datetime import time, datetime
from typing import Dict, List, Callable

# Import types at runtime (required for Pydantic models that use TradingContext)
from .types import MarketConfig, InstrumentSpec, SessionWindow, SessionPhaseSpec


@dataclass
class TradingContext:
    """
    Runtime trading context for a specific market/instrument/frequency combination.

    This is the primary interface for modules to access market configuration.
    Created by MarketFactory and passed to modules that need market info.

    Attributes:
        market: Market configuration (SHFE, CRYPTO, etc.)
        instrument: Instrument specification (al, btc, etc.)
        frequency: Trading frequency ('intraday' or 'interday')
        bar_size: Bar size string ('5m', '15m', '1d', etc.)
        initial_capital: Starting capital for backtesting and live trading.
    """
    market: MarketConfig
    instrument: InstrumentSpec
    frequency: str  # 'intraday' | 'interday'
    bar_size: str   # '1m', '5m', '15m', '30m', '1h', '1d'

    # Starting capital for backtests (and as the live-deploy capital base).
    initial_capital: float = 200000.0

    # Encoding functions (set by factory based on market)
    _encode_phase: Callable[[str], int] = field(default=lambda x: 0, repr=False)
    _decode_phase: Callable[[int], str] = field(default=lambda x: 'unknown', repr=False)

    # =========================================================================
    # Market Properties
    # =========================================================================

    @property
    def market_code(self) -> str:
        """Market code (e.g., 'SHFE', 'CRYPTO')."""
        return self.market.code

    @property
    def timezone(self) -> str:
        """Market timezone (e.g., 'Asia/Shanghai', 'UTC')."""
        return self.market.timezone

    @property
    def has_contract_expiry(self) -> bool:
        """Whether contracts expire (futures vs perpetuals)."""
        return self.market.has_contract_expiry

    # =========================================================================
    # Instrument Properties
    # =========================================================================

    @property
    def instrument_code(self) -> str:
        """Instrument code (e.g., 'al', 'btc')."""
        return self.instrument.code

    @property
    def instrument_name(self) -> str:
        """Instrument name (e.g., 'Aluminum', 'Bitcoin Perpetual')."""
        return self.instrument.name

    @property
    def multiplier(self) -> float:
        """Contract multiplier."""
        return self.instrument.multiplier

    @property
    def margin_rate(self) -> float:
        """Margin requirement (decimal, e.g., 0.08 = 8%)."""
        return self.instrument.margin_rate

    @property
    def has_night_session(self) -> bool:
        """Whether instrument trades in night session."""
        return self.instrument.has_night_session

    # =========================================================================
    # Session Access
    # =========================================================================

    @property
    def phases(self) -> Dict[str, SessionPhaseSpec]:
        """All session phases for this market."""
        return self.market.phases

    @property
    def trading_phases(self) -> List[SessionPhaseSpec]:
        """Only trading phases (excludes breaks)."""
        return [p for p in self.market.phases.values() if p.is_trading]

    # =========================================================================
    # Frequency Properties
    # =========================================================================

    @property
    def is_intraday(self) -> bool:
        """Whether trading intraday."""
        return self.frequency == 'intraday'

    @property
    def is_interday(self) -> bool:
        """Whether trading interday (daily bars)."""
        return self.frequency == 'interday'

    @property
    def bars_per_day(self) -> int:
        """Expected bars per trading day."""
        if self.is_interday:
            return 1

        # Get from market-specific constants
        if self.market_code == 'SHFE':
            from echolon.config.markets.shfe.constants import BARS_PER_DAY, BARS_PER_DAY_NO_NIGHT
            bars_map = BARS_PER_DAY if self.has_night_session else BARS_PER_DAY_NO_NIGHT
            return bars_map.get(self.bar_size)
        elif self.market_code == 'CRYPTO':
            from echolon.config.markets.crypto.perpetuals import BARS_PER_DAY
            return BARS_PER_DAY.get(self.bar_size, 288)

        return 1  # Default for unknown markets

    # =========================================================================
    # Frequency-Derived Parameters (for Indicators)
    # =========================================================================

    @property
    def bar_size_minutes(self) -> int:
        """
        Bar size in minutes.

        Parses bar_size string ('1m', '5m', '15m', '30m', '1h', '4h', '1d')
        and returns the duration in minutes.
        """
        bar_size_lower = self.bar_size.lower()

        # Handle hour format
        if 'h' in bar_size_lower:
            hours = int(bar_size_lower.replace('h', ''))
            return hours * 60

        # Handle minute formats (both "5m" and "5min")
        if 'min' in bar_size_lower:
            return int(bar_size_lower.replace('min', ''))
        if 'm' in bar_size_lower:
            return int(bar_size_lower.replace('m', ''))

        # Handle day format
        if 'd' in bar_size_lower:
            return 1440  # 24 * 60

    @property
    def bars_per_hour(self) -> int:
        """Bars contained in one hour at current frequency (minimum 1)."""
        return max(1, 60 // self.bar_size_minutes)

    def hours_to_bars(self, hours: float) -> int:
        """
        Convert hours to bar count for current frequency.

        Args:
            hours: Duration in hours

        Returns:
            Number of bars (minimum 1)
        """
        return max(1, int(hours * self.bars_per_hour))

    def minutes_to_bars(self, minutes: int) -> int:
        """
        Convert minutes to bar count for current frequency.

        Args:
            minutes: Duration in minutes

        Returns:
            Number of bars (minimum 1)
        """
        return max(1, minutes // self.bar_size_minutes)

    def get_indicator_params(self) -> dict:
        """
        Get frequency-appropriate indicator parameters.

        For INTERDAY (daily bars): Returns standard TA-Lib defaults
        For INTRADAY: Returns time-scaled parameters based on bar_size

        Returns:
            Dictionary of indicator parameters appropriate for current frequency
        """
        # INTERDAY: Use standard TA-Lib defaults (industry standard for daily bars)
        if self.is_interday:
            return {
                # Momentum indicators (standard daily defaults)
                "rsi_period": 14,
                "cci_period": 20,
                "willr_period": 14,
                "mfi_period": 14,
                "mom_period": 10,

                # Trend indicators
                "adx_period": 14,
                "aroonosc_period": 25,

                # Volatility
                "atr_period": 14,

                # Moving averages
                "ema_fast": 12,
                "ema_slow": 26,
                "sma_short": 20,
                "sma_mid": 50,

                # MACD (standard 12/26/9)
                "macd_fast": 12,
                "macd_slow": 26,
                "macd_signal": 9,

                # Bollinger Bands
                "bb_period": 20,

                # Volume percentile (20 trading days)
                "vol_lookback": 20,

                # Opening range (not applicable for daily)
                "or_bars": 1,
                "or_minutes": 0,

                # Channel periods (5, 10, 20 days)
                "channel_periods": [5, 10, 20],

                # ROC periods (5, 10, 20 days)
                "roc_periods": [5, 10, 20],

                # Volatility state
                "volatility_atr_period": 14,
                "volatility_lookback": 60,
                "volatility_high_pct": 75.0,
                "volatility_low_pct": 25.0,
            }

        # INTRADAY: Scale parameters based on bar_size to maintain consistent
        # lookback periods in real time across different bar sizes
        return {
            # Momentum indicators (~2-3 hours lookback)
            "rsi_period": self.hours_to_bars(2.3),
            "cci_period": self.hours_to_bars(3.3),
            "willr_period": self.hours_to_bars(2.3),
            "mfi_period": self.hours_to_bars(2.3),
            "mom_period": self.hours_to_bars(1.0),

            # Trend indicators (~2-3 hours)
            "adx_period": self.hours_to_bars(2.3),
            "aroonosc_period": self.hours_to_bars(3.3),

            # Volatility
            "atr_period": self.hours_to_bars(2.3),

            # Moving averages
            "ema_fast": self.hours_to_bars(1.0),
            "ema_slow": self.hours_to_bars(2.3),
            "sma_short": self.hours_to_bars(1.5),
            "sma_mid": self.hours_to_bars(3.3),

            # MACD (scaled)
            "macd_fast": max(3, self.minutes_to_bars(25)),
            "macd_slow": max(7, self.minutes_to_bars(65)),
            "macd_signal": max(3, self.minutes_to_bars(25)),

            # Bollinger Bands
            "bb_period": self.hours_to_bars(1.5),

            # Volume percentile (1 trading day)
            "vol_lookback": self.bars_per_day,

            # Opening range (30 minutes)
            "or_bars": self.minutes_to_bars(30),
            "or_minutes": 30,

            # Channel periods (1h, 2h, 4h)
            "channel_periods": [
                self.hours_to_bars(1),
                self.hours_to_bars(2),
                self.hours_to_bars(4),
            ],

            # ROC periods (30m, 1h, 2h)
            "roc_periods": [
                self.minutes_to_bars(30),
                self.hours_to_bars(1),
                self.hours_to_bars(2),
            ],

            # Volatility state
            "volatility_atr_period": self.hours_to_bars(1.2),
            "volatility_lookback": self.bars_per_day,
            "volatility_high_pct": 75.0,
            "volatility_low_pct": 25.0,
        }

    # =========================================================================
    # Phase Encoding (for Backtrader compatibility)
    # =========================================================================

    def encode_phase(self, phase_str: str) -> int:
        """
        Convert session phase string to numeric encoding.

        This method is bar_size-aware (bar_size baked in at context creation):
        - Granular (5m/15m): 'night'->1, 'morning'->2, 'afternoon'->5
        - Aggregated (30m/1h): 'night_session'->1, 'day_session'->2

        Args:
            phase_str: Phase name. For granular bars: 'night', 'morning', 'afternoon'.
                      For aggregated bars: 'night_session', 'day_session'.

        Returns:
            Numeric encoding for Backtrader data feed (0 if unknown)
        """
        return self._encode_phase(phase_str)

    def decode_phase(self, phase_code: int) -> str:
        """
        Convert numeric phase code to string.

        This method is bar_size-aware (bar_size baked in at context creation):
        - Granular (5m/15m): 1->'night', 2->'morning', 5->'afternoon'
        - Aggregated (30m/1h): 1->'night_session', 2->'day_session'

        Args:
            phase_code: Numeric encoding from Backtrader data feed

        Returns:
            Phase name string ('unknown' if code not recognized)
        """
        return self._decode_phase(phase_code)

    # =========================================================================
    # Alternate Constructors
    # =========================================================================

    @classmethod
    def from_market(
        cls,
        market: str,
        instrument: str,
        frequency: str = "interday",
        bar_size: str = "1d",
    ) -> "TradingContext":
        """
        Create a TradingContext from market/instrument codes.

        Thin convenience wrapper over MarketFactory.create() so callers can
        construct a context without importing the factory directly.

        Args:
            market: Market code ('SHFE', 'CRYPTO'); case-insensitive
            instrument: Instrument code ('cu', 'al', 'btc'); case-insensitive
            frequency: 'interday' (default) or 'intraday'
            bar_size: Bar size string ('1d' default, '5m', '15m', '1h', ...)

        Returns:
            Configured TradingContext
        """
        from echolon.config.markets.factory import MarketFactory
        return MarketFactory.create(
            market=market,
            instrument=instrument,
            frequency=frequency,
            bar_size=bar_size,
        )

    def __repr__(self) -> str:
        return (
            f"TradingContext("
            f"market={self.market_code}, "
            f"instrument={self.instrument_code}, "
            f"frequency={self.frequency}, "
            f"bar_size={self.bar_size})"
        )

    # =========================================================================
    # Bar-Size-Aware Phase Selection (SHFE-specific)
    # =========================================================================

    @property
    def is_aggregated_phases(self) -> bool:
        """
        Whether current bar size uses aggregated session phases.

        Returns:
            True for 30m/1h bars (uses night_session, day_session)
            False for 5m/15m bars (uses night, morning, afternoon)
        """
        if self.market_code == 'SHFE' and self.is_intraday:
            from echolon.config.markets.shfe.phases import is_aggregated_bar_size
            return is_aggregated_bar_size(self.bar_size)
        return False

    @property
    def tradeable_phases(self) -> List[str]:
        """
        Get list of tradeable phase names appropriate for current bar size.

        Returns:
            ['night', 'morning', 'afternoon'] for 5m/15m
            ['night_session', 'day_session'] for 30m/1h
        """
        if self.market_code == 'SHFE' and self.is_intraday:
            from echolon.config.markets.shfe.phases import get_tradeable_phases
            return get_tradeable_phases(self.bar_size)
        # Default: return all trading phase names
        return [p.name for p in self.trading_phases]

