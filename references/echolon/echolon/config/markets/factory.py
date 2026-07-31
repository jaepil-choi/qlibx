"""
Market Factory - Creates TradingContext from explicit values.

Host apps own session/config parsing. MarketFactory.create() is the library's
only public entry point; it accepts market/instrument/frequency/bar_size and
returns a fully wired TradingContext with no file I/O.

Usage:
    from echolon.config.markets.factory import MarketFactory

    ctx = MarketFactory.create(
        market='SHFE',
        instrument='al',
        frequency='intraday',
        bar_size='5m',
    )

    print(f"Trading {ctx.instrument_name} on {ctx.market_code}")
    print(f"Bars per day: {ctx.bars_per_day}")
"""

from typing import Optional

from echolon.config.markets.core.context import TradingContext
from echolon.config.markets.core.types import MarketConfig, InstrumentSpec


class MarketFactory:
    """
    Factory for creating TradingContext instances from explicit values.
    """

    # Cache for loaded market configs
    _market_configs: dict = {}

    @classmethod
    def create(
        cls,
        market: str,
        instrument: str,
        frequency: str,
        bar_size: str,
        initial_capital: float = 200000.0,
    ) -> TradingContext:
        """
        Create TradingContext with explicit parameters.

        Args:
            market: Market code ('SHFE', 'CRYPTO')
            instrument: Instrument code ('al', 'btc')
            frequency: 'intraday' or 'interday'
            bar_size: Bar size ('1m', '5m', '15m', '1h', '1d')
            initial_capital: Starting capital for backtesting / live trading.

        Returns:
            Configured TradingContext

        Raises:
            ValueError: If market or instrument is not supported
        """
        market_upper = market.upper()
        instrument_lower = instrument.lower()

        # Get market config
        market_config = cls._get_market_config(market_upper)
        if market_config is None:
            supported = cls._get_supported_markets()
            raise ValueError(
                f"Unsupported market: '{market}'. Supported: {supported}"
            )

        # Get instrument spec using flexible lookup (supports code or name)
        instrument_spec = cls.get_instrument_flexible(market_upper, instrument_lower)
        if instrument_spec is None:
            supported = list(market_config.instruments.keys())
            raise ValueError(
                f"Unsupported instrument: '{instrument}' for market '{market}'. "
                f"Supported: {supported}"
            )

        # Get encoding functions (bar_size-aware for SHFE aggregated phases)
        encode_fn, decode_fn = cls._get_encoding_functions(market_upper, bar_size)

        return TradingContext(
            market=market_config,
            instrument=instrument_spec,
            frequency=frequency,
            bar_size=bar_size,
            initial_capital=initial_capital,
            _encode_phase=encode_fn,
            _decode_phase=decode_fn,
        )

    @classmethod
    def _get_market_config(cls, market_code: str) -> Optional[MarketConfig]:
        """Get market configuration, loading if necessary."""
        if market_code not in cls._market_configs:
            cls._load_market(market_code)
        return cls._market_configs.get(market_code)

    @classmethod
    def _load_market(cls, market_code: str) -> None:
        """Load market configuration module."""
        if market_code == 'SHFE':
            from echolon.config.markets.shfe.config import CONFIG
            cls._market_configs['SHFE'] = CONFIG
        elif market_code == 'CRYPTO':
            from echolon.config.markets.crypto.config import CONFIG
            cls._market_configs['CRYPTO'] = CONFIG
        # Add more markets here as needed

    @classmethod
    def _get_encoding_functions(cls, market_code: str, bar_size: str) -> tuple:
        """
        Get phase encoding/decoding functions for a market.

        Creates bar_size-aware functions that use the correct encoding
        for granular (5m/15m) vs aggregated (30m/1h) phases.

        Args:
            market_code: Market code (e.g., 'SHFE')
            bar_size: Bar size string (e.g., '30m') to determine encoding

        Returns:
            Tuple of (encode_fn, decode_fn) with bar_size baked in
        """
        if market_code == 'SHFE':
            from echolon.config.markets.shfe.phases import encode_phase, decode_phase
            # Create bar_size-aware functions
            return (
                lambda phase_str: encode_phase(phase_str, bar_size),
                lambda phase_code: decode_phase(phase_code, bar_size)
            )
        elif market_code == 'CRYPTO':
            # Crypto doesn't have session phases in the same way
            # Return identity functions
            return lambda _: 0, lambda _: 'continuous'

        # Default: no-op functions
        return lambda _: 0, lambda _: 'unknown'

    @classmethod
    def _get_supported_markets(cls) -> list:
        """Get list of supported market codes."""
        return ['SHFE', 'CRYPTO']

    @classmethod
    def get_market_config(cls, market: str) -> Optional[MarketConfig]:
        """
        Get raw market configuration.

        For cases where you need the config without creating a full context.

        Args:
            market: Market code

        Returns:
            MarketConfig or None
        """
        return cls._get_market_config(market.upper())

    @classmethod
    def get_instrument(cls, market: str, instrument: str) -> Optional[InstrumentSpec]:
        """
        Get raw instrument specification by code.

        Args:
            market: Market code
            instrument: Instrument code

        Returns:
            InstrumentSpec or None
        """
        market_config = cls._get_market_config(market.upper())
        if market_config:
            return market_config.instruments.get(instrument.lower())
        return None

    @classmethod
    def get_instrument_flexible(cls, market: str, identifier: str) -> Optional[InstrumentSpec]:
        """
        Get instrument specification by either code or name.

        Supports flexible lookup:
        - By code: 'al', 'cu', 'btc'
        - By name: 'aluminum', 'copper', 'bitcoin_perpetual'

        Args:
            market: Market code (e.g., 'SHFE', 'CRYPTO')
            identifier: Instrument code or name

        Returns:
            InstrumentSpec or None
        """
        market_config = cls._get_market_config(market.upper())
        if not market_config:
            return None

        identifier_lower = identifier.lower()

        # Try as code first (most common)
        if identifier_lower in market_config.instruments:
            return market_config.instruments[identifier_lower]

        # Try as name
        for spec in market_config.instruments.values():
            if spec.name.lower() == identifier_lower:
                return spec

        return None

    @classmethod
    def list_instruments(cls, market: str) -> list:
        """
        List all instruments for a market.

        Args:
            market: Market code

        Returns:
            List of instrument codes
        """
        market_config = cls._get_market_config(market.upper())
        if market_config:
            return list(market_config.instruments.keys())
        return []

    @classmethod
    def clear_cache(cls) -> None:
        """Clear cached market configs (for testing)."""
        cls._market_configs.clear()
