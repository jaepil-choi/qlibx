"""
Trading Calendar Loader
=======================

Provides unified interface for loading trading calendars.
"""
import os
import logging
import pandas as pd
from typing import Optional, List
from datetime import datetime
from pathlib import Path

from echolon.markets.shfe.trading_calendar import TradingCalendar

logger = logging.getLogger(__name__)


def load_trading_calendar(
    market: str,
    asset: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    *,
    market_data_dir: Path,
) -> pd.DataFrame:
    """
    Load trading calendar for a market/asset.

    Args:
        market: Market code (e.g., "SHFE")
        asset: Asset name (e.g., "aluminum")
        start_date: Optional start date filter (YYYY-MM-DD)
        end_date: Optional end date filter (YYYY-MM-DD)
        market_data_dir: Required root directory for processed market data
              (typically ``paths.market_data_dir``). The calendar file is
              resolved as ``{market_data_dir}/{market}/{asset}/trading_calendar.csv``.

    Returns:
        DataFrame with trading calendar
    """
    calendar_file = os.path.join(str(market_data_dir), market, asset, "trading_calendar.csv")

    if not os.path.exists(calendar_file):
        logger.error(f"[CALENDAR_LOADER] File not found: {calendar_file}")
        raise FileNotFoundError(f"Trading calendar not found: {calendar_file}")

    df = pd.read_csv(calendar_file)
    df['date'] = pd.to_datetime(df['date'])

    # Filter to trading days only (new format has is_trading_day column)
    if 'is_trading_day' in df.columns:
        df = df[df['is_trading_day'] == 1]

    # Apply date filters
    if start_date:
        df = df[df['date'] >= pd.to_datetime(start_date)]
    if end_date:
        df = df[df['date'] <= pd.to_datetime(end_date)]

    logger.info(f"[CALENDAR_LOADER] Loaded {len(df)} trading dates | {market}/{asset}")
    return df


def get_trading_dates(
    market: str,
    asset: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    *,
    market_data_dir: Path,
) -> List[datetime]:
    """
    Get list of trading dates for a market/asset.

    Args:
        market: Market code
        asset: Asset name
        start_date: Optional start date filter
        end_date: Optional end date filter
        market_data_dir: Required root directory (typically
              ``paths.market_data_dir``) — passed through to
              ``load_trading_calendar``.

    Returns:
        List of datetime objects representing trading dates
    """
    calendar = load_trading_calendar(
        market, asset, start_date, end_date, market_data_dir=market_data_dir,
    )
    return calendar['date'].tolist()


def is_trading_day(
    market: str,
    asset: str,
    date: datetime,
    *,
    market_data_dir: Path,
) -> bool:
    """
    Check if a specific date is a trading day.

    Args:
        market: Market code
        asset: Asset name
        date: Date to check (time component is ignored)
        market_data_dir: Root directory for processed market data (passed through
              to ``load_trading_calendar``).

    Returns:
        True if the date is a trading day
    """
    calendar = load_trading_calendar(market, asset, market_data_dir=market_data_dir)
    date_normalized = pd.Timestamp(date).normalize()
    return date_normalized in calendar['date'].values


def is_night_market_open(
    market: str,
    asset: str,
    date: datetime,
    *,
    market_data_dir: Optional[Path] = None,
) -> bool:
    """
    Check if the night trading session is open for a given date.

    Reads the raw calendar CSV (unfiltered) so that non-trading days are
    also covered.  Defaults to True when the file is missing, the date is
    not found, or the night_market column is absent.

    Args:
        market: Market code (e.g., "SHFE")
        asset: Asset name (e.g., "aluminum")
        date: Date to check (time component is ignored)
        market_data_dir: Root directory for processed market data
              (typically ``paths.market_data_dir``). Required — missing value
              raises CFG-003.

    Returns:
        True if night market is open (defaults to True on missing data).
    """
    if market.upper() == "EQUITY":
        return False
    if market_data_dir is None:
        from echolon.errors import raise_error
        raise_error(
            "CFG-003",
            function="is_night_market_open",
            param="market_data_dir=",
            paths_field="market_data_dir",
        )
    calendar_file = os.path.join(str(market_data_dir), market, asset, "trading_calendar.csv")

    if not os.path.exists(calendar_file):
        logger.warning(f"[CALENDAR_LOADER] File not found: {calendar_file} — defaulting night market open")
        return True

    df = pd.read_csv(calendar_file)
    df['date'] = pd.to_datetime(df['date'])

    if 'night_market' not in df.columns:
        logger.warning("[CALENDAR_LOADER] No night_market column in calendar — defaulting True")
        return True

    ts = pd.Timestamp(date)
    if ts.tzinfo is not None:
        ts = ts.tz_convert("Asia/Shanghai")
    date_normalized = ts.tz_localize(None).normalize()
    row = df[df['date'] == date_normalized]

    if row.empty:
        logger.warning(f"[CALENDAR_LOADER] Date {date_normalized.date()} not in trading calendar — defaulting night market open")
        return True

    night_market_status = bool(int(row['night_market'].iloc[0]))
    logger.info(
        f"[CALENDAR_LOADER] Night market for {date_normalized.date()}: "
        f"{'Open' if night_market_status else 'Closed'}"
    )
    return night_market_status


def get_trading_calendar_instance(
    market: str,
    asset: str,
    *,
    market_data_dir: Optional[Path] = None,
) -> TradingCalendar:
    """
    Get a TradingCalendar instance loaded with the market/asset calendar.

    This is used by the standardizer to calculate trading_date for intraday data.
    Falls back to weekend-only logic if no calendar file exists.

    Args:
        market: Market code (e.g., "SHFE")
        asset: Asset name (e.g., "aluminum")
        market_data_dir: Root directory for processed market data
              (typically ``paths.market_data_dir``). Required — missing value
              raises CFG-003.

    Returns:
        TradingCalendar instance (loaded from file or with weekend-only fallback)
    """
    if market_data_dir is None:
        from echolon.errors import raise_error
        raise_error(
            "CFG-003",
            function="get_trading_calendar_instance",
            param="market_data_dir=",
            paths_field="market_data_dir",
        )
    calendar_file = Path(market_data_dir) / market.upper() / asset / "trading_calendar.csv"

    calendar = TradingCalendar()

    if calendar_file.exists():
        loaded_count = calendar.load_calendar(str(calendar_file))
        logger.info(
            f"[CALENDAR_LOADER] Loaded TradingCalendar | "
            f"market={market}, asset={asset}, trading_days={loaded_count}"
        )
    else:
        logger.warning(
            f"[CALENDAR_LOADER] No calendar file found at {calendar_file}, "
            f"using weekend-only fallback"
        )

    return calendar
