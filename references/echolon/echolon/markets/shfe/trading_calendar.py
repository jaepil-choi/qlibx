"""
SHFE Trading Calendar
=====================

Trading calendar management for Shanghai Futures Exchange.

Module-level helpers:
- get_previous_trading_day(date): Get previous valid trading day
- get_last_trading_day_of_month(year, month): For contract expiry

Calendar data:
- Excludes weekends
- Excludes Chinese public holidays
- Excludes SHFE-specific closures
- Updated annually with new holiday schedule

Data source:
- data/market_data/shfe/trading_calendar.csv
- Or fallback to weekend-only exclusion

Used by:
- SHFEAdapter.is_trading_day()
- Contract expiry calculations
- Session scheduling
"""

import csv
from datetime import date, timedelta
from pathlib import Path
from typing import Optional, Set, List
from calendar import monthrange


class TradingCalendar:
    """
    SHFE trading calendar manager.

    Provides trading day lookups and calculations with support for
    Chinese holidays and exchange-specific closures.
    """

    def __init__(self, calendar_path: Optional[str] = None):
        """
        Initialize trading calendar.

        Args:
            calendar_path: Path to CSV file with trading dates.
                           If None, uses weekend-only exclusion.
        """
        self._trading_days: Set[date] = set()
        self._calendar_loaded = False

        if calendar_path:
            self.load_calendar(calendar_path)

    def load_calendar(self, path: str) -> int:
        """
        Load trading calendar from CSV file.

        Expected CSV format:
        - Column: 'date' (YYYYMMDD or YYYY-MM-DD format)
        - Optional column: 'is_trading_day' (True/False or 1/0)

        If 'is_trading_day' column exists, only dates marked as trading days
        are loaded. Otherwise, all dates in the file are considered trading days.

        Args:
            path: Path to CSV file

        Returns:
            Number of trading days loaded
        """
        file_path = Path(path)
        if not file_path.exists():
            return 0

        self._trading_days.clear()

        with open(file_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Handle different column names
                date_str = row.get('date') or row.get('trading_date') or row.get('Date')
                if not date_str:
                    continue

                # Parse date
                parsed_date = self._parse_date(date_str)
                if not parsed_date:
                    continue

                # Check is_trading_day column if present
                is_trading = row.get('is_trading_day', 'True')
                if isinstance(is_trading, str):
                    is_trading = is_trading.lower() in ('true', '1', 'yes')

                if is_trading:
                    self._trading_days.add(parsed_date)

        self._calendar_loaded = len(self._trading_days) > 0
        return len(self._trading_days)

    def _parse_date(self, date_str: str) -> Optional[date]:
        """Parse date string in various formats."""
        date_str = str(date_str).strip()

        # Try YYYYMMDD format
        if len(date_str) == 8 and date_str.isdigit():
            return date(int(date_str[:4]), int(date_str[4:6]), int(date_str[6:8]))

        # Try YYYY-MM-DD or YYYY/MM/DD format
        for sep in ['-', '/']:
            if sep in date_str:
                parts = date_str.split(sep)
                if len(parts) == 3:
                    return date(int(parts[0]), int(parts[1]), int(parts[2]))

        return None

    def is_trading_day(self, check_date: date) -> bool:
        """
        Check if a date is a valid trading day.

        Args:
            check_date: Date to check

        Returns:
            True if trading day, False otherwise
        """
        if self._calendar_loaded:
            return check_date in self._trading_days

        # Fallback: Weekend exclusion only
        return check_date.weekday() < 5  # Monday=0, Friday=4

    def get_next_trading_day(self, from_date: date) -> date:
        """
        Get the next trading day after the given date.

        Args:
            from_date: Starting date (exclusive)

        Returns:
            Next trading day
        """
        current = from_date + timedelta(days=1)
        max_iterations = 30  # Safety limit

        for _ in range(max_iterations):
            if self.is_trading_day(current):
                return current
            current += timedelta(days=1)

        # Should not reach here in normal operation
        return current

    def get_previous_trading_day(self, from_date: date) -> date:
        """
        Get the previous trading day before the given date.

        Args:
            from_date: Starting date (exclusive)

        Returns:
            Previous trading day
        """
        current = from_date - timedelta(days=1)
        max_iterations = 30  # Safety limit

        for _ in range(max_iterations):
            if self.is_trading_day(current):
                return current
            current -= timedelta(days=1)

        # Should not reach here in normal operation
        return current

    def get_last_trading_day_of_month(self, year: int, month: int) -> date:
        """
        Get the last trading day of a specific month.

        Used for contract expiry calculations.

        Args:
            year: Year
            month: Month (1-12)

        Returns:
            Last trading day of the month
        """
        # Get the last day of the month
        last_day = monthrange(year, month)[1]
        check_date = date(year, month, last_day)

        # Walk backwards to find last trading day
        while not self.is_trading_day(check_date) and check_date.day > 1:
            check_date -= timedelta(days=1)

        return check_date

    def get_first_trading_day_of_month(self, year: int, month: int) -> date:
        """
        Get the first trading day of a specific month.

        Args:
            year: Year
            month: Month (1-12)

        Returns:
            First trading day of the month
        """
        check_date = date(year, month, 1)

        # Walk forward to find first trading day
        while not self.is_trading_day(check_date) and check_date.month == month:
            check_date += timedelta(days=1)

        return check_date

    def get_trading_days_between(
        self,
        start_date: date,
        end_date: date,
        inclusive: bool = True
    ) -> List[date]:
        """
        Get list of trading days between two dates.

        Args:
            start_date: Start date
            end_date: End date
            inclusive: If True, includes start and end dates if they are trading days

        Returns:
            List of trading days [oldest, ..., newest]
        """
        trading_days = []
        current = start_date

        while current <= end_date:
            if self.is_trading_day(current):
                if inclusive or (current != start_date and current != end_date):
                    trading_days.append(current)
            current += timedelta(days=1)

        return trading_days

    def count_trading_days_between(
        self,
        start_date: date,
        end_date: date,
        inclusive: bool = True
    ) -> int:
        """
        Count trading days between two dates.

        Args:
            start_date: Start date
            end_date: End date
            inclusive: If True, includes start and end dates in count

        Returns:
            Number of trading days
        """
        return len(self.get_trading_days_between(start_date, end_date, inclusive))

    @property
    def is_loaded(self) -> bool:
        """Check if calendar has been loaded from file."""
        return self._calendar_loaded

    @property
    def total_trading_days(self) -> int:
        """Get total number of trading days in loaded calendar."""
        return len(self._trading_days)


# =============================================================================
# Module-level functions used by contract_rules.py
# =============================================================================


def get_previous_trading_day(from_date: date, calendar: Optional[TradingCalendar] = None) -> date:
    """
    Get the previous trading day before the given date.

    Args:
        from_date: Starting date (exclusive)
        calendar: Optional calendar instance

    Returns:
        Previous trading day
    """
    cal = calendar if calendar is not None else TradingCalendar()
    return cal.get_previous_trading_day(from_date)


def get_last_trading_day_of_month(
    year: int,
    month: int,
    calendar: Optional[TradingCalendar] = None
) -> date:
    """
    Get the last trading day of a specific month.

    Args:
        year: Year
        month: Month (1-12)
        calendar: Optional calendar instance

    Returns:
        Last trading day of the month
    """
    cal = calendar if calendar is not None else TradingCalendar()
    return cal.get_last_trading_day_of_month(year, month)
