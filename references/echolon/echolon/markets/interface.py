"""
Market Adapter Interface
========================

Abstract interface for market-specific logic abstraction.

Each market (SHFE, crypto, CME) implements IMarketAdapter to provide:
- Trading session windows and calendar
- Contract specifications (multiplier, tick size, margin, commission)
- Main contract determination (for futures)
- Contract rollover logic (for expiring futures)
- Commission calculations

This interface enables strategy code to remain market-agnostic while
properly handling market-specific rules like SHFE's contract expiry
or crypto's 24/7 perpetual trading.

Data classes:
- SessionWindow: Imported from echolon.config.markets.core.types (canonical source)
- ContractSpec: Contract specification (multiplier, tick size, etc.)

Key methods:
- get_main_contract(date): Determine front/main contract
- should_rollover(contract, date, size): Check if position needs rolling
- is_trading_day(date): Check if market is open
- calculate_commission(symbol, size, price): Calculate trade commission
"""

from abc import ABC, abstractmethod
from typing import List, Optional, Tuple, TYPE_CHECKING
from datetime import date, datetime
from dataclasses import dataclass

# Import SessionWindow from canonical source
from echolon.config.markets.core.types import SessionWindow

if TYPE_CHECKING:
    from .session_context import ISessionContext


@dataclass
class ContractSpec:
    """
    Contract specification.

    Contains all the details needed for position sizing and P&L calculation.
    """
    symbol: str
    multiplier: float  # Contract multiplier (e.g., 5 for aluminum = 5 tons/contract)
    tick_size: float  # Minimum price movement (e.g., 5 CNY for aluminum)
    margin_rate: float  # Initial margin as percentage (e.g., 0.10 = 10%)
    commission: float  # Commission per contract or rate (depends on commission_type)
    commission_type: str = "per_contract"  # "per_contract" or "percentage"
    close_today_commission: Optional[float] = None  # Same unit/mode as commission
    currency: str = "CNY"
    expiry_date: Optional[date] = None
    trading_unit: str = "lots"  # "lots", "contracts", "coins"
    min_order_size: float = 1.0
    max_order_size: Optional[float] = None
    stamp_duty_rate: float = 0.0
    transfer_fee_rate: float = 0.0
    min_commission: float = 0.0
    long_only: bool = False
    t_plus_one: bool = False

    # =========================================================================
    # Cost-model v2 fields (Q59 + Q60; per qorka decisions_log.md 2026-05-13
    # "Cost-model v2" entry). Address 2 of the 5 gaps in v1 scalar:
    # gap 1 (per-intent variance) + gap 4 (vol-regime dependence). Gap 2
    # (abandonment) ships in Gate 1B alongside A9 live-replay. Gaps 3+5
    # (partial-fill, fat-tail) deferred to Wave 2 per Q62.
    #
    # Precedence rule in backtrader_engine:
    #   1. calibrated_slippage_bps_by_intent (v2) — preferred when set
    #   2. calibrated_slippage_bps (v1 scalar) — backward-compat fallback
    #   3. tick_size-derived (legacy default)
    # =========================================================================

    # Per-intent slippage in basis points (one-way). Keys: "ENTRY", "EXIT",
    # "FORCED_EXIT". When set, backtrader_engine installs a custom slippage
    # broker (`StructuredSlippageBroker`) that classifies each order's intent
    # by inspecting position state pre-fill and applies the matching bps.
    # Populated by qorka's per-intent calibration (Q59 default plan: p50 of
    # observed live `trade_executions_*.csv` filtered by `intent` field, plus
    # Q41 buffer rule).
    calibrated_slippage_bps_by_intent: Optional[dict] = None

    # Vol-regime cost multiplier. When current bar's 60-day rolling vol
    # percentile exceeds `high_vol_pct_threshold`, per-intent bps is
    # multiplied by `high_vol_slippage_multiplier`. Default 1.0 = no
    # regime dependence. Per Q60 default plan: threshold=75.0, multiplier
    # calibrated from observed live high-vol vs normal-period fills.
    high_vol_slippage_multiplier: float = 1.0
    high_vol_pct_threshold: float = 75.0

    # Stub for Wave 2 fat-tail modeling (Q62). When > 1.0, stress-test
    # backtests can sample tail slippage as tail_factor × median. Ignored
    # in Gate 1A — the underlying stochastic-sampling slippage class is
    # Wave 2 scope per `decisions_log.md` 2026-05-13 "Cost-model v2".
    tail_factor: float = 1.0

    # v1 scalar (DEPRECATED 2026-05-13; backward-compat fallback only).
    # Ignored when `calibrated_slippage_bps_by_intent` is set.
    # Live-calibrated slippage override (basis points per side). When set
    # AND v2 dict is None, backtrader_engine prefers this over the
    # tick-derived slippage. Per Q47 Option A (v1).
    calibrated_slippage_bps: Optional[float] = None

    def calculate_contract_value(self, price: float, size: float = 1.0) -> float:
        """Calculate notional value of contracts."""
        return price * self.multiplier * abs(size)

    def calculate_margin(self, price: float, size: float) -> float:
        """Calculate required margin for position."""
        return self.calculate_contract_value(price, size) * self.margin_rate

    def calculate_commission(
        self,
        price: float,
        size: float,
        close_today: bool = False,
        side: str | None = None,
    ) -> float:
        """Calculate total trade charges in RMB; invalid sides raise loudly."""
        if side not in (None, "BUY", "SELL"):
            raise ValueError("side must be BUY, SELL, or None")
        commission = (
            self.close_today_commission
            if close_today and self.close_today_commission is not None
            else self.commission
        )
        notional = self.calculate_contract_value(price, size)
        if self.commission_type == "per_contract":
            brokerage = abs(size) * commission
        else:  # percentage
            brokerage = notional * commission
        if side is None:
            return brokerage
        brokerage = max(brokerage, self.min_commission)
        stamp_duty = notional * self.stamp_duty_rate if side == "SELL" else 0.0
        return brokerage + stamp_duty + notional * self.transfer_fee_rate

    def calculate_pnl(
        self,
        entry_price: float,
        exit_price: float,
        size: float,
        is_long: bool = True
    ) -> float:
        """
        Calculate P&L for a trade.

        Args:
            entry_price: Entry price
            exit_price: Exit price
            size: Position size (positive)
            is_long: True for long position, False for short

        Returns:
            Profit/loss in currency units
        """
        price_diff = exit_price - entry_price if is_long else entry_price - exit_price
        return price_diff * self.multiplier * abs(size)


class IMarketAdapter(ABC):
    """
    Abstract interface for market-specific logic.

    Each market (SHFE, crypto, CME) implements this interface
    to provide market-specific behavior while maintaining
    a consistent API for the strategy layer.
    """

    @property
    @abstractmethod
    def market_code(self) -> str:
        """
        Market identifier.

        Examples: 'SHFE', 'CRYPTO', 'CME', 'CFFEX'
        """
        pass

    @property
    @abstractmethod
    def market_name(self) -> str:
        """
        Full market name.

        Examples: 'Shanghai Futures Exchange', 'Cryptocurrency', 'Chicago Mercantile Exchange'
        """
        pass

    @property
    @abstractmethod
    def timezone(self) -> str:
        """
        Market timezone.

        Examples: 'Asia/Shanghai', 'UTC', 'America/Chicago'
        """
        pass

    @property
    @abstractmethod
    def trading_sessions(self) -> List[SessionWindow]:
        """List of trading session windows."""
        pass

    @property
    @abstractmethod
    def supports_overnight_positions(self) -> bool:
        """Whether market allows overnight positions."""
        pass

    @property
    @abstractmethod
    def has_contract_expiry(self) -> bool:
        """Whether contracts expire (True for futures, False for perpetuals)."""
        pass

    @abstractmethod
    def get_contract_spec(self, symbol: str) -> ContractSpec:
        """
        Get contract specification for a symbol.

        Args:
            symbol: Trading symbol (e.g., 'al2403', 'BTC-PERP')

        Returns:
            ContractSpec with all contract details
        """
        pass

    @abstractmethod
    def get_main_contract(self, trading_date: date, instrument: str) -> str:
        """
        Determine the main/front contract for a given date.

        For futures: Typically 1-2 months ahead
        For crypto perpetuals: Always the perpetual contract

        Args:
            instrument: Base instrument code (e.g., 'al', 'BTC')
            trading_date: Date to determine main contract for

        Returns:
            Main contract symbol (e.g., 'al2403', 'BTC-PERP')
        """
        pass

    @abstractmethod
    def should_rollover(
        self,
        current_contract: str,
        trading_date: date,
        position_size: float
    ) -> bool:
        """
        Check if position should be rolled to new contract.

        For futures: Based on expiry dates
        For perpetuals: Always False (no expiry)

        Args:
            current_contract: Current contract symbol
            trading_date: Current trading date
            position_size: Current position size

        Returns:
            True if position should be rolled
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
            current_contract: Current contract symbol
            trading_date: Current trading date

        Returns:
            Target contract symbol or None if no rollover needed
        """
        pass

    @abstractmethod
    def get_contract_expiry_date(self, contract: str) -> Optional[date]:
        """
        Get expiry date for a contract.

        Args:
            contract: Contract symbol

        Returns:
            Expiry date or None for perpetuals
        """
        pass

    @abstractmethod
    def is_trading_day(self, check_date: date) -> bool:
        """
        Check if a date is a valid trading day.

        Args:
            check_date: Date to check

        Returns:
            True if market is open on this date
        """
        pass

    @abstractmethod
    def is_session_active(self, check_time: datetime) -> bool:
        """
        Check if current time is within active trading session.

        Args:
            check_time: Datetime to check

        Returns:
            True if within trading hours
        """
        pass

    @abstractmethod
    def get_session_close_time(self, check_date: date) -> datetime:
        """
        Get the closing time for the trading day.

        Args:
            check_date: Trading date

        Returns:
            Datetime of session close
        """
        pass

    @abstractmethod
    def get_next_trading_day(self, from_date: date) -> date:
        """
        Get next valid trading day.

        Args:
            from_date: Starting date

        Returns:
            Next trading day after from_date
        """
        pass

    @abstractmethod
    def get_previous_trading_day(self, from_date: date) -> date:
        """
        Get previous valid trading day.

        Args:
            from_date: Starting date

        Returns:
            Previous trading day before from_date
        """
        pass

    @abstractmethod
    def calculate_commission(
        self,
        symbol: str,
        size: float,
        price: float,
        close_today: bool = False,
        side: str | None = None,
    ) -> float:
        """
        Calculate commission for a trade.

        Args:
            symbol: Trading symbol
            size: Trade size
            price: Trade price

        Returns:
            Commission amount in market currency
        """
        pass

    @abstractmethod
    def get_price_precision(self, symbol: str) -> int:
        """
        Get price decimal precision for a symbol.

        Args:
            symbol: Trading symbol

        Returns:
            Number of decimal places for price
        """
        pass

    @abstractmethod
    def get_size_precision(self, symbol: str) -> int:
        """
        Get size decimal precision for a symbol.

        Args:
            symbol: Trading symbol

        Returns:
            Number of decimal places for size
        """
        pass

    def get_total_trading_minutes(self) -> int:
        """Get total trading minutes per day across all sessions."""
        return sum(session.duration_minutes() for session in self.trading_sessions)

    def get_bars_per_day(self, bar_minutes: int) -> int:
        """
        Calculate number of bars per day for a given bar size.

        Args:
            bar_minutes: Bar size in minutes

        Returns:
            Expected number of bars per trading day
        """
        total_minutes = self.get_total_trading_minutes()
        return total_minutes // bar_minutes

    def parse_contract(self, contract: str) -> Tuple[str, Optional[int], Optional[int]]:
        """
        Parse contract string into components.

        Args:
            contract: Contract symbol (e.g., 'al2403')

        Returns:
            Tuple of (instrument, year, month) or (symbol, None, None) for perpetuals
        """
        # Default implementation for futures-style contracts
        # Subclasses can override for different formats
        if len(contract) >= 6:
            instrument = contract[:2]
            year = 2000 + int(contract[2:4])
            month = int(contract[4:6])
            return (instrument, year, month)
        return (contract, None, None)

    def create_session_provider(
        self,
        bar_size_minutes: int = 5,
    ) -> 'ISessionContext':
        """
        Create a session context provider for this market.

        Factory method that returns the appropriate session provider
        for this market (SHFE, crypto, etc.).

        DESIGN PRINCIPLE:
            Infrastructure provides factual data only.
            Strategy decides opening/closing phase thresholds.

        Args:
            bar_size_minutes: Bar size in minutes (default: 5)

        Returns:
            ISessionContext implementation appropriate for this market

        Note:
            This is a default implementation that raises NotImplementedError.
            Market-specific adapters should override this method.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement create_session_provider(). "
            "Override this method to return a market-specific session provider."
        )
