"""
OHLCV Data Standardizer
=======================

Validates and standardizes OHLCV data to conform to the standard schema.
"""
import logging
from typing import Optional
import pandas as pd

from ..schemas import OHLCVSchema
from echolon.markets.shfe.trading_calendar import TradingCalendar
from echolon.config.markets.shfe.phases import get_phase_for_time as get_session_phase
from echolon.config.markets.shfe.sessions import NIGHT as SHFE_NIGHT_SESSION

logger = logging.getLogger(__name__)

# Night session start time from centralized config
SHFE_NIGHT_SESSION_START = SHFE_NIGHT_SESSION.start


class OHLCVStandardizer:
    """
    Standardizes extracted OHLCV data.

    Responsibilities:
    - Validate required columns exist
    - Convert column types
    - Handle missing values
    - Ensure consistent date format

    Handles both day data and minute data formats:
    - Day data: 'date' column in YYYYMMDD format
    - Minute data: 'time' column in milliseconds since epoch
    """

    # Column name mappings from various source formats to standard names
    COLUMN_MAPPING = {
        # Minute data from xuntou API
        'amount': 'turnover',
        'settelementPrice': 'settlement',
        'openInterest': 'open_interest',
        'preClose': 'prev_close',
        'suspendFlag': 'suspend_flag',
        # Day data from SHFE Excel (already mapped by extractor, but kept for completeness)
        '成交金额': 'turnover',
        '持仓量': 'open_interest',
        '前收盘': 'prev_close',
        '结算价': 'settlement',
        '前结算': 'prev_settlement',
    }

    def __init__(
        self,
        fill_missing: bool = True,
        market: str = "SHFE",
        trading_calendar: Optional[TradingCalendar] = None,
        bar_size: Optional[str] = None,
    ):
        """
        Initialize standardizer.

        Args:
            fill_missing: If True, fill missing OHLCV values using close price
            market: Market code (e.g., "SHFE", "CRYPTO") for market-specific logic
            trading_calendar: Optional TradingCalendar instance for computing trading_date.
                              If None, uses weekend-only fallback for SHFE.
            bar_size: Optional bar size string ('5m', '15m', '30m', '1h').
                      For 30m/1h bars, uses aggregated phases (night_session, day_session).
                      For 5m/15m or None, uses granular phases (night, morning, afternoon).
        """
        self.fill_missing = fill_missing
        self.market = market.upper()
        self.trading_calendar = trading_calendar or TradingCalendar()
        self.bar_size = bar_size

    def standardize(self, df: pd.DataFrame, timezone: str = None) -> pd.DataFrame:
        """
        Standardize a DataFrame to conform to OHLCV schema.

        Args:
            df: Raw extracted DataFrame
            timezone: Target timezone for timestamp conversion (e.g., 'Asia/Shanghai')
                     Required for minute data to convert UTC timestamps to local time

        Returns:
            Standardized DataFrame
        """
        result = df.copy()

        # Step 1: Rename columns to standard names
        result = self._rename_columns(result)

        # Step 2: Handle timestamp conversion (minute data has 'time', not 'date')
        result = self._convert_timestamp(result, timezone=timezone)

        # Step 2b: Add trading_date for intraday data (Tier 2 schema column)
        result = self._add_trading_date(result)

        # Step 2c: Add session_phase for intraday data (Tier 2 schema column)
        result = self._add_session_phase(result)

        # Step 3: Validate required columns
        missing = OHLCVSchema.get_missing_columns(result)
        if missing:
            logger.warning(f"[STANDARDIZER] Missing columns: {missing}")

        # Step 4: Standardize date column
        result = self._standardize_date(result)

        # Step 5: Standardize numeric columns
        result = self._standardize_numerics(result)

        # Step 6: Fill missing OHLCV values
        if self.fill_missing:
            result = self._fill_missing_ohlcv(result)

        # Step 7: Sort by datetime (minute) or date (day)
        if 'datetime' in result.columns:
            result = result.sort_values('datetime').reset_index(drop=True)
        elif 'date' in result.columns:
            result = result.sort_values('date').reset_index(drop=True)

        logger.info(f"[STANDARDIZER] Standardized {len(result)} rows")
        return result

    def _rename_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """Rename columns to standard names."""
        result = df.copy()
        rename_map = {k: v for k, v in self.COLUMN_MAPPING.items() if k in result.columns}
        if rename_map:
            result = result.rename(columns=rename_map)
            logger.debug(f"[STANDARDIZER] Renamed columns: {list(rename_map.keys())}")
        return result

    def _convert_timestamp(self, df: pd.DataFrame, timezone: str = None) -> pd.DataFrame:
        """
        Convert millisecond timestamp to date and datetime columns.

        Minute data has 'time' column with milliseconds since epoch (UTC).
        This converts it to local timezone if specified.

        Args:
            df: DataFrame with 'time' column in milliseconds
            timezone: Target timezone (e.g., 'Asia/Shanghai' for SHFE, 'UTC' for crypto)
                     If None, timestamps are treated as-is (no conversion)
        """
        if 'time' not in df.columns:
            return df

        result = df.copy()

        # Check if 'time' is milliseconds timestamp (large integer)
        if result['time'].dtype in ['int64', 'float64'] and result['time'].iloc[0] > 1e12:
            if timezone:
                # Convert milliseconds (UTC) to target timezone
                dt_utc = pd.to_datetime(result['time'], unit='ms', utc=True)
                # Convert to local timezone and remove timezone info (make naive)
                result['datetime'] = dt_utc.dt.tz_convert(timezone).dt.tz_localize(None)
                logger.debug(f"[STANDARDIZER] Converted 'time' (UTC ms) to '{timezone}'")
            else:
                # No timezone conversion - treat as-is
                result['datetime'] = pd.to_datetime(result['time'], unit='ms')
                logger.debug("[STANDARDIZER] Converted 'time' (ms) to datetime (no tz conversion)")

            result['date'] = result['datetime'].dt.normalize()

        return result

    def _add_trading_date(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Add trading_date column for intraday data (Tier 2 schema column).

        For SHFE intraday data, trading_date differs from calendar date:
        - Night session bars (21:00-23:59) belong to the NEXT trading day's session
        - Bars after midnight (00:00-01:00) and day session (09:00-15:00) use same calendar date

        Uses TradingCalendar to correctly handle weekends and holidays.

        Example:
        - Bar at 2022-12-16 (Friday) 21:40:00 → trading_date = 20221219 (Monday, next trading day)
        - Bar at 2022-12-19 00:30:00 → trading_date = 20221219 (same trading session)
        - Bar at 2022-12-19 09:30:00 → trading_date = 20221219 (day session)

        Args:
            df: DataFrame with 'datetime' column

        Returns:
            DataFrame with 'trading_date' column added (YYYYMMDD string format)
        """
        if 'datetime' not in df.columns:
            # Not intraday data, skip
            return df

        result = df.copy()

        if self.market == "SHFE":
            # For SHFE: bars at 21:00+ belong to next trading day's session
            bar_times = result['datetime'].dt.time
            is_night_session = bar_times >= SHFE_NIGHT_SESSION_START

            # Calculate trading_date for each row
            def get_trading_date(row_datetime, is_night: bool) -> str:
                calendar_date = row_datetime.date()
                if is_night:
                    # Night session: use next trading day
                    trading_day = self.trading_calendar.get_next_trading_day(calendar_date)
                else:
                    # Day session or after midnight: use calendar date
                    trading_day = calendar_date
                return trading_day.strftime('%Y%m%d')

            # Apply to all rows
            result['trading_date'] = [
                get_trading_date(dt, is_night)
                for dt, is_night in zip(result['datetime'], is_night_session)
            ]

            night_count = is_night_session.sum()
            if night_count > 0:
                logger.debug(
                    f"[STANDARDIZER] Added trading_date for SHFE | "
                    f"night_session_bars={night_count}, total={len(result)}"
                )
        else:
            # For other markets (e.g., crypto 24/7), trading_date = calendar date
            result['trading_date'] = result['datetime'].dt.strftime('%Y%m%d')
            logger.debug(f"[STANDARDIZER] Added trading_date for {self.market} (calendar date)")

        return result

    def _add_session_phase(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Add session_phase column for intraday data (Tier 2 schema column).

        Classifies each bar into session phases using the centralized session
        phase definitions from config/markets.py.

        Phase names depend on bar_size:
        - For 5m/15m (or None): 'night', 'morning', 'afternoon' (granular)
        - For 30m/1h: 'night_session', 'day_session' (aggregated)

        Args:
            df: DataFrame with 'datetime' column

        Returns:
            DataFrame with 'session_phase' column added
        """
        if 'datetime' not in df.columns:
            # Not intraday data, skip
            return df

        result = df.copy()

        if self.market == "SHFE":
            # Use centralized get_session_phase function with bar_size for phase selection
            # Extract time component since get_session_phase expects datetime.time, not Timestamp
            result['session_phase'] = result['datetime'].apply(
                lambda dt: get_session_phase(dt.time(), bar_size=self.bar_size)
            )

            # Count phase distribution for logging
            phase_counts = result['session_phase'].value_counts()
            null_count = result['session_phase'].isna().sum()

            if null_count > 0:
                logger.warning(
                    f"[STANDARDIZER] {null_count} bars have no session_phase (outside trading hours)"
                )

            phase_type = "aggregated" if self.bar_size in ('30m', '1h') else "granular"
            logger.debug(
                f"[STANDARDIZER] Added session_phase for SHFE ({phase_type}) | "
                f"phases={len(phase_counts)}, outside_hours={null_count}"
            )
        else:
            # For other markets, session_phase is not applicable
            logger.debug(f"[STANDARDIZER] session_phase not applicable for {self.market}")

        return result

    def _standardize_date(self, df: pd.DataFrame) -> pd.DataFrame:
        """Convert date column to datetime."""
        if 'date' not in df.columns:
            return df

        result = df.copy()

        # Handle integer dates (YYYYMMDD format)
        if result['date'].dtype in ['int64', 'float64', 'Int64']:
            result['date'] = pd.to_datetime(
                result['date'].astype(str),
                format='%Y%m%d',
                errors='coerce'
            )
        elif result['date'].dtype == 'object':
            # Try multiple formats
            result['date'] = pd.to_datetime(result['date'], errors='coerce')

        return result

    def _standardize_numerics(self, df: pd.DataFrame) -> pd.DataFrame:
        """Convert numeric columns to proper types."""
        result = df.copy()

        numeric_cols = ['open', 'high', 'low', 'close', 'volume',
                       'settlement', 'prev_close', 'prev_settlement',
                       'open_interest', 'turnover']

        for col in numeric_cols:
            if col in result.columns:
                result[col] = pd.to_numeric(result[col], errors='coerce')

        return result

    def _fill_missing_ohlcv(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Fill missing OHLCV values using close price.

        For rows with missing open/high/low, use close price from same row.
        """
        result = df.copy()

        if 'close' not in result.columns:
            return result

        # Fill missing open with close
        if 'open' in result.columns:
            mask = result['open'].isna()
            result.loc[mask, 'open'] = result.loc[mask, 'close']

        # Fill missing high with close
        if 'high' in result.columns:
            mask = result['high'].isna()
            result.loc[mask, 'high'] = result.loc[mask, 'close']

        # Fill missing low with close
        if 'low' in result.columns:
            mask = result['low'].isna()
            result.loc[mask, 'low'] = result.loc[mask, 'close']

        return result

    def validate(self, df: pd.DataFrame) -> bool:
        """
        Validate DataFrame conforms to schema.

        Args:
            df: DataFrame to validate

        Returns:
            True if valid
        """
        return OHLCVSchema.validate(df)
