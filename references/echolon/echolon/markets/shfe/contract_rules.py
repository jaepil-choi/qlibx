"""
SHFE Contract Rules
===================

Contract expiry and rollover logic for SHFE futures.

Public functions:
- parse_contract(contract_str): Parse "al2403" into (symbol, year, month)
- get_expiry_date(contract_str): Calculate expiry date for contract
- get_main_contract(trading_date, symbol): Resolve main contract from CSV
- should_rollover(contract_str, check_date, position_size): Rollover decision
- get_rollover_target(current_contract, check_date, position_size): Next contract

SHFE expiry rules:
- Delivery month: The month in the contract name (al2403 → March 2024)
- Last trading day: 15th of delivery month (or prior business day)
- Position must close: By last trading day of month BEFORE delivery month
- Example: al2403 position must close by end of February 2024

Rollover strategy:
- Monitor current contract's proximity to expiry
- Signal rollover when position should move to next main contract
- Coordinate with trading_calendar.py for valid trading days
"""

import re
from datetime import date
from typing import Dict, Optional, Tuple
from pathlib import Path

import pandas as pd

from echolon.errors import raise_error
from .trading_calendar import TradingCalendar, get_last_trading_day_of_month

# Cache for main contract data to avoid repeated file reads.
# Keyed by (symbol_lower, str(resolved market_data_dir)) so different injected
# market-data directories don't collide on re-entry.
_main_contract_cache: Dict[Tuple[str, str], pd.DataFrame] = {}


def parse_contract(contract_str: str) -> Tuple[str, int, int]:
    """
    Parse contract code into components.

    Args:
        contract_str: Contract code (e.g., 'al2403', 'cu2405')

    Returns:
        Tuple of (symbol, year, month)
        - symbol: Product code (e.g., 'al', 'cu')
        - year: Full year (e.g., 2024)
        - month: Month (1-12)

    Raises:
        ValueError: If contract string is invalid

    Examples:
        >>> parse_contract('al2403')
        ('al', 2024, 3)
        >>> parse_contract('cu2512')
        ('cu', 2025, 12)
    """
    # Pattern: letters followed by 4 digits (YYMM)
    match = re.match(r'^([a-zA-Z]+)(\d{4})$', contract_str.strip())
    if not match:
        raise ValueError(f"Invalid contract format: {contract_str}")

    symbol = match.group(1).lower()
    yymm = match.group(2)

    year_2digit = int(yymm[:2])
    month = int(yymm[2:4])

    # Validate month
    if month < 1 or month > 12:
        raise ValueError(f"Invalid month in contract: {contract_str}")

    # Convert 2-digit year to 4-digit year
    # Assume years 00-50 are 2000-2050, years 51-99 are 1951-1999
    if year_2digit <= 50:
        year = 2000 + year_2digit
    else:
        year = 1900 + year_2digit

    return symbol, year, month


def get_expiry_date(
    contract_str: str,
    calendar: Optional[TradingCalendar] = None
) -> date:
    """
    Calculate the expiry date for a contract.

    SHFE rule: Position must be closed by the last trading day
    of the month BEFORE the delivery month.

    Args:
        contract_str: Contract code (e.g., 'al2403')
        calendar: Optional trading calendar for accurate date calculation

    Returns:
        Expiry date (last day position can be held)

    Examples:
        >>> get_expiry_date('al2403')  # March 2024 delivery
        date(2024, 2, 29)  # Last trading day of February 2024
    """
    _, year, month = parse_contract(contract_str)

    # Get the month before delivery month
    if month == 1:
        expiry_year = year - 1
        expiry_month = 12
    else:
        expiry_year = year
        expiry_month = month - 1

    # Get last trading day of expiry month
    return get_last_trading_day_of_month(expiry_year, expiry_month, calendar)


def _get_rollover_signal_date(
    contract_str: str,
    days_before_expiry: int = 2,
    calendar: Optional[TradingCalendar] = None
) -> date:
    """
    Get the date when rollover should be signaled.

    This is typically 1-2 trading days before expiry to ensure
    the position can be rolled smoothly.
    """
    expiry_date = get_expiry_date(contract_str, calendar)

    # Walk back trading days
    signal_date = expiry_date
    if calendar:
        for _ in range(days_before_expiry):
            signal_date = calendar.get_previous_trading_day(signal_date)
    else:
        # Fallback: simple day subtraction (may land on weekend)
        from .trading_calendar import get_previous_trading_day
        for _ in range(days_before_expiry):
            signal_date = get_previous_trading_day(signal_date, calendar)

    return signal_date


def _load_main_contract_data(
    symbol: str,
    market_data_dir: Optional[Path] = None,
) -> pd.DataFrame:
    """
    Load main contract data from CSV file.

    main_contract.csv is a derived market-data artifact (same kind as
    trading_calendar.csv) and lives at::

        {market_data_dir}/SHFE/{instrument_name}/main_contract.csv

    Host code that produces main_contract.csv elsewhere is responsible for
    placing it at this path before calling echolon's backtest pipeline.

    Args:
        symbol: Product symbol (e.g., 'al', 'cu', 'rb') — instrument CODE.
            Resolved to instrument name via MarketFactory.
        market_data_dir: Required base market-data directory (typically
            ``paths.market_data_dir``).

    Returns:
        DataFrame with 'date' and 'main_contract' columns

    Raises:
        EchelonError (CFG-003): If market_data_dir is None.
        EchelonError (DAT-003): If main_contract.csv is missing.
    """
    global _main_contract_cache

    symbol_lower = symbol.lower()

    if market_data_dir is None:
        raise_error(
            "CFG-003",
            function="get_main_contract / contract_rules._load_main_contract_data",
            param="market_data_dir=",
            paths_field="market_data_dir",
        )
    market_data_dir = Path(market_data_dir).resolve()

    cache_key = (symbol_lower, str(market_data_dir))
    if cache_key in _main_contract_cache:
        return _main_contract_cache[cache_key]

    # Resolve instrument name from code via MarketFactory so the path is
    # always {market_data_dir}/SHFE/{instrument_name}/main_contract.csv
    # (co-located with sort_by_contract/, sort_by_date.csv, trading_calendar.csv).
    from echolon.config.markets.factory import MarketFactory
    spec = MarketFactory.get_instrument_flexible("SHFE", symbol_lower)
    if spec is None:
        raise_error("DAT-003", path=f"<unknown-instrument:{symbol}>", symbol=symbol)
    csv_path = market_data_dir / "SHFE" / spec.name.lower() / "main_contract.csv"

    if not csv_path.exists():
        raise_error("DAT-003", path=str(csv_path), symbol=symbol)

    df = pd.read_csv(csv_path)
    df['date'] = pd.to_datetime(df['date']).dt.date
    df = df.sort_values('date').reset_index(drop=True)

    _main_contract_cache[cache_key] = df
    return df


def get_main_contract(
    trading_date: date,
    symbol: str,
    market_data_dir: Optional[Path] = None,
) -> str:
    """
    Get the main contract code for a given trading date.

    Looks up the main contract from main_contract.csv at::

        {market_data_dir}/SHFE/{instrument_name}/main_contract.csv

    Args:
        trading_date: The trading date
        symbol: Product symbol (e.g., 'al', 'cu', 'rb')
        market_data_dir: Required base market-data directory (typically
            ``paths.market_data_dir``). Missing value raises CFG-003.

    Returns:
        Main contract code (e.g., 'al2403', 'rb2410')

    Raises:
        EchelonError (CFG-003): If market_data_dir is None.
        EchelonError (DAT-003): If main_contract.csv is missing.
        ValueError: If no main contract data available for the date.

    Examples:
        >>> get_main_contract(date(2024, 1, 15), 'al',
        ...                   market_data_dir=paths.market_data_dir)
        'al2403'
    """
    df = _load_main_contract_data(symbol, market_data_dir=market_data_dir)

    # Find the most recent entry on or before trading_date
    mask = df['date'] <= trading_date
    if not mask.any():
        raise ValueError(
            f"No main contract data available for {symbol} on or before {trading_date}. "
            f"Earliest data: {df['date'].min()}"
        )

    # Get the last row where date <= trading_date
    idx = df.loc[mask, 'date'].idxmax()
    main_contract_raw = df.loc[idx, 'main_contract']

    # Remove exchange suffix (e.g., '.SF') if present
    if '.' in main_contract_raw:
        main_contract = main_contract_raw.split('.')[0]
    else:
        main_contract = main_contract_raw

    return main_contract.lower()


def should_rollover(
    contract_str: str,
    check_date: date,
    position_size: int,
    calendar: Optional[TradingCalendar] = None,
    days_before_expiry: int = 2
) -> bool:
    """
    Determine if a position should be rolled over.

    Args:
        contract_str: Current contract code
        check_date: Current date
        position_size: Current position size (0 = no position)
        calendar: Optional trading calendar
        days_before_expiry: Days before expiry to signal rollover

    Returns:
        True if position should be rolled

    Examples:
        >>> should_rollover('al2403', date(2024, 2, 27), 10)
        True  # If signal date is Feb 27
    """
    # No position = no need to roll
    if position_size == 0:
        return False

    signal_date = _get_rollover_signal_date(contract_str, days_before_expiry, calendar)
    return check_date >= signal_date


def get_rollover_target(
    current_contract: str,
    check_date: date,
    position_size: int,
    calendar: Optional[TradingCalendar] = None,
    market_data_dir: Optional[Path] = None,
) -> Optional[str]:
    """
    Get the target contract for rollover.

    Args:
        current_contract: Current contract code
        check_date: Current date
        position_size: Current position size
        calendar: Optional trading calendar
        market_data_dir: Required base market-data directory forwarded to
            get_main_contract (typically ``paths.market_data_dir``).

    Returns:
        Target contract code, or None if no rollover needed

    Examples:
        >>> get_rollover_target('al2403', date(2024, 2, 27), 10,
        ...                     market_data_dir=paths.market_data_dir)
        'al2404'  # If rollover is needed
    """
    if not should_rollover(current_contract, check_date, position_size, calendar):
        return None

    # Get the main contract for current date (which would be the next contract)
    symbol, _, _ = parse_contract(current_contract)
    return get_main_contract(check_date, symbol, market_data_dir=market_data_dir)
