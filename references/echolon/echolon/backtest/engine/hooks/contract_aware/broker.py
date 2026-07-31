"""
Contract-Aware Broker Implementation for Futures Trading
========================================================

Broker that correctly handles futures contract pricing during backtesting.
Overrides the standard broker's execution logic to ensure closing orders
are executed at the price of the specific contract the position was opened in,
rather than the price of the continuous front-month contract.

MIGRATED FROM: modules/backtest/backtesting/engine/contract_aware_broker.py
Changes:
- Parameterized with IMarketAdapter instead of hardcoded SHFE/aluminum logic
- Uses market_adapter.get_main_contract() instead of module-level function
- Uses market_adapter.parse_contract() for contract parsing
- Works with any market that implements IMarketAdapter

Performance Optimization:
- ContractPriceCache pre-loads all contract prices at optimization start
- Uses simple dict for O(1) lookups instead of DataFrame operations
- Call preload_contract_prices() before starting Optuna optimization
"""

import backtrader as bt
import pandas as pd
from datetime import datetime
import logging
from pathlib import Path
from typing import Dict, Optional, TYPE_CHECKING
from collections import defaultdict

from ...futures.enhanced_position import EnhancedPosition

if TYPE_CHECKING:
    from echolon.markets.interface import IMarketAdapter

logger = logging.getLogger(__name__)
debug_logger = logging.getLogger(f"{__name__}.debug")


# ============================================================================
# CONTRACT PRICE CACHE - Pre-loaded for Optimization Performance
# ============================================================================

class ContractPriceCache:
    """
    Pre-loaded contract price cache for fast O(1) lookups during backtesting.

    This singleton class pre-loads all contract prices from disk into memory
    at optimization start, eliminating per-trade disk I/O overhead.

    Performance Impact:
    - Without cache: ~5-20ms per trade x ~100 trades x 400 trials = 200-800 seconds
    - With cache: <0.001ms per lookup (dict access)
    """

    _instance: Optional['ContractPriceCache'] = None
    _initialized: bool = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        # Only initialize once
        if ContractPriceCache._initialized:
            return

        # {contract_name: {trading_date: close_price}}
        self._prices: Dict[str, Dict[datetime.date, float]] = {}
        # {contract_name: DataFrame} - full data for fallback
        self._full_data: Dict[str, pd.DataFrame] = {}
        self._indicators_dir: Optional[Path] = None
        ContractPriceCache._initialized = True

    def preload(self, indicators_dir: str, *, reset: bool = True) -> int:
        """
        Pre-load all contract prices from disk.

        Call this ONCE at the start of optimization, before any trials run.

        Parameters
        ----------
        indicators_dir : str
            Path to indicators directory containing 'by_contract' subdirectory
        reset : bool
            Clear any previously loaded contract prices before loading this
            directory. Defaults to True so sequential backtests cannot retain
            prices from an earlier indicators root.

        Returns
        -------
        int
            Number of contracts loaded
        """
        if reset:
            self.clear()

        self._indicators_dir = Path(indicators_dir)
        contract_dir = self._indicators_dir / "by_contract"

        if not contract_dir.exists():
            logger.error(f"[CONTRACT_CACHE] Directory not found: {contract_dir}")
            return 0

        loaded_count = 0

        # Load all pickle files (faster) or CSV files
        for pkl_file in contract_dir.glob("*_indicators.pkl"):
            contract_name = pkl_file.stem.replace("_indicators", "")
            loaded = self._load_contract(contract_name, pkl_file, is_pickle=True)
            if loaded:
                loaded_count += 1

        # Load any CSV files that don't have pickle versions
        for csv_file in contract_dir.glob("*_indicators.csv"):
            contract_name = csv_file.stem.replace("_indicators", "")
            if contract_name not in self._prices:
                loaded = self._load_contract(contract_name, csv_file, is_pickle=False)
                if loaded:
                    loaded_count += 1

        if logger.isEnabledFor(logging.INFO):
            total_prices = sum(len(prices) for prices in self._prices.values())
            logger.info(f"[CONTRACT_CACHE] Pre-loaded | contracts={loaded_count}, total_prices={total_prices}")

        return loaded_count

    def _load_contract(self, contract_name: str, file_path: Path, is_pickle: bool) -> bool:
        """Load a single contract's price data."""
        try:
            if is_pickle:
                df = pd.read_pickle(file_path)
            else:
                df = pd.read_csv(file_path)

            if 'trading_date' not in df.columns or 'close' not in df.columns:
                logger.warning(f"[CONTRACT_CACHE] Missing columns | contract={contract_name}")
                return False

            # Convert trading_date to date objects
            df['trading_date'] = pd.to_datetime(df['trading_date'], format='%Y%m%d').dt.date

            # Build price lookup dict: {date: price}
            self._prices[contract_name] = dict(zip(df['trading_date'], df['close'].astype(float)))

            # Store full data for potential fallback needs
            df_indexed = df.set_index('trading_date')
            self._full_data[contract_name] = df_indexed

            return True

        except Exception as e:
            logger.warning(f"[CONTRACT_CACHE] Load failed | contract={contract_name}, error={e}")
            return False

    def get_price(self, contract_name: str, trading_date: datetime.date) -> Optional[float]:
        """
        Get the closing price for a contract on a specific date.

        O(1) dict lookup - no disk I/O or DataFrame operations.
        """
        contract_prices = self._prices.get(contract_name)
        if contract_prices is None:
            return None

        price = contract_prices.get(trading_date)
        if price is not None and not pd.isna(price):
            return float(price)
        return None

    def get_full_data(self, contract_name: str) -> Optional[pd.DataFrame]:
        """Get full indicator DataFrame for a contract (for fallback compatibility)."""
        return self._full_data.get(contract_name)

    def is_loaded(self) -> bool:
        """Check if cache has been pre-loaded."""
        return len(self._prices) > 0

    def clear(self):
        """Clear the cache (useful for testing)."""
        self._prices.clear()
        self._full_data.clear()
        self._indicators_dir = None
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("[CONTRACT_CACHE] Cleared")


# Module-level singleton instance
_contract_price_cache = ContractPriceCache()


def preload_contract_prices(indicators_dir: str, *, reset: bool = True) -> int:
    """
    Pre-load all contract prices for optimization performance.

    Call this ONCE before starting Optuna optimization.

    Parameters
    ----------
    indicators_dir : str
        Path to indicators directory
    reset : bool
        Clear existing cached prices before loading this directory.

    Returns
    -------
    int
        Number of contracts loaded
    """
    return _contract_price_cache.preload(indicators_dir, reset=reset)


def get_cached_contract_price(contract_name: str, trading_date: datetime.date) -> Optional[float]:
    """Get contract price from pre-loaded cache."""
    return _contract_price_cache.get_price(contract_name, trading_date)


def is_contract_cache_loaded() -> bool:
    """Check if contract price cache has been pre-loaded."""
    return _contract_price_cache.is_loaded()


def clear_contract_price_cache():
    """Clear the contract price cache (useful for testing)."""
    _contract_price_cache.clear()


class ContractAwareBroker(bt.brokers.BackBroker):
    """
    Enhanced BackBroker that correctly handles futures contract pricing.

    Tracks the specific contract in which a position is opened. When the
    position is closed, uses the historical price of that original contract
    for the exit execution.

    Parameters
    ----------
    indicators_dir : str
        Path to the indicators directory with 'by_contract' subdirectory
    market_adapter : IMarketAdapter
        Market adapter for contract management and parsing
    instrument : str
        Base instrument code (e.g., 'al', 'cu', 'BTC')
    **kwargs
        Additional arguments for parent BackBroker
    """

    def __init__(
        self,
        indicators_dir: str,
        market_adapter: 'IMarketAdapter',
        instrument: str,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.indicators_dir = Path(indicators_dir)
        self.market_adapter = market_adapter
        self.instrument = instrument
        self.contract_indicators_dir = self.indicators_dir / "by_contract"

        # Use the module-level pre-loaded cache for O(1) price lookups
        self._use_preloaded_cache = _contract_price_cache.is_loaded()

        # Fallback cache for on-demand loading
        self._fallback_cache: Dict[str, pd.DataFrame] = {}

        # Dictionary to store the contract in which a position was opened
        self._position_contracts: Dict[bt.DataBase, str] = {}

        # Override positions with enhanced position tracking
        self.positions = defaultdict(lambda: EnhancedPosition())

        if not self.contract_indicators_dir.exists():
            logger.error(f"[CONTRACT_BROKER] Directory not found: {self.contract_indicators_dir}")
            raise FileNotFoundError(f"Directory not found: {self.contract_indicators_dir}")

        if logger.isEnabledFor(logging.DEBUG):
            cache_status = "pre-loaded" if self._use_preloaded_cache else "on-demand"
            logger.debug(f"[CONTRACT_BROKER] Initialized | cache={cache_status}, market={market_adapter.market_code}")

    @property
    def contract_prefix(self) -> str:
        """Get the contract prefix for this instrument."""

        return self.instrument.lower()

    def getvalue(self, datas=None):
        """
        Calculate portfolio value using contract-specific prices for open positions.

        Ensures all analyzers receive accurate, contract-aware portfolio value.
        """
        val = self.cash

        for data, pos in self.positions.items():
            if not pos.size:
                continue

            price = data.close[0]

            position_contract = self._position_contracts.get(data)
            order_dt = bt.num2date(data.datetime[0]).date()

            if position_contract:
                contract_price = self._get_contract_price(position_contract, order_dt)
                if contract_price is not None:
                    price = contract_price

            comminfo = self.getcommissioninfo(data)

            if not self.p.shortcash:
                dvalue = comminfo.getvalue(pos, price)
            else:
                dvalue = comminfo.getvaluesize(pos.size, price)

            val += dvalue

        return val

    def _load_contract_indicators(self, contract_name: str) -> Optional[pd.DataFrame]:
        """Load indicator and price data for a specific futures contract."""
        # First, try pre-loaded cache
        if self._use_preloaded_cache:
            full_data = _contract_price_cache.get_full_data(contract_name)
            if full_data is not None:
                return full_data

        # Fallback: check instance-level cache
        if contract_name in self._fallback_cache:
            return self._fallback_cache[contract_name]

        # Fallback: load from disk
        pkl_file = self.contract_indicators_dir / f"{contract_name}_indicators.pkl"
        csv_file = self.contract_indicators_dir / f"{contract_name}_indicators.csv"

        df = None
        if pkl_file.exists():
            try:
                df = pd.read_pickle(pkl_file)
            except Exception as e:
                logger.warning(f"[CONTRACT_BROKER] Pickle load failed: {e}")

        if df is None and csv_file.exists():
            try:
                df = pd.read_csv(csv_file)
            except Exception as e:
                logger.error(f"[CONTRACT_BROKER] CSV load failed: {e}")
                return None

        if df is None:
            logger.warning(f"[CONTRACT_BROKER] No indicator file | contract={contract_name}")
            return None

        if 'trading_date' in df.columns:
            df['trading_date'] = pd.to_datetime(df['trading_date'], format='%Y%m%d').dt.date
        else:
            logger.warning(f"[CONTRACT_BROKER] Missing column | contract={contract_name}, column=trading_date")
            return None

        df.set_index('trading_date', inplace=True)
        self._fallback_cache[contract_name] = df
        return df

    def _get_contract_price(self, contract_name: str, trading_date: datetime.date) -> Optional[float]:
        """Get the closing price for a specific contract on a given trading date."""
        # Fast path: Use pre-loaded cache
        if self._use_preloaded_cache:
            price = _contract_price_cache.get_price(contract_name, trading_date)
            if price is not None:
                return price

        # Slow path: Load from disk
        contract_data = self._load_contract_indicators(contract_name)
        if contract_data is None:
            return None

        try:
            price = contract_data.at[trading_date, 'close']
            if pd.isna(price):
                return None
            return float(price)
        except KeyError:
            logger.warning(f"[CONTRACT_BROKER] Price not found | contract={contract_name}, date={trading_date}")
            return None
        except Exception as e:
            logger.error(f"[CONTRACT_BROKER] Price retrieval failed | error={e}")
            return None

    def _get_current_contract_from_data(self, data: bt.DataBase) -> Optional[str]:
        """
        Get the current contract from the data feed's contract line.

        Uses market_adapter.parse_contract() for validation.
        """
        if hasattr(data, 'contract') and len(data.contract) > 0:
            current_contract = data.contract[0]

            # Handle numpy scalar
            if hasattr(current_contract, 'item'):
                current_contract = current_contract.item()

            # Convert from numeric format back to string format
            numeric_contract = int(current_contract)
            if numeric_contract == 0:
                return None

            # Convert to contract format using instrument prefix
            string_contract = f"{self.contract_prefix}{numeric_contract:04d}"

            # Validate contract using market adapter
            current_date = bt.num2date(data.datetime[0]).date()
            instrument, year, month = self.market_adapter.parse_contract(string_contract)

            if year is not None:
                # Validate contract year makes sense
                data_year = current_date.year
                if abs(year - data_year) > 2:
                    debug_logger.error(
                        f"DATA FEED CONTRACT ERROR: Data for {current_date} ({data_year}) "
                        f"contains contract {string_contract} ({year}-{month:02d})"
                    )
                    return None

            return string_contract
        else:
            return None


    def _execute(self, order, ago=None, price=None, cash=None, position=None, dtcoc=None, **kwargs):
        """Override execution to inject correct contract pricing."""
        if price is None:
            return super()._execute(order, ago, price, cash, position, dtcoc, **kwargs)

        pos = self.positions[order.data]
        pos_size_before = pos.size

        order_dt = bt.num2date(order.data.datetime[ago]).date()
        corrected_price = price

        # Check if opening a new position
        is_opening_trade = pos_size_before == 0 and order.size != 0
        if is_opening_trade:
            current_contract = self._get_current_contract_from_data(order.data)

            if current_contract is None:
                # Fallback to market adapter
                current_contract = self.market_adapter.get_main_contract(order_dt, self.instrument)
                debug_logger.warning(f"Using fallback contract: {current_contract}")

            # Ensure position has contract before execution
            if not isinstance(pos, EnhancedPosition):
                pos = EnhancedPosition.from_base_position(pos, contract=current_contract)
                self.positions[order.data] = pos
            else:
                pos.update_contract(current_contract)

            self._position_contracts[order.data] = current_contract

        # Check if closing position
        is_closing_trade = (order.isbuy() and pos_size_before < 0) or \
                          (order.issell() and pos_size_before > 0)

        if is_closing_trade:
            position_contract = self._position_contracts.get(order.data)
            if position_contract:
                contract_price = self._get_contract_price(position_contract, order_dt)

                if contract_price is not None and abs(contract_price - price) > 1e-9:
                    corrected_price = contract_price
                    debug_logger.debug(
                        f"[{order_dt}] Price Correction for {position_contract}: "
                        f"Main={price:.2f}, Contract={corrected_price:.2f}"
                    )

        # Execute with parent class
        result = super()._execute(order, ago, corrected_price, cash, position, dtcoc, **kwargs)

        # Clean up tracking after position closed
        pos_size_after = pos.size
        if pos_size_before != 0 and pos_size_after == 0:
            if order.data in self._position_contracts:
                del self._position_contracts[order.data]

        # Verify contract assignment for open positions
        if pos_size_after != 0 and not getattr(pos, 'contract', None):
            stored_contract = self._position_contracts.get(order.data)
            if stored_contract:
                if isinstance(pos, EnhancedPosition):
                    pos.update_contract(stored_contract)

        return result

    def getposition(self, data, clone=True):
        """Override to return enhanced positions with contract information."""
        pos = self.positions[data]

        if not isinstance(pos, EnhancedPosition):
            contract = self._position_contracts.get(data)
            if not contract and pos.size != 0:
                contract = self._get_current_contract_from_data(data)
                if not contract:
                    contract = self.market_adapter.get_main_contract(
                        bt.num2date(data.datetime[0]).date(),
                        self.instrument
                    )
                self._position_contracts[data] = contract

            pos = EnhancedPosition.from_base_position(pos, contract=contract)
            self.positions[data] = pos

        if pos.size != 0 and not pos.contract:
            stored_contract = self._position_contracts.get(data)
            if stored_contract:
                pos.update_contract(stored_contract)
            else:
                current_contract = self._get_current_contract_from_data(data)
                if not current_contract:
                    current_contract = self.market_adapter.get_main_contract(
                        bt.num2date(data.datetime[0]).date(),
                        self.instrument
                    )
                pos.update_contract(current_contract)
                self._position_contracts[data] = current_contract

        if clone:
            return pos.clone()
        return pos

    def get_current_position_with_contract(self) -> Optional[EnhancedPosition]:
        """Get the current active position with contract information."""
        # Debug: Log what positions exist
        if logger.isEnabledFor(logging.DEBUG):
            positions_info = [(type(d).__name__, p.size, getattr(p, 'contract', None))
                             for d, p in self.positions.items()]
            logger.debug(f"[CONTRACT_BROKER] Positions: {positions_info}")

        for data, pos in self.positions.items():
            if pos.size != 0:
                enhanced_pos = self.getposition(data, clone=True)
                logger.debug(
                    f"[CONTRACT_BROKER] Found active position | size={enhanced_pos.size}, "
                    f"contract={enhanced_pos.contract}"
                )
                return enhanced_pos
        return None

    def get_all_positions_with_contracts(self) -> Dict[str, EnhancedPosition]:
        """Get all positions with contract information."""
        positions_with_contracts = {}
        for data, pos in self.positions.items():
            if pos.size != 0:
                enhanced_pos = self.getposition(data, clone=True)
                if enhanced_pos.contract:
                    positions_with_contracts[enhanced_pos.contract] = enhanced_pos
        return positions_with_contracts


def create_contract_aware_broker(
    indicators_dir: str,
    market_adapter: 'IMarketAdapter',
    instrument: str,
    **broker_kwargs
) -> ContractAwareBroker:
    """
    Factory function to create a ContractAwareBroker instance.

    Parameters
    ----------
    indicators_dir : str
        Path to the indicators directory
    market_adapter : IMarketAdapter
        Market adapter for contract management
    instrument : str
        Base instrument code (e.g., 'al', 'cu')
    **broker_kwargs
        Additional broker arguments (cash, commission, etc.)

    Returns
    -------
    ContractAwareBroker
        Configured broker instance
    """
    broker = ContractAwareBroker(
        indicators_dir=indicators_dir,
        market_adapter=market_adapter,
        instrument=instrument,
        **broker_kwargs
    )
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(f"[CONTRACT_BROKER] Factory | status=created, market={market_adapter.market_code}")
    return broker
