"""
Market Registry — central aggregation point for market configurations.

Singleton registry collecting configurations from all market-specific
modules. Each market module registers itself on import.

Usage::

    from echolon.config.markets.core.registry import MarketRegistry

    al_spec = MarketRegistry.get_instrument('SHFE', 'al')
    shfe_config = MarketRegistry.get_market('SHFE')
"""

from typing import Dict, List, Optional

from ..core.types import (
    MarketConfig,
    InstrumentSpec,
    SessionWindow,
    SessionPhaseSpec,
)


class MarketRegistry:
    """
    Singleton registry for all market configurations.

    Markets self-register by calling MarketRegistry.register() on module import.
    This allows adding new markets without modifying this file.
    """

    _markets: Dict[str, MarketConfig] = {}
    _initialized: bool = False

    @classmethod
    def register(cls, market: MarketConfig) -> None:
        """
        Register a market configuration.

        Called by each market module (shfe, dce, etc.) during import.

        Args:
            market: Complete market configuration
        """
        cls._markets[market.code.upper()] = market

    @classmethod
    def get_market(cls, market_code: str) -> Optional[MarketConfig]:
        """
        Get market configuration by code.

        Args:
            market_code: Market code (e.g., 'SHFE', 'DCE')

        Returns:
            MarketConfig or None if not found
        """
        return cls._markets.get(market_code.upper())

    @classmethod
    def get_instrument(cls, market: str, symbol: str) -> Optional[InstrumentSpec]:
        """
        Get instrument specification.

        Args:
            market: Market code (e.g., 'SHFE')
            symbol: Instrument code (e.g., 'al', 'cu')

        Returns:
            InstrumentSpec or None if not found
        """
        market_config = cls._markets.get(market.upper())
        if market_config:
            return market_config.instruments.get(symbol.lower())
        return None

    @classmethod
    def get_sessions(cls, market: str) -> Dict[str, SessionWindow]:
        """
        Get all session windows for a market.

        Args:
            market: Market code

        Returns:
            Dict of session name -> SessionWindow
        """
        market_config = cls._markets.get(market.upper())
        if market_config:
            return market_config.sessions
        return {}

    @classmethod
    def get_phases(cls, market: str) -> Dict[str, SessionPhaseSpec]:
        """
        Get all session phases for a market.

        Args:
            market: Market code

        Returns:
            Dict of phase name -> SessionPhaseSpec
        """
        market_config = cls._markets.get(market.upper())
        if market_config:
            return market_config.phases
        return {}

    @classmethod
    def get_instrument_list(cls, market: Optional[str] = None) -> List[str]:
        """
        Get list of all instrument codes.

        Args:
            market: Optional market code to filter by

        Returns:
            List of instrument codes
        """
        if market:
            market_config = cls._markets.get(market.upper())
            return list(market_config.instruments.keys()) if market_config else []

        all_instruments = []
        for config in cls._markets.values():
            all_instruments.extend(config.instruments.keys())
        return all_instruments

    @classmethod
    def is_night_session(cls, market: str, symbol: str) -> bool:
        """
        Check if instrument trades in night session.

        Args:
            market: Market code
            symbol: Instrument code

        Returns:
            True if instrument has night session
        """
        instrument = cls.get_instrument(market, symbol)
        return instrument.has_night_session if instrument else False

    @classmethod
    def validate_market_instrument(cls, market: str, symbol: str) -> tuple:
        """
        Validate and normalize market and instrument codes.

        Args:
            market: Market code
            symbol: Instrument code

        Returns:
            Tuple of (market_code, instrument_code)

        Raises:
            ValueError: If market or instrument is invalid
        """
        market_upper = market.upper()
        symbol_lower = symbol.lower()

        if market_upper not in cls._markets:
            valid_markets = list(cls._markets.keys())
            raise ValueError(
                f"Invalid market: '{market}'. Must be one of: {valid_markets}"
            )

        market_config = cls._markets[market_upper]
        if symbol_lower not in market_config.instruments:
            valid_instruments = list(market_config.instruments.keys())
            raise ValueError(
                f"Invalid instrument: '{symbol}' for market '{market}'. "
                f"Must be one of: {valid_instruments}"
            )

        return market_upper, symbol_lower

    @classmethod
    def get_night_session_products(cls) -> set:
        """
        Get set of all instrument codes that have night sessions.

        Returns:
            Set of instrument codes
        """
        products = set()
        for config in cls._markets.values():
            for code, spec in config.instruments.items():
                if spec.has_night_session:
                    products.add(code)
        return products

    @classmethod
    def list_registered_markets(cls) -> List[str]:
        """Get list of all registered market codes."""
        return list(cls._markets.keys())

    @classmethod
    def clear(cls) -> None:
        """Clear all registered markets (for testing)."""
        cls._markets.clear()
        cls._initialized = False
