"""
Trading Calendar Generator
==========================

Generates trading calendar from OHLCV data.
"""
import os
import logging
from pathlib import Path
from typing import Optional, List
from datetime import datetime
import pandas as pd

from echolon.errors import raise_error

logger = logging.getLogger(__name__)


class CalendarGenerator:
    """
    Generates trading calendar from market data.

    Responsibilities:
    - Extract unique trading dates from data
    - Filter by date range
    - Save calendar to file

    Important: For intraday data with epoch timestamps (UTC), the timezone
    parameter must be specified to correctly extract local calendar dates.
    Without timezone conversion, after-midnight bars (00:00-01:00 local time)
    would be assigned to the previous UTC day, creating incorrect calendar dates.
    """

    def __init__(
        self,
        output_dir: str,
        date_column: str = "date",
        timezone: str = None
    ):
        """
        Initialize generator.

        Args:
            output_dir: Directory to save calendar file
            date_column: Name of date column
            timezone: Timezone for epoch timestamp conversion (e.g., 'Asia/Shanghai').
                      Required for correct date extraction from intraday minute data.
        """
        self.output_dir = Path(output_dir)
        self.date_column = date_column
        self.timezone = timezone

    def _find_date_column(self, df: pd.DataFrame) -> Optional[str]:
        """
        Find the appropriate date column in the DataFrame.

        Priority:
        1. Configured date_column (default: 'date')
        2. 'time' column (epoch milliseconds from raw data)
        3. 'datetime' column

        Args:
            df: DataFrame to search

        Returns:
            Column name or None if not found
        """
        # Check configured column first
        if self.date_column in df.columns:
            return self.date_column

        # Check common alternatives
        for col in ['time', 'datetime', 'timestamp']:
            if col in df.columns:
                logger.info(f"[CALENDAR] Using '{col}' column for date extraction")
                return col

        return None

    def generate(
        self,
        df: pd.DataFrame = None,
        input_file: str = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        output_filename: str = "trading_calendar.csv"
    ) -> pd.DataFrame:
        """
        Generate trading calendar from data.

        Args:
            df: DataFrame with trading data (optional if input_file provided)
            input_file: Path to CSV file to load (used if df not provided)
            start_date: Filter dates from this date (YYYY-MM-DD)
            end_date: Filter dates until this date (YYYY-MM-DD)
            output_filename: Name of output calendar file

        Returns:
            DataFrame with trading calendar
        """
        # Load data if not provided
        if df is None and input_file:
            if not os.path.exists(input_file):
                logger.error(f"[CALENDAR] File not found: {input_file}")
                df = pd.DataFrame()
            else:
                df = pd.read_csv(input_file)

        if df is None or df.empty:
            logger.error("[CALENDAR] No data provided")
            dates = []
            date_col = None
        else:
            # Determine which column to use for dates
            date_col = self._find_date_column(df)
            if date_col is None:
                logger.error(f"[CALENDAR] No date column found. Available: {list(df.columns)}")
                dates = []
            else:
                # Get unique dates
                dates = df[date_col].unique()

        # Convert to datetime based on column type
        if date_col is None or len(dates) == 0:
            dates_dt = []
        else:
            col_dtype = df[date_col].dtype
            if date_col == 'time':
                # Epoch milliseconds - convert to dates
                # CRITICAL: Must apply timezone conversion to get correct local dates
                # Without this, after-midnight bars (00:00-01:00 local) would be
                # assigned to the previous UTC day (e.g., Monday 00:30 Shanghai
                # = Sunday 16:30 UTC → would incorrectly create Sunday as calendar date)
                # Convert UTC epoch to local timezone, then extract date
                dates_dt = [
                    pd.to_datetime(int(d), unit='ms', utc=True)
                        .tz_convert(self.timezone)
                        .normalize()
                        .tz_localize(None)  # Remove tz info after normalization
                    for d in dates if pd.notna(d)
                ]
                logger.debug(f"[CALENDAR] Converted epoch timestamps using timezone: {self.timezone}")

                # Remove duplicates after converting to date
                dates_dt = list(set(dates_dt))
            elif col_dtype in ['int64', 'float64', 'Int64']:
                # Integer format (YYYYMMDD)
                dates_dt = [
                    pd.to_datetime(str(int(d)), format='%Y%m%d')
                    for d in dates if pd.notna(d)
                ]
            else:
                # Already datetime or string
                dates_dt = pd.to_datetime(dates).tolist()

        # Sort dates
        dates_dt = sorted([d for d in dates_dt if pd.notna(d)])

        # Filter by date range
        if start_date:
            start_dt = pd.to_datetime(start_date)
            dates_dt = [d for d in dates_dt if d >= start_dt]
            logger.info(f"[CALENDAR] Filtered from {start_date}")

        if end_date:
            end_dt = pd.to_datetime(end_date)
            dates_dt = [d for d in dates_dt if d <= end_dt]
            logger.info(f"[CALENDAR] Filtered until {end_date}")

        # Create calendar DataFrame
        calendar = pd.DataFrame({
            'date': dates_dt,
            'is_trading_day': True
        })

        if calendar.empty:
            raise_error(
                "DAT-004",
                market=getattr(self, "market", "<unknown>"),
                instrument=getattr(self, "instrument", "<unknown>"),
                start_date=str(start_date),
                end_date=str(end_date),
                rows_seen=len(df) if df is not None else 0,
            )

        # Save to file
        self.output_dir.mkdir(parents=True, exist_ok=True)
        output_path = self.output_dir / output_filename
        calendar.to_csv(output_path, index=False)

        logger.info(f"[CALENDAR] Generated {len(calendar)} trading dates: {output_path}")
        return calendar

    def get_trading_dates(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> List[datetime]:
        """
        Load and return trading dates from saved calendar.

        Args:
            start_date: Filter from date
            end_date: Filter until date

        Returns:
            List of trading dates
        """
        calendar_path = self.output_dir / "trading_calendar.csv"

        if not calendar_path.exists():
            logger.warning(f"[CALENDAR] Calendar not found: {calendar_path}")
            return []

        df = pd.read_csv(calendar_path)
        df['date'] = pd.to_datetime(df['date'])

        dates = df['date'].tolist()

        if start_date:
            start_dt = pd.to_datetime(start_date)
            dates = [d for d in dates if d >= start_dt]

        if end_date:
            end_dt = pd.to_datetime(end_date)
            dates = [d for d in dates if d <= end_dt]

        return dates
