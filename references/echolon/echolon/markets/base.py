"""
Base Market Adapter
===================

Abstract base class providing common functionality for market adapters.

Provides default implementations for:
- Price and size precision methods
- Common calendar utilities
- Helper methods for session calculations

Subclasses must implement:
- market_code property
- trading_sessions property
- supports_overnight_positions property
- get_contract_spec()
- get_main_contract()
- should_rollover()
- get_rollover_target()
- is_trading_day()
- is_session_active()
- get_session_close_time()
- calculate_commission()

This base class reduces code duplication across adapters while
ensuring all required interface methods are implemented.
"""

from abc import ABC, abstractmethod
from datetime import datetime, date, time
from typing import Optional, List, Dict

from echolon.markets.interface import SessionWindow, ContractSpec, IMarketAdapter


class BaseMarketAdapter(IMarketAdapter, ABC):
    """
    Abstract base class for market adapters.

    Provides common functionality and default implementations
    for market-specific adapters (SHFE, Crypto, CME, etc.).
    """

    def __init__(self):
        """Initialize base market adapter."""
        self._contract_specs: Dict[str, ContractSpec] = {}

    # =========================================================================
    # Abstract Properties (must be implemented by subclasses)
    # =========================================================================

    @property
    @abstractmethod
    def market_code(self) -> str:
        """
        Get the market identifier code.

        Returns:
            Market code string (e.g., 'SHFE', 'CRYPTO', 'CME')
        """
        pass

    @property
    @abstractmethod
    def trading_sessions(self) -> List[SessionWindow]:
        """
        Get the list of trading sessions for this market.

        Returns:
            List of SessionWindow objects defining trading hours
        """
        pass

    @property
    @abstractmethod
    def supports_overnight_positions(self) -> bool:
        """
        Check if this market supports holding positions overnight.

        Returns:
            True if overnight positions are supported
        """
        pass

    # =========================================================================
    # Abstract Methods (must be implemented by subclasses)
    # =========================================================================

    @abstractmethod
    def get_contract_spec(self, symbol: str) -> ContractSpec:
        """
        Get contract specification for a symbol.

        Args:
            symbol: Product symbol (e.g., 'al', 'cu', 'BTC')

        Returns:
            ContractSpec with contract details
        """
        pass

    @abstractmethod
    def get_main_contract(self, trading_date: date) -> str:
        """
        Get the main contract code for a trading date.

        Args:
            trading_date: Date to get main contract for

        Returns:
            Main contract code (e.g., 'al2403')
        """
        pass

    @abstractmethod
    def should_rollover(
        self,
        contract: str,
        trading_date: date,
        position_size: int
    ) -> bool:
        """
        Check if position should be rolled to next contract.

        Args:
            contract: Current contract code
            trading_date: Current trading date
            position_size: Current position size

        Returns:
            True if rollover should occur
        """
        pass

    @abstractmethod
    def get_rollover_target(
        self,
        current_contract: str,
        trading_date: date
    ) -> Optional[str]:
        """
        Get the target contract for rollover.

        Args:
            current_contract: Current contract code
            trading_date: Current trading date

        Returns:
            Target contract code, or None if no rollover needed
        """
        pass

    @abstractmethod
    def is_trading_day(self, check_date: date) -> bool:
        """
        Check if a date is a valid trading day.

        Args:
            check_date: Date to check

        Returns:
            True if trading day
        """
        pass

    @abstractmethod
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

        Args:
            symbol: Product symbol
            size: Trade size
            price: Trade price

        Returns:
            Commission amount
        """
        pass

    # =========================================================================
    # Default Implementations
    # =========================================================================

    def is_session_active(self, current_time: datetime) -> bool:
        """
        Check if any trading session is currently active.

        Default implementation checks against all trading_sessions.

        Args:
            current_time: Current datetime to check

        Returns:
            True if within a trading session
        """
        check_time = current_time.time()
        for session in self.trading_sessions:
            if session.contains_time(check_time):
                return True
        return False

    def get_session_close_time(self, current_time: datetime) -> Optional[time]:
        """
        Get the close time of the current or next session.

        Args:
            current_time: Current datetime

        Returns:
            Session close time, or None if outside all sessions
        """
        check_time = current_time.time()

        # Check if we're in a session
        for session in self.trading_sessions:
            if session.contains_time(check_time):
                return session.end

        # Find next session
        sorted_sessions = sorted(self.trading_sessions, key=lambda s: s.start)
        for session in sorted_sessions:
            if session.start > check_time:
                return session.end

        # Return first session's close (for next day)
        if sorted_sessions:
            return sorted_sessions[0].end

        return None

    def get_current_session(self, current_time: datetime) -> Optional[SessionWindow]:
        """
        Get the current trading session.

        Args:
            current_time: Current datetime

        Returns:
            Current SessionWindow, or None if outside all sessions
        """
        check_time = current_time.time()
        for session in self.trading_sessions:
            if session.contains_time(check_time):
                return session
        return None

    def get_next_session(self, current_time: datetime) -> Optional[SessionWindow]:
        """
        Get the next trading session.

        Args:
            current_time: Current datetime

        Returns:
            Next SessionWindow, or None if no more sessions today
        """
        check_time = current_time.time()
        sorted_sessions = sorted(self.trading_sessions, key=lambda s: s.start)

        for session in sorted_sessions:
            if session.start > check_time:
                return session

        return None

    def get_minutes_to_session_close(self, current_time: datetime) -> Optional[int]:
        """
        Get minutes remaining until current session closes.

        Args:
            current_time: Current datetime

        Returns:
            Minutes until session close, or None if not in session
        """
        current_session = self.get_current_session(current_time)
        if not current_session:
            return None

        check_time = current_time.time()
        session_end = current_session.end

        # Calculate minutes
        current_minutes = check_time.hour * 60 + check_time.minute
        end_minutes = session_end.hour * 60 + session_end.minute

        return end_minutes - current_minutes

    def round_price(self, price: float, symbol: str) -> float:
        """
        Round price to valid tick size.

        Args:
            price: Raw price
            symbol: Product symbol

        Returns:
            Price rounded to tick size
        """
        spec = self.get_contract_spec(symbol)
        tick_size = spec.tick_size
        return round(round(price / tick_size) * tick_size, 6)

    def round_size(self, size: float, symbol: str) -> int:
        """
        Round size to valid lot size.

        Args:
            size: Raw size
            symbol: Product symbol

        Returns:
            Size rounded to lot size
        """
        spec = self.get_contract_spec(symbol)
        lot_size = spec.min_order_size
        return int(round(size / lot_size) * lot_size)

    def get_trading_days_in_month(
        self,
        year: int,
        month: int
    ) -> List[date]:
        """
        Get all trading days in a specific month.

        Args:
            year: Year
            month: Month (1-12)

        Returns:
            List of trading dates
        """
        from calendar import monthrange

        trading_days = []
        _, last_day = monthrange(year, month)

        for day in range(1, last_day + 1):
            check_date = date(year, month, day)
            if self.is_trading_day(check_date):
                trading_days.append(check_date)

        return trading_days

    def get_total_trading_minutes_per_day(self) -> int:
        """
        Get total trading minutes per day.

        Returns:
            Total minutes across all sessions
        """
        return sum(session.duration_minutes for session in self.trading_sessions)

    # =========================================================================
    # Contract Spec Management
    # =========================================================================

    def register_contract_spec(self, symbol: str, spec: ContractSpec) -> None:
        """
        Register a contract specification.

        Args:
            symbol: Product symbol
            spec: Contract specification
        """
        self._contract_specs[symbol.lower()] = spec

    def has_contract_spec(self, symbol: str) -> bool:
        """
        Check if contract spec exists for symbol.

        Args:
            symbol: Product symbol

        Returns:
            True if spec is registered
        """
        return symbol.lower() in self._contract_specs

    # =========================================================================
    # Utility Methods
    # =========================================================================

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"{self.__class__.__name__}("
            f"market={self.market_code}, "
            f"sessions={len(self.trading_sessions)}, "
            f"overnight={self.supports_overnight_positions})"
        )
