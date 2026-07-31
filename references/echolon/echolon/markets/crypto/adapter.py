"""
Crypto Adapter
==============

Cryptocurrency perpetual futures market adapter implementation.

Implements IMarketAdapter for crypto perpetual trading:
- BTC-PERP (Bitcoin perpetual)
- ETH-PERP (Ethereum perpetual)
- Other perpetuals as configured

Key crypto-specific behavior:
1. No contract expiry: Perpetuals never expire
2. No rollover: should_rollover() always returns False
3. 24/7 trading: is_trading_day() always True, is_session_active() always True
4. Percentage commission: Typically 0.02-0.1% of trade value
5. High precision: 8+ decimal places for price and size

Funding rate consideration:
- Funding paid/received every 8 hours
- Positive rate: Longs pay shorts
- Negative rate: Shorts pay longs
- Strategy may consider funding in position decisions

Exchange abstraction:
- Works with any CCXT-supported exchange
- Exchange-specific details handled by deploy platform
"""

from datetime import date, datetime, time, timedelta
from typing import Optional, List, TYPE_CHECKING
import math

from ..base import BaseMarketAdapter
from echolon.markets.interface import SessionWindow, ContractSpec

if TYPE_CHECKING:
    from echolon.strategy.frequency.session_interface import ISessionContext

from .session_config import (
    ALL_SESSIONS,
)
from .perpetual_rules import (
    get_next_funding_time,
    is_near_funding,
    estimate_funding_payment,
)
from echolon.config.markets.crypto.perpetuals import PERPETUALS as CRYPTO_INSTRUMENTS, BARS_PER_DAY
from echolon.config.markets.core.types import InstrumentSpec


def instrument_spec_to_contract_spec(spec: InstrumentSpec) -> ContractSpec:
    """
    Convert InstrumentSpec (config) to ContractSpec (runtime).

    Args:
        spec: InstrumentSpec from config/markets

    Returns:
        ContractSpec for quant_engine runtime use
    """
    return ContractSpec(
        symbol=f"{spec.code.upper()}-PERP",
        multiplier=spec.multiplier,
        tick_size=spec.tick_size,
        margin_rate=spec.margin_rate,
        commission=spec.commission,
        commission_type=spec.commission_type,
        currency=spec.currency,
        trading_unit=spec.trading_unit,
        min_order_size=spec.min_order_size,
    )


class CryptoAdapter(BaseMarketAdapter):
    """
    Cryptocurrency perpetual futures market adapter.

    Implements market-specific logic for crypto perpetual trading.
    Key differences from traditional futures:
    - 24/7 trading
    - No contract expiry
    - Funding mechanism instead of expiry/rollover
    """

    def __init__(
        self,
        symbol: str = "btc",
        commission_rate: float = 0.0005,
        margin_rate: float = 0.01
    ):
        """
        Initialize crypto adapter.

        Args:
            symbol: Primary symbol (e.g., 'btc', 'eth')
            commission_rate: Trading fee rate (e.g., 0.0005 = 0.05%)
            margin_rate: Margin requirement rate
        """
        super().__init__()

        self._symbol = symbol.lower()
        self._commission_rate = commission_rate
        self._margin_rate = margin_rate

        # Register contract specs from canonical config source
        for sym, instrument_spec in CRYPTO_INSTRUMENTS.items():
            contract_spec = instrument_spec_to_contract_spec(instrument_spec)
            self.register_contract_spec(sym, contract_spec)

    # =========================================================================
    # Required Properties
    # =========================================================================

    @property
    def market_code(self) -> str:
        """Get crypto market code."""
        return "CRYPTO"

    @property
    def market_name(self) -> str:
        """Get full market name."""
        return "Cryptocurrency"

    @property
    def timezone(self) -> str:
        """Get market timezone."""
        return "UTC"

    @property
    def trading_sessions(self) -> List[SessionWindow]:
        """Get crypto trading sessions (24/7)."""
        return ALL_SESSIONS

    @property
    def supports_overnight_positions(self) -> bool:
        """Crypto supports positions indefinitely."""
        return True

    @property
    def has_contract_expiry(self) -> bool:
        """Perpetuals don't expire."""
        return False

    @property
    def symbol(self) -> str:
        """Get the primary symbol for this adapter."""
        return self._symbol

    # =========================================================================
    # Contract Management (simplified for perpetuals)
    # =========================================================================

    def get_contract_spec(self, symbol: str) -> ContractSpec:
        """
        Get contract specification for a symbol.

        Args:
            symbol: Symbol (e.g., 'btc', 'eth')

        Returns:
            ContractSpec for the symbol

        Raises:
            KeyError: If symbol not found
        """
        sym = symbol.lower()
        if sym in self._contract_specs:
            return self._contract_specs[sym]

        # Fallback to config source (convert on-the-fly)
        if sym in CRYPTO_INSTRUMENTS:
            return instrument_spec_to_contract_spec(CRYPTO_INSTRUMENTS[sym])

        raise KeyError(f"Unknown crypto symbol: {symbol}")

    def get_main_contract(self, trading_date: date) -> str:
        """
        Get the main contract for crypto.

        For perpetuals, this is always the same symbol
        (no contract months like traditional futures).

        Args:
            trading_date: Date (unused for perpetuals)

        Returns:
            Perpetual contract symbol
        """
        return f"{self._symbol.upper()}-PERP"

    def should_rollover(
        self,
        contract: str,
        trading_date: date,
        position_size: int
    ) -> bool:
        """
        Check if rollover is needed.

        For perpetuals, always returns False (no expiry).

        Args:
            contract: Contract code
            trading_date: Current date
            position_size: Position size

        Returns:
            Always False for perpetuals
        """
        return False

    def get_rollover_target(
        self,
        current_contract: str,
        trading_date: date
    ) -> Optional[str]:
        """
        Get rollover target contract.

        For perpetuals, always returns None (no rollover).

        Args:
            current_contract: Current contract
            trading_date: Current date

        Returns:
            Always None for perpetuals
        """
        return None

    def get_contract_expiry_date(self, contract: str) -> Optional[date]:
        """
        Get expiry date for a contract.

        For perpetuals, returns None (no expiry).

        Args:
            contract: Contract symbol

        Returns:
            None for perpetuals
        """
        return None

    # =========================================================================
    # Calendar Methods (24/7 trading)
    # =========================================================================

    def is_trading_day(self, check_date: date) -> bool:
        """
        Check if date is a trading day.

        For crypto, every day is a trading day.

        Args:
            check_date: Date to check

        Returns:
            Always True for crypto
        """
        return True

    def is_session_active(self, current_time: datetime) -> bool:
        """
        Check if trading session is active.

        For crypto, always returns True (24/7).

        Args:
            current_time: Current datetime

        Returns:
            Always True for crypto
        """
        return True

    def get_session_close_time(self, check_date: date) -> datetime:
        """
        Get session close time.

        For crypto, returns 23:59:59 (end of UTC day).

        Args:
            check_date: Date

        Returns:
            Datetime of session close
        """
        return datetime.combine(check_date, time(23, 59, 59))

    def get_next_trading_day(self, from_date: date) -> date:
        """
        Get next trading day.

        For crypto, every day is a trading day.

        Args:
            from_date: Starting date

        Returns:
            Next day
        """
        return from_date + timedelta(days=1)

    def get_previous_trading_day(self, from_date: date) -> date:
        """
        Get previous trading day.

        For crypto, every day is a trading day.

        Args:
            from_date: Starting date

        Returns:
            Previous day
        """
        return from_date - timedelta(days=1)

    # =========================================================================
    # Commission Calculation
    # =========================================================================

    def calculate_commission(
        self,
        symbol: str,
        size: int,
        price: float,
        close_today: bool = False,
        side: str | None = None,
    ) -> float:
        """
        Calculate commission for a trade.

        Crypto uses percentage-based commission.

        Args:
            symbol: Symbol
            size: Trade size
            price: Trade price

        Returns:
            Commission amount
        """
        spec = self.get_contract_spec(symbol)
        return spec.calculate_commission(price, size)

    def calculate_margin(
        self,
        symbol: str,
        size: int,
        price: float
    ) -> float:
        """
        Calculate required margin for a position.

        Args:
            symbol: Symbol
            size: Position size
            price: Current price

        Returns:
            Required margin
        """
        spec = self.get_contract_spec(symbol)
        return spec.calculate_margin(price, size)

    # =========================================================================
    # Precision Methods
    # =========================================================================

    def get_price_precision(self, symbol: str) -> int:
        """
        Get price decimal precision for a symbol.

        Args:
            symbol: Trading symbol

        Returns:
            Number of decimal places for price
        """
        spec = self.get_contract_spec(symbol)
        if spec.tick_size >= 1:
            return 0
        return abs(int(math.log10(spec.tick_size)))

    def get_size_precision(self, symbol: str) -> int:
        """
        Get size decimal precision for a symbol.

        Args:
            symbol: Trading symbol

        Returns:
            Number of decimal places for size
        """
        spec = self.get_contract_spec(symbol)
        if spec.min_order_size >= 1:
            return 0
        return abs(int(math.log10(spec.min_order_size)))

    # =========================================================================
    # Funding Rate Utilities
    # =========================================================================

    def get_next_funding_time(self, current_time: datetime) -> datetime:
        """
        Get next funding time.

        Args:
            current_time: Current datetime (UTC)

        Returns:
            Next funding datetime
        """
        return get_next_funding_time(current_time)

    def is_near_funding(
        self,
        current_time: datetime,
        minutes_before: int = 15
    ) -> bool:
        """
        Check if near funding time.

        Args:
            current_time: Current datetime
            minutes_before: Minutes threshold

        Returns:
            True if within threshold of funding
        """
        return is_near_funding(current_time, minutes_before)

    def estimate_funding_cost(
        self,
        position_value: float,
        funding_rate: float,
        is_long: bool
    ) -> float:
        """
        Estimate funding payment.

        Args:
            position_value: Position value
            funding_rate: Current funding rate
            is_long: True if long position

        Returns:
            Estimated payment (positive = pay, negative = receive)
        """
        return estimate_funding_payment(position_value, funding_rate, is_long)

    # =========================================================================
    # Session Context Provider
    # =========================================================================

    def create_session_provider(
        self,
        bar_size_minutes: int = 15,
    ) -> 'ISessionContext':
        """
        Create crypto session context provider.

        Provides FACTUAL session data. Strategy decides phase thresholds.

        Args:
            bar_size_minutes: Bar size in minutes (default: 15)

        Returns:
            CryptoSessionProvider instance
        """
        from .sessions import CryptoSessionProvider
        return CryptoSessionProvider(
            market_adapter=self,
            bar_size_minutes=bar_size_minutes,
        )

    # =========================================================================
    # Utility Methods
    # =========================================================================

    def get_bars_per_day(self, bar_size: str) -> int:
        """
        Get expected bars per day for a bar size.

        Args:
            bar_size: Bar size string

        Returns:
            Expected bars per day
        """
        return BARS_PER_DAY.get(bar_size, 96)

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"CryptoAdapter(symbol={self._symbol}, "
            f"commission_rate={self._commission_rate}, "
            f"margin_rate={self._margin_rate})"
        )
