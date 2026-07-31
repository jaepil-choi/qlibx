"""
Enriched Pandas Data Feed
=========================

Dynamic data feed creation with indicators for Backtrader backtesting.

This module provides:
- EnrichedPandasData: Enhanced PandasData feed with indicator columns
- Module-level caching for Optuna optimization performance
- Dynamic class generation based on indicator metadata

MIGRATED FROM: modules/backtest/backtesting/engine/enriched_pandas_data.py
Changes:
- No functional changes, this is a generic infrastructure component
- Works with any market via indicator metadata
"""

import logging
import backtrader as bt
from typing import Dict, Any, Optional, Type

logger = logging.getLogger(__name__)

# ============================================================================
# MODULE-LEVEL CACHE FOR DATAFEED CLASS
# ============================================================================
# This cache stores the dynamically created DataFeed class to avoid
# recreating it for every trial during Optuna optimization.
# The class only depends on indicator columns, which don't change between trials.

_CACHED_DATA_FEED_CLASS: Optional[Type[bt.feeds.PandasData]] = None
_CACHED_INDICATOR_COLUMNS: Optional[tuple] = None


def get_cached_data_feed_class(metadata: Dict[str, Any]) -> Type[bt.feeds.PandasData]:
    """
    Get or create a cached DataFeed class from metadata.

    This function provides significant performance improvement during Optuna
    optimization by avoiding repeated class creation (type() calls) for each trial.
    The DataFeed class structure only depends on indicator columns, which remain
    constant across all optimization trials.

    Parameters
    ----------
    metadata : Dict[str, Any]
        Indicator metadata dictionary containing 'indicator_columns'

    Returns
    -------
    Type[bt.feeds.PandasData]
        Cached or newly created PandasData class
    """
    global _CACHED_DATA_FEED_CLASS, _CACHED_INDICATOR_COLUMNS

    # Create cache key from indicator columns
    current_columns = tuple(sorted(metadata.get('indicator_columns', [])))

    # Return cached class if columns match
    if _CACHED_DATA_FEED_CLASS is not None and _CACHED_INDICATOR_COLUMNS == current_columns:
        return _CACHED_DATA_FEED_CLASS

    # Create new class and cache it
    _CACHED_DATA_FEED_CLASS = EnrichedPandasData.from_metadata(metadata)
    _CACHED_INDICATOR_COLUMNS = current_columns

    if logger.isEnabledFor(logging.INFO):
        logger.info(f"[ENRICHED_DATA] Cached DataFeed class | indicators={len(current_columns)}")

    return _CACHED_DATA_FEED_CLASS


def clear_data_feed_cache():
    """Clear the cached DataFeed class. Useful for testing or when indicators change."""
    global _CACHED_DATA_FEED_CLASS, _CACHED_INDICATOR_COLUMNS
    _CACHED_DATA_FEED_CLASS = None
    _CACHED_INDICATOR_COLUMNS = None
    logger.debug("[ENRICHED_DATA] Cache cleared")


class EnrichedPandasData(bt.feeds.PandasData):
    """
    Enhanced PandasData feed that includes additional indicator columns
    as accessible lines for strategies.

    This class can be dynamically configured using metadata to define
    which indicators are available as lines.
    """
    lines = ()
    params = (
        ('datetime', None),  # Let backtrader automatically use datetime index
        ('open', 'open'),
        ('high', 'high'),
        ('low', 'low'),
        ('close', 'close'),
        ('volume', 'volume'),
        ('openinterest', -1),  # Not available in our data
    )

    @classmethod
    def from_metadata(cls, metadata: Dict[str, Any]) -> Type[bt.feeds.PandasData]:
        """
        Create a dynamically configured EnrichedPandasData class using metadata.

        Parameters
        ----------
        metadata : Dict[str, Any]
            Indicator metadata dictionary containing 'indicator_columns'

        Returns
        -------
        Type[bt.feeds.PandasData]
            Dynamically configured PandasData class
        """
        indicator_columns = metadata['indicator_columns']

        # Generate unique line names (lowercase)
        line_names = set()
        line_to_col = {}

        # Exclude metadata columns from indicator lines
        # These columns are handled separately or dropped in data loading
        # Note: session_phase and contract are converted to numeric in SHFE_loader
        excluded_columns = {'date', 'trading_date', 'datetime'}

        filtered_columns = [col for col in indicator_columns
                          if col.lower() not in excluded_columns
                          and not col.lower().startswith('unnamed')]

        for col in filtered_columns:
            # Validate the LOWERCASED form — that is what gets bound as the
            # backtrader line name below (line_name = col.lower()).
            col_lower = col.lower()
            if not col_lower.isidentifier():
                raise ValueError(
                    f"[ENRICHED_DATA] indicator_columns entry {col!r} is not a valid Python "
                    f"identifier (backtrader binds indicator columns as line attributes; "
                    f"names with dashes, spaces, or dots fail at first access). "
                    f"Rename the column before calling from_metadata."
                )

        for col in filtered_columns:
            line_name = col.lower()

            if line_name not in line_to_col:
                line_names.add(line_name)
                line_to_col[line_name] = col

        # Convert to sorted tuple for deterministic order
        line_names_tuple = tuple(sorted(line_names))

        # Create parameters
        params = [
            ('datetime', None),  # Use index as datetime
            ('open', 'open'),
            ('high', 'high'),
            ('low', 'low'),
            ('close', 'close'),
            ('volume', 'volume'),
            ('openinterest', -1),  # Not available in our data
        ]

        # Add indicator parameters
        for line_name in sorted(line_names):
            col = line_to_col[line_name]
            params.append((line_name, col))

        # Create the new class with numpy-optimized data loading
        # Standard PandasData uses slow pandas.iloc access for each value
        # This optimization pre-converts to numpy arrays for ~10-50x faster loading
        class_dict = {
            'lines': line_names_tuple,
            'params': tuple(params)
        }

        def optimized_start(self):
            """Pre-convert DataFrame columns to numpy arrays for fast access."""
            # Call parent start first
            bt.feeds.PandasData.start(self)

            # Pre-extract all columns as numpy arrays for fast _load() access
            df = self.p.dataname
            self._np_arrays = {}
            self._np_datetime = df.index.values  # datetime index

            # Extract OHLCV columns
            for col in ['open', 'high', 'low', 'close', 'volume']:
                if col in df.columns:
                    self._np_arrays[col] = df[col].values

            # Extract all indicator columns
            for col in df.columns:
                col_lower = col.lower()
                if col_lower not in self._np_arrays:
                    self._np_arrays[col_lower] = df[col].values

            self._np_len = len(df)

        def optimized_load(self):
            """Load one bar using fast numpy array indexing instead of pandas iloc."""
            import pandas as pd

            # Increment first (matching standard PandasData._load behavior)
            # Parent's start() sets _idx = -1, so first increment makes it 0
            self._idx += 1

            if self._idx >= self._np_len:
                return False

            idx = self._idx

            # Load datetime (convert numpy.datetime64 to Python datetime)
            dt = pd.Timestamp(self._np_datetime[idx]).to_pydatetime()
            self.lines.datetime[0] = bt.date2num(dt)

            # Load OHLCV
            self.lines.open[0] = self._np_arrays['open'][idx]
            self.lines.high[0] = self._np_arrays['high'][idx]
            self.lines.low[0] = self._np_arrays['low'][idx]
            self.lines.close[0] = self._np_arrays['close'][idx]
            self.lines.volume[0] = self._np_arrays['volume'][idx]
            self.lines.openinterest[0] = 0.0

            # Load all indicator lines
            for line_name in line_names_tuple:
                if line_name in self._np_arrays:
                    getattr(self.lines, line_name)[0] = self._np_arrays[line_name][idx]

            return True

        def optimized_preload(self):
            """
            Optimized preload using fast numpy-based _load().

            Uses Backtrader's standard preload loop but with our optimized _load()
            that uses pre-converted numpy arrays instead of slow pandas iloc.
            """
            # Use standard Backtrader preload loop with our fast _load()
            while self.load():
                pass

            self._last()
            self.home()

        class_dict['start'] = optimized_start
        class_dict['_load'] = optimized_load
        class_dict['preload'] = optimized_preload

        data_feed_class = type(
            'DynamicEnrichedPandasData',
            (bt.feeds.PandasData,),
            class_dict
        )

        if logger.isEnabledFor(logging.INFO):
            logger.info(f"[ENRICHED_DATA] Feed created | indicators={len(line_names_tuple)}")
        return data_feed_class
