"""
SHFE Adapter
============

Shanghai Futures Exchange market adapter implementation.

Implements IMarketAdapter for SHFE metals trading:
- Aluminum (al)
- Copper (cu)
- Zinc (zn)
- Nickel (ni)

Key SHFE-specific rules:
1. Main contract: 2 months ahead (trading Jan 15 → main contract is al2403)
2. Expiry: Must close position by last trading day of month before delivery
3. Sessions: Day1 (9:00-10:15), Day2 (10:30-11:30), Afternoon (13:30-15:00), Night (21:00-23:00)
4. Commission: Fixed per contract (e.g., 3.01 CNY for aluminum)

Contract naming: al2403 = Aluminum, March 2024
"""

from datetime import date, datetime
from pathlib import Path
from typing import Optional, List, TYPE_CHECKING
import math

from ..base import BaseMarketAdapter
from echolon.markets.interface import SessionWindow, ContractSpec

if TYPE_CHECKING:
    from echolon.strategy.frequency.session_interface import ISessionContext
from .sessions import SHFESessionProvider
from echolon.config.markets.shfe.sessions import (
    ALL_SESSIONS,
    DAY_SESSIONS,
    SESSIONS as SHFE_SESSIONS,
)
from echolon.config.markets.shfe.instruments import INSTRUMENTS as SHFE_INSTRUMENTS, NIGHT_SESSION_PRODUCTS
from echolon.config.markets.core.types import InstrumentSpec
from .trading_calendar import TradingCalendar
from .contract_rules import (
    get_main_contract,
    should_rollover,
    get_rollover_target as contract_get_rollover_target,
    get_expiry_date,
    parse_contract,
)

# Session aliases for convenience
NIGHT_SESSION = SHFE_SESSIONS['night']
AFTERNOON_SESSION = SHFE_SESSIONS['afternoon']


def get_sessions_for_product(product_code: str) -> list:
    """Get trading sessions for a product based on whether it has night session."""
    if product_code.lower() in NIGHT_SESSION_PRODUCTS:
        return ALL_SESSIONS
    return DAY_SESSIONS


def instrument_spec_to_contract_spec(spec: InstrumentSpec) -> ContractSpec:
    """
    Convert InstrumentSpec (config) to ContractSpec (runtime).

    Args:
        spec: InstrumentSpec from config/markets

    Returns:
        ContractSpec for quant_engine runtime use
    """
    return ContractSpec(
        symbol=spec.code,
        multiplier=spec.multiplier,
        tick_size=spec.tick_size,
        margin_rate=spec.margin_rate,
        commission=spec.commission,
        commission_type=spec.commission_type,
        close_today_commission=spec.close_today_commission,
        currency=spec.currency,
        trading_unit=spec.trading_unit,
        min_order_size=spec.min_order_size,
    )


class SHFEAdapter(BaseMarketAdapter):
    """
    Shanghai Futures Exchange market adapter.

    Implements market-specific logic for SHFE metals futures trading,
    including contract management, session handling, and commission calculation.
    """

    def __init__(
        self,
        symbol: str = "al",
        trading_calendar_path: Optional[str] = None,
        days_before_rollover: int = 2,
        market_data_dir: Optional[Path] = None,
    ):
        """
        Initialize SHFE adapter.

        Args:
            symbol: Primary product symbol (e.g., 'al', 'cu')
            trading_calendar_path: Path to trading calendar CSV file
            days_before_rollover: Trading days before contract expiry on which
                to SIGNAL forced exit. Set by EngineFactory.create_market_adapter
                — both backtest and deploy use 1, giving fills on trading day
                T (last trading day before delivery month):
                    backtest interday: hook fires T-1, submits exit, skips
                        strategy.next on T-1, backtrader fills T's open.
                    deploy night-market interday: hook fires 20:30 calendar
                        T-1, runner waits until 21:00 then burst-fires the
                        order via submit_order_async, fills 21:00 calendar
                        T-1 = night-session open of trading day T (per SHFE
                        convention).
                    deploy day-only interday: hook fires 14:55 calendar T-1,
                        order fills before 15:00 calendar T-1 (= same trading
                        day T-1, one day earlier than night-market — accepted
                        as conservative-safe).
                "Expiry" here = last trading day of the month before the
                contract's delivery month (SHFE rule for "must close by").
        """
        super().__init__()

        self._symbol = symbol.lower()
        self._days_before_rollover = days_before_rollover
        # main_contract.csv lives in market_data_dir (alongside trading_calendar.csv
        # and OHLCV). When None, callers surface CFG-003 from the loader on
        # first get_main_contract / get_rollover_target call — fail-loud.
        self._market_data_dir = market_data_dir

        # Load trading calendar
        self._calendar = TradingCalendar(trading_calendar_path)

        # Register contract specs from canonical config source
        for sym, instrument_spec in SHFE_INSTRUMENTS.items():
            contract_spec = instrument_spec_to_contract_spec(instrument_spec)
            self.register_contract_spec(sym, contract_spec)

        # Get sessions for this product
        self._sessions = get_sessions_for_product(self._symbol)

    # =========================================================================
    # Required Properties
    # =========================================================================

    @property
    def market_code(self) -> str:
        """Get SHFE market code."""
        return "SHFE"

    @property
    def market_name(self) -> str:
        """Get full market name."""
        return "Shanghai Futures Exchange"

    @property
    def timezone(self) -> str:
        """Get market timezone."""
        return "Asia/Shanghai"

    @property
    def trading_sessions(self) -> List[SessionWindow]:
        """Get SHFE trading sessions for the configured symbol."""
        return self._sessions

    @property
    def supports_overnight_positions(self) -> bool:
        """SHFE supports overnight positions."""
        return True

    @property
    def has_contract_expiry(self) -> bool:
        """SHFE futures have contract expiry."""
        return True

    @property
    def symbol(self) -> str:
        """Get the primary symbol for this adapter."""
        return self._symbol

    @property
    def calendar(self) -> TradingCalendar:
        """Get the trading calendar."""
        return self._calendar

    # =========================================================================
    # Contract Management
    # =========================================================================

    def get_contract_spec(self, symbol: str) -> ContractSpec:
        """
        Get contract specification for a symbol.

        Args:
            symbol: Product symbol (e.g., 'al', 'cu') or full contract code (e.g., 'al2403')

        Returns:
            ContractSpec for the symbol

        Raises:
            KeyError: If symbol not found
        """
        sym = symbol.lower()

        # Direct lookup for base symbols
        if sym in self._contract_specs:
            return self._contract_specs[sym]

        # Extract base symbol from full contract code (e.g., 'al2403' → 'al')
        # SHFE pattern: 2-letter product code + 4-digit YYMM
        if len(sym) >= 2:
            base_sym = sym[:2]
            if base_sym in self._contract_specs:
                return self._contract_specs[base_sym]

        # Fallback to config source (convert on-the-fly)
        if sym in SHFE_INSTRUMENTS:
            return instrument_spec_to_contract_spec(SHFE_INSTRUMENTS[sym])

        # Try base symbol in config
        if len(sym) >= 2:
            base_sym = sym[:2]
            if base_sym in SHFE_INSTRUMENTS:
                return instrument_spec_to_contract_spec(SHFE_INSTRUMENTS[base_sym])

        raise KeyError(f"Unknown SHFE symbol: {symbol}")

    def get_main_contract(self, trading_date: date, instrument: str = None) -> str:
        """
        Get the main contract code for a trading date.

        SHFE rule: Main contract is 2 months ahead.

        Args:
            trading_date: Date to get main contract for
            instrument: Optional instrument override (uses self._symbol if None)

        Returns:
            Main contract code (e.g., 'al2403')
        """
        sym = instrument.lower() if instrument else self._symbol
        return get_main_contract(trading_date, sym, market_data_dir=self._market_data_dir)

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
        return should_rollover(
            contract,
            trading_date,
            position_size,
            self._calendar,
            self._days_before_rollover
        )

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
        # Use should_rollover to check if rollover is needed
        # (with position_size=1 since we're just checking the date)
        if not should_rollover(current_contract, trading_date, 1, self._calendar, self._days_before_rollover):
            return None

        return contract_get_rollover_target(
            current_contract,
            trading_date,
            1,  # position_size > 0 to allow rollover
            self._calendar,
            market_data_dir=self._market_data_dir,
        )

    def get_expiry_date(self, contract: str) -> date:
        """
        Get the expiry date for a contract.

        Args:
            contract: Contract code

        Returns:
            Expiry date
        """
        return get_expiry_date(contract, self._calendar)

    def get_contract_expiry_date(self, contract: str) -> Optional[date]:
        """
        Get expiry date for a contract.

        Args:
            contract: Contract symbol

        Returns:
            Expiry date
        """
        return get_expiry_date(contract, self._calendar)

    def parse_contract(self, contract: str) -> tuple:
        """
        Parse contract code into components.

        Args:
            contract: Contract code (e.g., 'al2403')

        Returns:
            Tuple of (symbol, year, month)
        """
        return parse_contract(contract)

    # =========================================================================
    # Forward-curve / Chain Composition (Gate 1C WS2 B2.1)
    # =========================================================================

    def get_contract_chain(
        self,
        trading_date: date,
        instrument: Optional[str] = None,
        n_contracts: Optional[int] = None,
    ) -> List[str]:
        """Get active contracts for an instrument on a trading date.

        Delegates to :func:`echolon.data.loaders.chain_composer.get_contract_chain`
        with this adapter's ``market_data_dir``. See chain_composer docstring
        for the "active on date" definition.

        Args:
            trading_date: Date to enumerate the chain for.
            instrument: Optional product override; defaults to ``self._symbol``.
            n_contracts: If given, truncate to the nearest-expiry contracts.

        Returns:
            List of contract codes sorted by expiry ascending (front first).
        """
        from echolon.data.loaders.chain_composer import get_contract_chain as _get_chain
        sym = instrument.lower() if instrument else self._symbol
        return _get_chain(
            sym,
            trading_date,
            market="SHFE",
            market_data_dir=self._market_data_dir,
            n_contracts=n_contracts,
        )

    def get_curve_snapshot(
        self,
        trading_date: date,
        instrument: Optional[str] = None,
        n_contracts: Optional[int] = None,
    ):
        """Build a same-date forward-curve snapshot across the active chain.

        Delegates to :func:`echolon.data.loaders.chain_composer.get_curve_snapshot`
        with this adapter's ``market_data_dir``.

        Args:
            trading_date: Date to snapshot the curve for.
            instrument: Optional product override; defaults to ``self._symbol``.
            n_contracts: If given, truncate to the nearest-expiry contracts.

        Returns:
            DataFrame with one row per active contract — columns include
            ``contract``, ``settlement``, ``expiry_date``, ``days_to_expiry``,
            and the usual OHLCV fields. See chain_composer docstring.
        """
        from echolon.data.loaders.chain_composer import get_curve_snapshot as _get_snap
        sym = instrument.lower() if instrument else self._symbol
        return _get_snap(
            sym,
            trading_date,
            market="SHFE",
            market_data_dir=self._market_data_dir,
            n_contracts=n_contracts,
        )

    # =========================================================================
    # Calendar Methods
    # =========================================================================

    def is_trading_day(self, check_date: date) -> bool:
        """
        Check if a date is a valid SHFE trading day.

        Args:
            check_date: Date to check

        Returns:
            True if trading day
        """
        return self._calendar.is_trading_day(check_date)

    def get_next_trading_day(self, from_date: date) -> date:
        """
        Get the next trading day after the given date.

        Args:
            from_date: Starting date

        Returns:
            Next trading day
        """
        return self._calendar.get_next_trading_day(from_date)

    def get_previous_trading_day(self, from_date: date) -> date:
        """
        Get the previous trading day before the given date.

        Args:
            from_date: Starting date

        Returns:
            Previous trading day
        """
        return self._calendar.get_previous_trading_day(from_date)

    def get_last_trading_day_of_month(self, year: int, month: int) -> date:
        """
        Get the last trading day of a specific month.

        Args:
            year: Year
            month: Month (1-12)

        Returns:
            Last trading day of the month
        """
        return self._calendar.get_last_trading_day_of_month(year, month)

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

        SHFE uses either fixed per-lot or percentage-based commission
        depending on the product.

        Args:
            symbol: Product symbol
            size: Trade size (number of lots)
            price: Trade price

        Returns:
            Commission amount in CNY
        """
        spec = self.get_contract_spec(symbol)
        return spec.calculate_commission(price, size, close_today=close_today)

    def calculate_margin(
        self,
        symbol: str,
        size: int,
        price: float
    ) -> float:
        """
        Calculate required margin for a position.

        Args:
            symbol: Product symbol
            size: Position size
            price: Current price

        Returns:
            Required margin in CNY
        """
        spec = self.get_contract_spec(symbol)
        contract_value = abs(size) * price * spec.multiplier
        return contract_value * spec.margin_rate

    def calculate_contract_value(
        self,
        symbol: str,
        size: int,
        price: float
    ) -> float:
        """
        Calculate total contract value.

        Args:
            symbol: Product symbol
            size: Position size
            price: Current price

        Returns:
            Total contract value in CNY
        """
        spec = self.get_contract_spec(symbol)
        return abs(size) * price * spec.multiplier

    def calculate_pnl(
        self,
        symbol: str,
        size: int,
        entry_price: float,
        exit_price: float
    ) -> float:
        """
        Calculate profit/loss for a trade.

        Args:
            symbol: Product symbol
            size: Position size (positive for long, negative for short)
            entry_price: Entry price
            exit_price: Exit price

        Returns:
            P&L in CNY
        """
        spec = self.get_contract_spec(symbol)
        price_diff = exit_price - entry_price
        return size * price_diff * spec.multiplier

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
        # Calculate precision from tick_size
        if spec.tick_size >= 1:
            return 0
        return abs(int(math.log10(spec.tick_size)))

    def get_size_precision(self, symbol: str) -> int:  # noqa: ARG002
        """
        Get size decimal precision for a symbol.

        Args:
            symbol: Trading symbol (unused - SHFE always uses whole lots)

        Returns:
            Number of decimal places for size
        """
        # SHFE uses whole lot sizes regardless of symbol
        del symbol  # Explicitly mark as unused
        return 0

    def get_session_close_time(self, check_date: date) -> datetime:
        """
        Get the closing time for the trading day.

        Args:
            check_date: Trading date

        Returns:
            Datetime of session close
        """
        # Last session is either night (ends at 23:00) or afternoon (ends at 15:00)
        if self.is_night_session_product():
            return datetime.combine(check_date, NIGHT_SESSION.end)
        return datetime.combine(check_date, AFTERNOON_SESSION.end)

    # =========================================================================
    # Session Context Provider
    # =========================================================================

    def create_session_provider(
        self,
        bar_size_minutes: int = 5,
    ) -> 'ISessionContext':
        """
        Create SHFE session context provider.

        Provides FACTUAL session data. Strategy decides phase thresholds.

        Args:
            bar_size_minutes: Bar size in minutes (default: 5)

        Returns:
            SHFESessionProvider instance
        """
        return SHFESessionProvider(
            market_adapter=self,
            bar_size_minutes=bar_size_minutes,
        )

    # =========================================================================
    # Session Utilities
    # =========================================================================

    def is_session_active(self, check_time: datetime) -> bool:
        """
        Check if current time is within active trading session.

        Args:
            check_time: Datetime to check

        Returns:
            True if within trading hours
        """
        # First check if it's a trading day
        if not self._calendar.is_trading_day(check_time.date()):
            return False

        # Then check if the time is in any session
        current_time = check_time.time()
        for session in self._sessions:
            if session.contains_time(current_time):
                return True
        return False

    def is_night_session_product(self) -> bool:
        """Check if current symbol trades in night session."""
        return self._symbol in NIGHT_SESSION_PRODUCTS

    def get_day_sessions(self) -> List[SessionWindow]:
        """Get day-only sessions (no night session)."""
        return DAY_SESSIONS

    def get_all_sessions(self) -> List[SessionWindow]:
        """Get all sessions including night session."""
        return ALL_SESSIONS

    # =========================================================================
    # Utility Methods
    # =========================================================================

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"SHFEAdapter(symbol={self._symbol}, "
            f"calendar_loaded={self._calendar.is_loaded}, "
            f"sessions={len(self._sessions)})"
        )
