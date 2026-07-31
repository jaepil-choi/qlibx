"""
Contract Loader
===============

Provides contract-related data access utilities for futures trading.

This module consolidates:
- ContractIndicatorManager: Load and cache contract-specific indicator data
  (per-contract OHLCV + indicators, supports pickle and CSV formats)
- get_main_contract: Thin wrapper around canonical main-contract resolution
  that appends the ``.SF`` exchange suffix for MiniQMT / deploy callers

Previously split across contract_data.py + contract_utils.py; merged here
for a single, focused import surface.
"""

import logging
import pandas as pd
from pathlib import Path
from typing import Dict, List, Optional, Any, TYPE_CHECKING
from datetime import date, datetime

if TYPE_CHECKING:
    from ..core.interfaces.trading_interfaces import IMarketAdapter

logger = logging.getLogger(__name__)


class ContractIndicatorManager:
    """
    Manages contract-specific indicator data for futures trading.

    Features:
    - Loads indicator data by contract
    - Caches data for fast repeated access
    - Supports both pickle (fast) and CSV formats
    - Integrates with market adapter for contract validation

    Parameters
    ----------
    indicators_dir : str or Path
        Path to the indicators directory containing 'by_contract' subdirectory
    market_adapter : IMarketAdapter, optional
        Market adapter for contract validation and parsing
    """

    def __init__(
        self,
        indicators_dir: str,
        market_adapter: Optional['IMarketAdapter'] = None
    ):
        self.indicators_dir = Path(indicators_dir)
        self.contract_dir = self.indicators_dir / "by_contract"
        self.market_adapter = market_adapter

        # Cache for loaded contract data
        self._contract_cache: Dict[str, pd.DataFrame] = {}

        # Metadata cache
        self._indicator_columns: Optional[List[str]] = None
        self._available_contracts: Optional[List[str]] = None

        if not self.contract_dir.exists():
            logger.warning(f"[CONTRACT_DATA] Directory not found: {self.contract_dir}")

        if logger.isEnabledFor(logging.INFO):
            logger.info(
                f"[CONTRACT_DATA] Initialized | "
                f"dir={self.indicators_dir}, "
                f"market={market_adapter.market_code if market_adapter else 'none'}"
            )

    def load_contract_data(self, contract_name: str) -> Optional[pd.DataFrame]:
        """
        Load indicator data for a specific contract.

        Parameters
        ----------
        contract_name : str
            Contract identifier (e.g., 'al2403', 'cu2401')

        Returns
        -------
        Optional[pd.DataFrame]
            DataFrame with indicators indexed by trading_date, or None if not found
        """
        # Check cache first
        if contract_name in self._contract_cache:
            return self._contract_cache[contract_name]

        # Try pickle first (faster)
        pkl_file = self.contract_dir / f"{contract_name}_indicators.pkl"
        csv_file = self.contract_dir / f"{contract_name}_indicators.csv"

        df = None
        if pkl_file.exists():
            try:
                df = pd.read_pickle(pkl_file)
                logger.debug(f"[CONTRACT_DATA] Loaded from pickle | contract={contract_name}")
            except Exception as e:
                logger.warning(f"[CONTRACT_DATA] Pickle load failed | contract={contract_name}, error={e}")

        if df is None and csv_file.exists():
            try:
                df = pd.read_csv(csv_file)
                logger.debug(f"[CONTRACT_DATA] Loaded from CSV | contract={contract_name}")
            except Exception as e:
                logger.error(f"[CONTRACT_DATA] CSV load failed | contract={contract_name}, error={e}")
                return None

        if df is None:
            logger.warning(f"[CONTRACT_DATA] No data file | contract={contract_name}")
            return None

        # Process trading_date column
        if 'trading_date' in df.columns:
            df['trading_date'] = pd.to_datetime(df['trading_date'], format='%Y%m%d').dt.date
            df = df.set_index('trading_date')
        elif 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date']).dt.date
            df = df.set_index('date')

        # Cache the data
        self._contract_cache[contract_name] = df

        return df

    def get_indicator(
        self,
        contract_name: str,
        trading_date: date,
        indicator_name: str
    ) -> Optional[float]:
        """
        Get a specific indicator value for a contract on a date.

        Parameters
        ----------
        contract_name : str
            Contract identifier
        trading_date : date
            Trading date
        indicator_name : str
            Indicator column name

        Returns
        -------
        Optional[float]
            Indicator value, or None if not found
        """
        df = self.load_contract_data(contract_name)
        if df is None:
            return None

        try:
            value = df.at[trading_date, indicator_name]
            if pd.isna(value):
                return None
            return float(value)
        except KeyError:
            logger.debug(
                f"[CONTRACT_DATA] Indicator not found | "
                f"contract={contract_name}, date={trading_date}, indicator={indicator_name}"
            )
            return None

    def get_price(self, contract_name: str, trading_date: date) -> Optional[float]:
        """
        Get the close price for a contract on a date.

        Convenience method that wraps get_indicator for the 'close' column.

        Parameters
        ----------
        contract_name : str
            Contract identifier
        trading_date : date
            Trading date

        Returns
        -------
        Optional[float]
            Close price, or None if not found
        """
        return self.get_indicator(contract_name, trading_date, 'close')

    def get_ohlcv(self, contract_name: str, trading_date: date) -> Optional[Dict[str, float]]:
        """
        Get OHLCV data for a contract on a date.

        Parameters
        ----------
        contract_name : str
            Contract identifier
        trading_date : date
            Trading date

        Returns
        -------
        Optional[Dict[str, float]]
            Dictionary with open, high, low, close, volume; or None if not found
        """
        df = self.load_contract_data(contract_name)
        if df is None:
            return None

        try:
            row = df.loc[trading_date]
            return {
                'open': float(row['open']) if not pd.isna(row['open']) else None,
                'high': float(row['high']) if not pd.isna(row['high']) else None,
                'low': float(row['low']) if not pd.isna(row['low']) else None,
                'close': float(row['close']) if not pd.isna(row['close']) else None,
                'volume': float(row['volume']) if not pd.isna(row.get('volume', float('nan'))) else None,
            }
        except KeyError:
            return None

    def get_available_contracts(self) -> List[str]:
        """
        Get list of all available contracts.

        Returns
        -------
        List[str]
            List of contract names that have indicator data
        """
        if self._available_contracts is not None:
            return self._available_contracts

        contracts = set()

        # Check for pickle files
        for pkl_file in self.contract_dir.glob("*_indicators.pkl"):
            contract_name = pkl_file.stem.replace("_indicators", "")
            contracts.add(contract_name)

        # Check for CSV files
        for csv_file in self.contract_dir.glob("*_indicators.csv"):
            contract_name = csv_file.stem.replace("_indicators", "")
            contracts.add(contract_name)

        self._available_contracts = sorted(list(contracts))
        return self._available_contracts

    def get_indicator_columns(self) -> List[str]:
        """
        Get list of available indicator columns.

        Loads the first available contract to determine columns.

        Returns
        -------
        List[str]
            List of indicator column names
        """
        if self._indicator_columns is not None:
            return self._indicator_columns

        contracts = self.get_available_contracts()
        if not contracts:
            return []

        # Load first contract to get columns
        df = self.load_contract_data(contracts[0])
        if df is None:
            return []

        # Exclude standard OHLCV columns
        standard_cols = {'open', 'high', 'low', 'close', 'volume', 'openinterest'}
        indicator_cols = [col for col in df.columns if col.lower() not in standard_cols]

        self._indicator_columns = indicator_cols
        return self._indicator_columns

    def get_contract_date_range(self, contract_name: str) -> Optional[tuple]:
        """
        Get the date range for a contract's data.

        Parameters
        ----------
        contract_name : str
            Contract identifier

        Returns
        -------
        Optional[tuple]
            (start_date, end_date) tuple, or None if contract not found
        """
        df = self.load_contract_data(contract_name)
        if df is None or df.empty:
            return None

        return (df.index.min(), df.index.max())

    def preload_contracts(self, contracts: Optional[List[str]] = None) -> int:
        """
        Pre-load contract data into cache.

        Useful for optimization where the same contracts are accessed repeatedly.

        Parameters
        ----------
        contracts : List[str], optional
            Specific contracts to load. If None, loads all available.

        Returns
        -------
        int
            Number of contracts loaded
        """
        if contracts is None:
            contracts = self.get_available_contracts()

        loaded_count = 0
        for contract in contracts:
            df = self.load_contract_data(contract)
            if df is not None:
                loaded_count += 1

        if logger.isEnabledFor(logging.INFO):
            logger.info(f"[CONTRACT_DATA] Pre-loaded | contracts={loaded_count}")

        return loaded_count

    def clear_cache(self) -> None:
        """Clear the contract data cache."""
        self._contract_cache.clear()
        self._indicator_columns = None
        self._available_contracts = None
        logger.debug("[CONTRACT_DATA] Cache cleared")

    def get_metadata(self) -> Dict[str, Any]:
        """
        Get metadata about the contract data.

        Returns
        -------
        Dict[str, Any]
            Dictionary with metadata including available contracts,
            indicator columns, and directory information
        """
        contracts = self.get_available_contracts()
        indicator_cols = self.get_indicator_columns()

        return {
            'indicators_dir': str(self.indicators_dir),
            'contract_dir': str(self.contract_dir),
            'num_contracts': len(contracts),
            'contracts': contracts,
            'num_indicators': len(indicator_cols),
            'indicator_columns': indicator_cols,
            'cached_contracts': list(self._contract_cache.keys()),
            'market': self.market_adapter.market_code if self.market_adapter else None
        }

    def validate_contract(self, contract_name: str) -> bool:
        """
        Validate a contract name.

        If market_adapter is provided, uses it for validation.
        Otherwise, checks if contract data exists.

        Parameters
        ----------
        contract_name : str
            Contract identifier

        Returns
        -------
        bool
            True if contract is valid
        """
        # Check if data exists
        if contract_name not in self.get_available_contracts():
            return False

        # Use market adapter for additional validation if available
        if self.market_adapter is not None:
            instrument, year, month = self.market_adapter.parse_contract(contract_name)
            if year is None or month is None:
                return False
            if month < 1 or month > 12:
                return False

        return True

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"ContractIndicatorManager("
            f"dir={self.indicators_dir}, "
            f"contracts={len(self.get_available_contracts())}, "
            f"cached={len(self._contract_cache)})"
        )


# =============================================================================
# Main-contract resolution helpers
# =============================================================================

from datetime import datetime as _datetime  # noqa: E402  (local import for clarity)

from echolon.markets.shfe.contract_rules import (  # noqa: E402
    get_main_contract as _get_main_contract_canonical,
)

# Default symbol used throughout the deploy pipeline
_DEFAULT_SYMBOL = "al"


def get_main_contract(
    ref_date: _datetime = None,
    symbol: str = _DEFAULT_SYMBOL,
    *,
    market_data_dir: Path,
) -> str:
    """
    Get the main futures contract code with ``.SF`` exchange suffix.

    Delegates to the canonical CSV-based lookup in
    ``market_adapters.shfe.contract_rules.get_main_contract``.

    Args:
        ref_date: Reference date. Defaults to ``datetime.now()`` if not provided.
        symbol: Product symbol (e.g. ``'al'``, ``'cu'``). Defaults to ``'al'``.
        market_data_dir: Required. Base market-data directory containing
            ``SHFE/{instrument_name}/main_contract.csv`` (typically
            ``paths.market_data_dir``).

    Returns:
        Main contract code with suffix (e.g. ``'al2508.SF'``).
    """
    current_date = ref_date if ref_date is not None else _datetime.now()
    trading_date = current_date.date() if isinstance(current_date, _datetime) else current_date

    bare_code = _get_main_contract_canonical(trading_date, symbol, market_data_dir=market_data_dir)
    contract = f"{bare_code}.SF"

    logger.debug(f"Main contract for {trading_date}: {contract}")
    return contract
