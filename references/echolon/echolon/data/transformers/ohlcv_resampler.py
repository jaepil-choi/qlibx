"""
OHLCV Data Resampler
====================

Resamples minute-level OHLCV data to a target frequency (e.g., 5m, 15m, 1h).
"""
import logging
import pandas as pd
from typing import Optional

logger = logging.getLogger(__name__)


class OHLCVResampler:
    """
    Resamples OHLCV data from source frequency to target frequency.

    For example, converts 1-minute bars to 5-minute bars by:
    - open: first value in the period
    - high: maximum value in the period
    - low: minimum value in the period
    - close: last value in the period
    - volume: sum of all values in the period
    - turnover: sum of all values in the period
    - open_interest: last value in the period
    """

    # Aggregation rules for OHLCV columns
    AGGREGATION_RULES = {
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum',
        'turnover': 'sum',
        'open_interest': 'last',
        'settlement': 'last',
        'prev_close': 'first',
        'prev_settlement': 'first',
    }

    # Pandas frequency aliases
    FREQUENCY_MAP = {
        '1m': '1min',
        '5m': '5min',
        '15m': '15min',
        '30m': '30min',
        '1h': '1h',
        '4h': '4h',
        '1d': '1D',
        # Also support full names
        '1min': '1min',
        '5min': '5min',
        '15min': '15min',
        '30min': '30min',
    }

    def __init__(self, target_frequency: str):
        """
        Initialize resampler.

        Args:
            target_frequency: Target bar size (e.g., '5m', '15m', '1h')
        """
        self.target_frequency = target_frequency
        self.pandas_freq = self._normalize_frequency(target_frequency)

    def _normalize_frequency(self, freq: str) -> str:
        """Convert frequency string to pandas-compatible format."""
        freq_lower = freq.lower()
        if freq_lower in self.FREQUENCY_MAP:
            return self.FREQUENCY_MAP[freq_lower]
        # Default: return as-is and let pandas handle it
        return freq

    def resample(
        self,
        df: pd.DataFrame,
        datetime_column: str = 'datetime',
        group_column: Optional[str] = 'contract'
    ) -> pd.DataFrame:
        """
        Resample OHLCV data to target frequency.

        Args:
            df: DataFrame with OHLCV data and datetime column
            datetime_column: Name of datetime column for resampling
            group_column: Column to group by before resampling (e.g., 'contract')

        Returns:
            Resampled DataFrame
        """
        if datetime_column not in df.columns:
            logger.warning(f"[RESAMPLER] Column '{datetime_column}' not found, skipping resample")
            return df

        # Check if resampling is needed (1m to 1m = no-op)
        if self.target_frequency in ('1m', '1min'):
            logger.info("[RESAMPLER] Target is 1m, no resampling needed")
            return df

        result = df.copy()

        # Ensure datetime column is proper datetime type
        if not pd.api.types.is_datetime64_any_dtype(result[datetime_column]):
            result[datetime_column] = pd.to_datetime(result[datetime_column])

        # Build aggregation dict for available columns
        agg_dict = {}
        for col, agg_func in self.AGGREGATION_RULES.items():
            if col in result.columns:
                agg_dict[col] = agg_func

        # Add pass-through for other columns (take first value)
        for col in result.columns:
            if col not in agg_dict and col not in [datetime_column, group_column, 'time', 'date']:
                agg_dict[col] = 'first'

        logger.info(f"[RESAMPLER] Resampling to {self.target_frequency} ({self.pandas_freq})")

        if group_column and group_column in result.columns:
            # Resample per contract
            resampled_groups = []
            for contract, group_df in result.groupby(group_column):
                resampled = self._resample_group(
                    group_df,
                    datetime_column,
                    agg_dict
                )
                resampled[group_column] = contract
                resampled_groups.append(resampled)

            if resampled_groups:
                result = pd.concat(resampled_groups, ignore_index=True)
            else:
                result = pd.DataFrame()
        else:
            # Resample all data together
            result = self._resample_group(result, datetime_column, agg_dict)

        # Regenerate date column from datetime
        if 'datetime' in result.columns:
            result['date'] = pd.to_datetime(result['datetime']).dt.normalize()

        logger.info(f"[RESAMPLER] Resampled to {len(result)} rows")
        return result

    def _resample_group(
        self,
        df: pd.DataFrame,
        datetime_column: str,
        agg_dict: dict
    ) -> pd.DataFrame:
        """Resample a single group (or entire DataFrame)."""
        # Set datetime as index for resampling
        df_indexed = df.set_index(datetime_column)

        # Resample using pandas
        resampled = df_indexed.resample(self.pandas_freq).agg(agg_dict)

        # Drop rows with all NaN (periods with no data)
        resampled = resampled.dropna(subset=['close'])

        # Reset index to get datetime back as column
        resampled = resampled.reset_index()
        resampled = resampled.rename(columns={'index': datetime_column})

        return resampled

    def get_source_frequency(self, df: pd.DataFrame, datetime_column: str = 'datetime') -> str:
        """
        Detect the source frequency from data.

        Args:
            df: DataFrame with datetime column
            datetime_column: Name of datetime column

        Returns:
            Detected frequency string (e.g., '1min', '5min')
        """
        if datetime_column not in df.columns or len(df) < 2:
            return 'unknown'

        # Get time differences
        dt_series = pd.to_datetime(df[datetime_column])
        diffs = dt_series.diff().dropna()

        if len(diffs) == 0:
            return 'unknown'

        # Get most common difference (mode)
        mode_diff = diffs.mode().iloc[0]
        minutes = mode_diff.total_seconds() / 60

        # Map detected minutes to frequency string with tolerance
        # Use exact matching with small tolerance for common frequencies
        FREQUENCY_MAP = {
            1: '1min',
            5: '5min',
            15: '15min',
            30: '30min',
            60: '1h',
            240: '4h',
            1440: '1D',  # 24 * 60
        }

        # Find closest standard frequency within 10% tolerance
        for standard_mins, freq_str in FREQUENCY_MAP.items():
            if abs(minutes - standard_mins) <= standard_mins * 0.1:
                return freq_str

        # If no standard frequency matches, return actual minutes
        if minutes < 60:
            return f'{int(round(minutes))}min'
        elif minutes < 1440:
            return f'{int(round(minutes / 60))}h'
        else:
            return '1D'
