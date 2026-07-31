"""
Parallel Indicator Processor

Indicator calculation workflow:
1. Process contract files in parallel via data-pipeline loaders.
2. Dispatch to TA-Lib calculators (``indicator_utils.py`` and
   ``indicator_mapping.py``).
3. Convert to numpy arrays for efficient calculation.
4. Output one row per (trading_date, contract) into
   ``strategy_indicators.csv`` + per-contract pkls.
5. Intraday calculations use session-based context (``SESSION_PHASE``,
   ``VOLATILITY_STATE``).
"""
import os
import re
import pandas as pd
import numpy as np
from typing import List, Dict, Any, Optional
import logging
from multiprocessing import cpu_count
from multiprocessing.pool import ThreadPool
import time
from pathlib import Path
import json
from datetime import datetime

# Data pipeline loaders for standardized data access
from echolon.data.loaders.ohlcv_loader import (
    load_contract_ohlcv,
    get_available_contracts,
)
# SHFE contract rules (main contract lookup, expiry date)
from echolon.markets.shfe.contract_rules import get_main_contract, get_expiry_date
from echolon.data.loaders.session_availability_loader import (
    get_session_availability_loader,
)
from ..registry.utils import get_function
from echolon.config.markets.core.context import TradingContext
from echolon.errors import IndicatorError, raise_error

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


_RE_FIT_SUFFIX = re.compile(r"^(.+)__fit([0-9]{8})$")
_RE_WINDOWED_DERIVED = re.compile(r"^(.+)_(pctl|z)_(\d+)$")


def _derived_column_base(indicator_name: str):
    fit_match = _RE_FIT_SUFFIX.match(indicator_name)
    if fit_match:
        return fit_match.group(1)

    window_match = _RE_WINDOWED_DERIVED.match(indicator_name)
    if window_match:
        return window_match.group(1)

    return None


def _resolve_function(indicator_name: str, frequency: str = "day"):
    """Resolve an indicator name to its calculation function.

    Raises IND-002 if the name has no mapping — silent-skip in this dispatch
    would produce an all-NaN output column the caller couldn't debug.
    """
    function = get_function(indicator_name.upper(), frequency=frequency)
    if function is None:
        base_indicator = _derived_column_base(indicator_name)
        if base_indicator is not None:
            raise IndicatorError(
                code="IND-002",
                what="Derived/vintage column requested for indicator dispatch",
                why=(
                    f"{indicator_name!r} is a derived/vintage column. The "
                    "indicator processor dispatches base catalog indicators; "
                    "feed-bake stages produce derived/vintage columns."
                ),
                fix=(
                    f"declare the BASE indicator {base_indicator!r} in "
                    "strategy_indicator_list.json and let the feed bake "
                    f"produce {indicator_name!r}. Do not list a "
                    "derived/vintage column as a computable indicator."
                ),
                context={
                    "indicator": indicator_name,
                    "base_indicator": base_indicator,
                    "file": __file__,
                    "line": "<indicator dispatch>",
                },
            )

        raise_error(
            "IND-002",
            indicator=indicator_name,
            file=__file__,
            line="<indicator dispatch>",
        )
    return function


def _write_nan_warnings_sidecar(
    df: "pd.DataFrame",
    output_path,
    nan_threshold: float = 0.8,
) -> None:
    """Inspect df for columns whose NaN ratio exceeds threshold and write
    <output_path>.warnings.json with a per-column IND-003 payload.

    The sidecar file is present iff at least one column was flagged.
    Columns 'date', 'datetime', 'contract' are always skipped (they're
    keys, not indicators).
    """
    output_path = Path(output_path)
    skip = {"date", "datetime", "contract"}
    warnings = {}
    for col in df.columns:
        if col in skip:
            continue
        total = len(df)
        if total == 0:
            continue
        nan_rows = int(df[col].isna().sum())
        ratio = nan_rows / total
        if ratio >= nan_threshold:
            warnings[col] = {
                "code": "IND-003",
                "indicator": col,
                "rows": total,
                "nan_rows": nan_rows,
                "nan_ratio": round(ratio, 4),
            }
    if warnings:
        sidecar = output_path.with_suffix(output_path.suffix + ".warnings.json")
        sidecar.write_text(json.dumps({"warnings": warnings}, indent=2))


# Default volatility context parameters
DEFAULT_CONTEXT_PARAMS = {
    'atr_period': 14,
    'vol_lookback': 100,
    'high_percentile': 75.0,
    'low_percentile': 25.0,
}
 

class IndicatorProcessor:
    """
    Parallel processor for calculating TA-Lib indicators on contract data.
    Uses data_pipeline loaders for standardized data access.
    """

    def __init__(
        self,
        ctx: TradingContext,
        trading_date_list,
        indicator_list: Dict[str, Dict[str, Any]],
        output_dir: str = None,
        n_jobs: int = None,
        regime_params: Optional[Dict[str, Any]] = None,
        backtest_start_year: Optional[int] = None,
        *,
        paths: "PathsConfig",  # type: ignore[name-defined]
    ):
        """
        Initialize the parallel processor.

        Args:
            ctx: TradingContext with market, instrument, frequency, bar_size configuration
            trading_date_list: List of trading dates to process
            indicator_list: Flat-dict indicator specification (required).
            output_dir: Directory to save processed indicator files
            n_jobs: Number of parallel processes (default: CPU count)
            regime_params: Regime classification parameters required when
                ``indicator_list`` contains a registered classifier name on
                an interday ctx.
            backtest_start_year: Earliest year (e.g. 2018) used to filter
                contracts in :meth:`_is_contract_in_backtest_period`.
            paths: Required PathsConfig for data lookups (market_data_dir).
        """
        self._provided_regime_params = regime_params
        self._backtest_start_year = backtest_start_year
        # Store context for frequency-aware indicator parameters
        self.ctx = ctx
        self._paths = paths

        # Caller-supplied indicator list (flat-dict schema)
        self.indicator_list = indicator_list

        # Extract values from context
        self.trading_date_list = trading_date_list
        self.market = ctx.market_code
        self.asset = ctx.instrument_name
        self.bar_size = ctx.bar_size
        self.bar_size_minutes = ctx.bar_size_minutes

        # Map frequency for internal use: interday -> "day", intraday -> "minute"
        self.frequency = "minute" if ctx.is_intraday else "day"

        # Kind-route declared indicators. ``curve_carry`` indicators (the 5
        # forward-curve carry signals) are computed by a dedicated curve stage in
        # extract_main_contract_indicators — NOT the per-contract TA-Lib path
        # (they need a multi-contract curve snapshot, not a single-contract df,
        # so _resolve_function would IND-002 on them). TA-Lib indicators +
        # registered classifiers stay on the per-contract path. The split is
        # DORMANT unless a curve_carry name is declared, so non-carry strategies
        # are byte-unchanged.
        self._curve_carry_list, self._per_contract_indicator_list = _split_curve_carry(
            self.indicator_list
        )
        if self._curve_carry_list:
            if self.frequency != "day":
                raise ValueError(
                    "curve_carry indicators are interday-only (built from the "
                    "daily forward curve sort_by_date.csv); got an intraday ctx "
                    f"with declared carry: {sorted(self._curve_carry_list)}"
                )
            # The curve builder uses fixed pool-default windows; a declared param
            # spec would be silently discarded — fail loud (NO_ERROR_HANDLING).
            swept = {n: p for n, p in self._curve_carry_list.items() if p}
            if swept:
                raise ValueError(
                    "curve_carry indicators do not accept a param spec (the "
                    "builder uses fixed pool-default windows); declare them with "
                    f"an empty spec. Offending: {sorted(swept)}"
                )

        self.output_dir = Path(output_dir)
        self.contract_output_dir = Path(output_dir) / "by_contract"
        self.n_jobs = n_jobs or cpu_count()
        self.futures = self.asset  # Keep for backwards compatibility
        self.futures_code = ctx.instrument_code

        # Get frequency-scaled default parameters from context
        self.default_params = ctx.get_indicator_params()

        # Create output directory
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.contract_output_dir.mkdir(parents=True, exist_ok=True)

        # Regime params: caller-provided or None. For interday indicators that
        # require them (market_regime etc.), _validate_regime_params will raise
        # at compute time if missing.
        if self.frequency == "day":
            self.regime_params = self._provided_regime_params
            self.session_availability = None  # Not used for interday
        else:
            # Intraday uses session_phase + volatility_state; regime_params unused
            self.regime_params = None
            # Load session availability for bar count indicators
            self.session_availability = get_session_availability_loader(
                market=self.market,
                instrument=self.asset,
                bar_size_minutes=self.bar_size_minutes,
                bar_size=self.bar_size,
            )
            if logger.isEnabledFor(logging.INFO):
                logger.info(f"[INDICATOR_PROCESSOR] Session availability loaded | market={self.market}, instrument={self.asset}, bar_size={self.bar_size}")

        if logger.isEnabledFor(logging.INFO):
            logger.info(f"[INDICATOR_PROCESSOR] Initialized | market={self.market}, asset={self.asset}, freq={self.frequency}, bar_size={self.bar_size}")
            logger.info(f"[INDICATOR_PROCESSOR] Config | processes={self.n_jobs}, bar_size_minutes={self.bar_size_minutes}")
            logger.info(f"[INDICATOR_PROCESSOR] Output dir | path={self.output_dir}")

    def process_all_contracts(self, use_multiprocessing: bool = True) -> Dict[str, bool]:
        """
        Process all contract files
        
        Args:
            use_multiprocessing: Whether to use parallel processing
            
        Returns:
            Dictionary mapping contract names to success status
        """
        contract_files = self.get_contract_files()

        if not contract_files:
            logger.warning("[INDICATOR_PROCESSOR] No contracts found | action=skipping")
            return {}

        start_time = time.time()

        if use_multiprocessing and self.n_jobs > 1:
            if logger.isEnabledFor(logging.INFO):
                logger.info(f"[INDICATOR_PROCESSOR] Parallel processing | contracts={len(contract_files)}, threads={self.n_jobs}")

            # Use ThreadPool instead of Pool to avoid pickling issues with instance methods
            # when modules are reloaded in async contexts (e.g., main.py workflow)
            with ThreadPool(processes=self.n_jobs) as pool:
                results = pool.map(self.process_single_contract, contract_files)

            results_dict = dict(zip(contract_files, results))
        else:
            if logger.isEnabledFor(logging.INFO):
                logger.info(f"[INDICATOR_PROCESSOR] Sequential processing | contracts={len(contract_files)}")
            results_dict = {}
            
            for contract_name in contract_files:
                results_dict[contract_name] = self.process_single_contract(contract_name)
        
        main_contract = self.extract_main_contract_indicators(
                        trading_dates_list=self.trading_date_list,
                        contract_indicators_dir=self.contract_output_dir

                    )
        total_time = time.time() - start_time
        successful = sum(results_dict.values())

        if logger.isEnabledFor(logging.INFO):
            logger.info(f"[INDICATOR_PROCESSOR] Processing complete | successful={successful}/{len(contract_files)}, time={total_time:.2f}s")
        
        return main_contract
    
    def process_single_contract(self, contract_name: str) -> bool:
        """
        Process a single contract using data_pipeline loader.

        Args:
            contract_name: Name of contract (e.g., 'al2201')

        Returns:
            True if successful, False otherwise
        """
        start_time = time.time()

        # Load contract data using data_pipeline loader
        df = load_contract_ohlcv(
            market=self.market,
            asset=self.asset,
            contract=contract_name,
            market_data_dir=self._paths.market_data_dir,
        )

        if df is None or df.empty:
            logger.warning(f"[INDICATOR_PROCESSOR] No data for contract | name={contract_name}")
            return False

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"[INDICATOR_PROCESSOR] Processing contract | name={contract_name}, rows={len(df)}")

        df = _prepare_ohlcv_frame(df)

        # Calculate indicators using the unified flat-dict compute path
        indicator_results = _compute_indicators_for_contract(
            df,
            indicator_list=self._per_contract_indicator_list,
            ctx=self.ctx,
            regime_params=self.regime_params,
            default_params=self.default_params,
            session_availability=self.session_availability,
        )
        
        # Create output dataframe
        output_df = self._create_output_dataframe(df, indicator_results, contract_name)
        
        # Save results
        output_file = self.contract_output_dir / f"{contract_name}_indicators.csv"
        output_df.to_csv(output_file, index=False)
        _write_nan_warnings_sidecar(output_df, output_file)

        # Also save as pickle for faster loading
        pickle_file = self.contract_output_dir / f"{contract_name}_indicators.pkl"
        output_df.to_pickle(pickle_file)
        
        processing_time = time.time() - start_time
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"[INDICATOR_PROCESSOR] Contract complete | name={contract_name}, time={processing_time:.2f}s, rows={len(output_df)}")
        
        return True
    
    
    def _calculate_mandatory_bar_count_indicators(self, df: pd.DataFrame) -> Dict[str, np.ndarray]:
        """
        Calculate mandatory bar count indicators for intraday data.

        These indicators are always generated regardless of indicator configuration,
        as they are essential for accurate timing control (especially with holiday
        schedules where night sessions may be absent).

        Indicators:
        - bar_of_day: Current bar index within trading day (0-indexed)
        - bars_remaining: Bars until end of trading day
        - total_bars_today: Total bars for this trading day (93 or 45)
        - has_night_session: Whether this day has night session (False after holidays)
        - bar_of_session: Current bar index within session (0-indexed)
        - bars_remaining_in_session: Bars until end of current session
        - session_bars_total: Total bars for current session (48/27/18)

        Args:
            df: DataFrame with datetime, trading_date, and session_phase columns

        Returns:
            Dict mapping indicator names to calculated values
        """
        from echolon.indicators.calculators.intraday.indicators import (
            bar_of_day,
            bars_remaining,
            total_bars_today,
            has_night_session,
            bar_of_session,
            bars_remaining_in_session,
            session_bars_total,
        )

        results = {}

        if self.session_availability is None:
            logger.warning("[INDICATOR_PROCESSOR] Session availability not loaded, skipping bar count indicators")
            return results

        if logger.isEnabledFor(logging.INFO):
            logger.info("[INDICATOR_PROCESSOR] Calculating mandatory bar count indicators | reason=intraday timing")

        # bar_of_day doesn't need session_availability
        results['bar_of_day'] = bar_of_day(df)

        # bar_of_session doesn't need session_availability
        results['bar_of_session'] = bar_of_session(df)

        # These require session_availability for accurate counts
        results['bars_remaining'] = bars_remaining(df, session_availability=self.session_availability)
        results['total_bars_today'] = total_bars_today(df, session_availability=self.session_availability)
        results['has_night_session'] = has_night_session(df, session_availability=self.session_availability)
        results['bars_remaining_in_session'] = bars_remaining_in_session(df, session_availability=self.session_availability)
        results['session_bars_total'] = session_bars_total(df, session_availability=self.session_availability)

        return results


    def get_contract_files(self) -> List[str]:
        """Get list of contract files to process using data_pipeline loader."""
        # Use data_pipeline loader to get available contracts
        all_contracts = get_available_contracts(
            market=self.market, asset=self.asset,
            market_data_dir=self._paths.market_data_dir,
        )

        # Filter for contracts matching our futures code (e.g., "al" for aluminum)
        contract_files = []
        for contract_name in all_contracts:
            # Check if contract name starts with our futures code
            if contract_name.startswith(self.futures_code):
                # Filter for recent contracts (2018+) as per existing system
                if self._is_contract_in_backtest_period(contract_name):
                    contract_files.append(contract_name)

        contract_files.sort()
        if logger.isEnabledFor(logging.INFO):
            logger.info(f"[INDICATOR_PROCESSOR] Contracts found | asset={self.asset}, code={self.futures_code}, count={len(contract_files)}")

        return contract_files
    
    def _is_contract_in_backtest_period(self, contract_name: str) -> bool:
        """Check if contract is within backtest period.

        Uses ``self._backtest_start_year`` (passed at construction time) to
        ensure consistent filtering between indicator calculation and
        backtesting.
        """
        import re

        if self._backtest_start_year is None:
            raise ValueError(
                "backtest_start_year is required for contract filtering. "
                "Pass it to IndicatorProcessor(..., backtest_start_year=YYYY) "
                "or forward it via run_indicator_calculation(start_date=...)."
            )
        backtest_start_year = self._backtest_start_year

        # Use regex to extract year from contract name (e.g., al1803, cu2401)
        # Pattern: letters followed by 4 digits (YYMM)
        match = re.match(r'^([a-zA-Z]+)(\d{4})$', contract_name)
        if not match:
            return False

        try:
            date_part = match.group(2)  # e.g., "1803", "2401"
            year_suffix = int(date_part[:2])  # e.g., 18, 24

            # Convert 2-digit year to full year
            full_year = 2000 + year_suffix

            return full_year >= backtest_start_year

        except (ValueError, IndexError):
            logger.warning(f"[INDICATOR_PROCESSOR] Year parse failed | contract={contract_name}")
            return False
    
    
    def _create_output_dataframe(self, original_df: pd.DataFrame,
                               indicator_results: Dict[str, np.ndarray],
                               contract_name: str) -> pd.DataFrame:
        """Create output dataframe with original data and indicators - optimized to avoid fragmentation"""
        # Start with original data (without Unnamed columns)
        unnamed_cols = [col for col in original_df.columns if col.startswith('Unnamed')]
        if unnamed_cols:
            base_df = original_df.drop(columns=unnamed_cols)
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(f"[INDICATOR_PROCESSOR] Removed Unnamed columns | contract={contract_name}, count={len(unnamed_cols)}")
        else:
            base_df = original_df.copy()

        # Prepare indicator columns that match DataFrame length
        indicator_dfs = []
        for indicator_name, values in indicator_results.items():
            if len(values) == len(base_df):
                indicator_dfs.append(pd.DataFrame({indicator_name: values}))
            else:
                logger.warning(f"[INDICATOR_PROCESSOR] Length mismatch | indicator={indicator_name}, contract={contract_name}")

        # Prepare metadata columns
        metadata_dict = {}

        # Add trading_date if not already present and date column exists
        # Use int64 format (YYYYMMDD) for efficient comparison in extract_main_contract_indicators
        if 'trading_date' not in base_df.columns and 'date' in base_df.columns:
            metadata_dict['trading_date'] = base_df['date'].dt.strftime('%Y%m%d').astype(int)

        # Add contract name if not already present
        if 'contract' not in base_df.columns:
            metadata_dict['contract'] = contract_name

        # Add contract expiry (need temporary df for calculation)
        if len(base_df) > 0:
            temp_df = base_df.copy()
            temp_df['contract'] = contract_name
            metadata_dict['contract_expiry'] = self.get_contract_expiry_date(temp_df)

        metadata_df = pd.DataFrame(metadata_dict, index=base_df.index)

        # Combine all DataFrames at once using concat
        dfs_to_concat = [base_df] + indicator_dfs + [metadata_df]
        output_df = pd.concat(dfs_to_concat, axis=1)

        return output_df
    

    def extract_main_contract_indicators(self,trading_dates_list: List[datetime],
                                    contract_indicators_dir: str) -> pd.DataFrame:
        """
        Extract and stitch together indicators from individual contract files
        based on main contract for each trading date.

        Uses main_contract.csv lookup table for accurate main contract determination.

        Parameters
        ----------
        trading_dates_list : List[datetime]
            List of trading dates
        contract_indicators_dir : str
            Directory containing individual contract indicator files

        Returns
        -------
        pd.DataFrame
            Stitched indicators following main contract progression
        """
        if logger.isEnabledFor(logging.INFO):
            logger.info("[INDICATOR_PROCESSOR] Extracting main contract indicators")

        main_contract_indicators = []
        market_data_dir = self._paths.market_data_dir

        for trading_date in trading_dates_list:
            # Get main contract for this date using SHFE contract rules
            try:
                main_contract = get_main_contract(
                    trading_date.date(), self.futures_code,
                    market_data_dir=market_data_dir,
                )
            except ValueError:
                logger.debug(f"No main contract for date: {trading_date}")
                continue

            # Load the contract's indicator file
            contract_file = os.path.join(contract_indicators_dir, f"{main_contract}_indicators.pkl")

            if not os.path.exists(contract_file):
                logger.warning(f"Contract indicator file not found: {contract_file}")
                continue

            contract_data = pd.read_pickle(contract_file)

            # Filter to this specific trading date
            # trading_date column is int64 format (YYYYMMDD), convert for comparison
            trading_date_int = int(trading_date.strftime('%Y%m%d'))
            date_data = contract_data[contract_data['trading_date'] == trading_date_int]

            if not date_data.empty:
                main_contract_indicators.append(date_data)
            else:
                logger.debug(f"No data for {main_contract} on {trading_date_int}")
                

        
        if main_contract_indicators:
            combined_indicators = pd.concat(main_contract_indicators, ignore_index=True)

            # Sort by datetime to ensure chronological order (for intraday data)
            if 'datetime' in combined_indicators.columns:
                combined_indicators = combined_indicators.sort_values('datetime').reset_index(drop=True)
            else:
                combined_indicators = combined_indicators.sort_values('trading_date').reset_index(drop=True)

            # Curve-stage carry: kind-routed curve_carry indicators are built
            # once from the forward curve and left-joined onto the per-date main
            # contract frame (bare canonical names -> exactly what the strategy
            # reads). Dormant unless a curve_carry name was declared.
            if self._curve_carry_list:
                combined_indicators = self._merge_curve_carry_indicators(
                    combined_indicators, market_data_dir
                )

            # Save to strategy_indicators.csv and .pkl in output directory
            csv_file = os.path.join(self.output_dir, "strategy_indicators.csv")
            pkl_file = os.path.join(self.output_dir, "strategy_indicators.pkl")

            # Set date as index before saving (required by data_loader.py)
            combined_indicators_with_index = combined_indicators.copy()
            combined_indicators_with_index['date'] = pd.to_datetime(combined_indicators_with_index['date'])
            combined_indicators_with_index.set_index('date', inplace=True)

            # Save with date as index
            combined_indicators_with_index.to_csv(csv_file, index=True)
            _write_nan_warnings_sidecar(combined_indicators_with_index, csv_file)
            combined_indicators_with_index.to_pickle(pkl_file)

            # Save indicator metadata
            self.save_strategy_indicator_metadata(combined_indicators)

            if logger.isEnabledFor(logging.INFO):
                logger.info(f"[INDICATOR_PROCESSOR] Main contract indicators extracted | rows={len(combined_indicators)}")
                logger.info(f"[INDICATOR_PROCESSOR] Saved | csv={csv_file}, pkl={pkl_file}")
            return combined_indicators_with_index
        else:
            logger.error("[INDICATOR_PROCESSOR] Extraction failed | reason=No main contract indicators")
            return pd.DataFrame()


    def _merge_curve_carry_indicators(
        self, combined_indicators: pd.DataFrame, market_data_dir
    ) -> pd.DataFrame:
        """Left-join the declared ``curve_carry`` indicators onto the per-date
        main-contract frame.

        The series builder reads the forward curve (sort_by_date.csv) once and
        returns the 5 carry indicators date-indexed; we select the declared
        subset by bare canonical name (lower-cased, no param suffix — exactly
        the column names the strategy reads) and join on the ``date`` column.
        Dates absent from the curve are NaN (left join).
        """
        from echolon.indicators.calculators.interday.carry.series_builder import (
            build_carry_indicator_frame,
        )

        carry = build_carry_indicator_frame(
            self.asset, market=self.market, market_data_dir=market_data_dir
        )
        wanted = [name.lower() for name in self._curve_carry_list]
        carry_cols = carry[wanted]

        out = combined_indicators.copy()
        out["date"] = pd.to_datetime(out["date"])
        merged = out.merge(carry_cols, left_on="date", right_index=True, how="left")
        if logger.isEnabledFor(logging.INFO):
            finite = int(merged[wanted[0]].notna().sum()) if wanted else 0
            logger.info(
                f"[INDICATOR_PROCESSOR] Curve-stage carry merged | indicators={wanted}, "
                f"rows={len(merged)}, finite[{wanted[0] if wanted else '-'}]={finite}"
            )
        return merged

    def save_strategy_indicator_metadata(self, combined_indicators: pd.DataFrame) -> None:
        """
        Extract indicator column headers from combined indicators and save metadata.

        Parameters
        ----------
        combined_indicators : pd.DataFrame
            Combined main contract indicators DataFrame
        """
        # Define base columns to exclude (OHLCV, metadata, and market data columns)
        base_columns = [
            'date', 'open', 'high', 'low', 'close', 'volume',
            'prev_close', 'prev_settlement', 'settlement',
            'price_change', 'settlement_change', 'turnover', 'open_interest'
        ]

        # Extract indicator columns (exclude base columns)
        indicator_columns = [col for col in combined_indicators.columns if col not in base_columns]

        # Create metadata dictionary
        metadata = {
            "indicator_columns": indicator_columns
        }

        # Save to JSON file
        metadata_file = os.path.join(self.output_dir, "strategy_indicator_metadata.json")

        with open(metadata_file, 'w') as f:
            json.dump(metadata, f, indent=2)

        if logger.isEnabledFor(logging.INFO):
            logger.info(f"[INDICATOR_PROCESSOR] Metadata saved | indicators={len(indicator_columns)}, path={metadata_file}")

    def get_contract_expiry_date(self, contract_data: pd.DataFrame) -> int:
        """
        Get expiry date for a contract using SHFE contract rules.

        Delegates to get_expiry_date from contract_rules.py for accurate
        calculation using the trading calendar.

        Parameters
        ----------
        contract_data : pd.DataFrame
            Contract OHLCV data with 'contract' column

        Returns
        -------
        int
            Expiry date as integer (YYYYMMDD format)
        """
        if contract_data.empty:
            return 0

        # Get contract name from the data
        contract_name = contract_data['contract'].iloc[0] if 'contract' in contract_data.columns else None

        if not contract_name:
            # Fallback if no contract name
            logger.warning("No contract name found in data, using last date as expiry")
            last_date = contract_data.iloc[-1]['date']
            if isinstance(last_date, str):
                return int(last_date)
            elif isinstance(last_date, (int, float)):
                return int(last_date)
            else:
                return int(last_date.strftime('%Y%m%d'))

        # Use canonical get_expiry_date from contract_rules.py
        # This uses TradingCalendar for accurate last trading day calculation
        expiry_date = get_expiry_date(str(contract_name))

        return int(expiry_date.strftime('%Y%m%d'))


# ---------------------------------------------------------------------------
# Module-level helpers for the unified compute path
# ---------------------------------------------------------------------------
def _prepare_ohlcv_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Apply the same pre-compute normalization to an OHLCV frame that
    :meth:`IndicatorProcessor.process_single_contract` applies to a freshly
    loaded per-contract file, before it reaches :func:`_compute_indicators_for_contract`.

    Steps (order matters — sort is last so the fill/convert steps don't
    depend on row order):

    1. Fill missing ``open``/``high``/``low`` with that row's ``close``.
    2. Convert ``date`` to a real datetime (no-op if already datetime-like).
    3. Sort by ``datetime`` (intraday) or ``date`` (interday) and reset the index.

    Shared by the contract-file path (``process_single_contract``) and the
    caller-injectable frame path (``compute_indicators_from_frame`` in
    ``echolon.indicators.run``) so both feed indicator computation the exact
    same normalized shape — a single-sourced step instead of two copies that
    could drift.
    """
    df = df.copy()

    # Preprocess data: for rows with missing open/high/low values, use close price from same row
    if 'close' in df.columns:
        # Fill missing open values with close price from same row
        if 'open' in df.columns:
            df.loc[df['open'].isna(), 'open'] = df.loc[df['open'].isna(), 'close']

        # Fill missing high values with close price from same row
        if 'high' in df.columns:
            df.loc[df['high'].isna(), 'high'] = df.loc[df['high'].isna(), 'close']

        # Fill missing low values with close price from same row
        if 'low' in df.columns:
            df.loc[df['low'].isna(), 'low'] = df.loc[df['low'].isna(), 'close']

    # Convert date column if needed
    if 'date' in df.columns:
        df['date'] = pd.to_datetime(df['date'], format='%Y%m%d')

    # Sort by datetime for intraday data, or by date for daily data
    if 'datetime' in df.columns:
        df = df.sort_values('datetime').reset_index(drop=True)
    elif 'date' in df.columns:
        df = df.sort_values('date').reset_index(drop=True)

    return df


def _split_curve_carry(
    indicator_list: Dict[str, Dict[str, Any]],
):
    """Partition a declared indicator_list into ``(curve_carry, per_contract)``.

    Routing is by catalog KIND: a name whose ``catalog.info(name).kind`` is
    ``curve_carry`` goes to the dedicated curve stage; everything else — TA-Lib
    indicators AND registered classifiers (which are not in the catalog, so
    ``info()`` is None) — stays on the per-contract path. ``catalog.info`` is
    case-insensitive and returns None on a miss, so unknown / classifier names
    fall through to ``per_contract`` unharmed.
    """
    from echolon.indicators import catalog
    from echolon.indicators.catalog import KIND_CURVE_CARRY

    curve: Dict[str, Dict[str, Any]] = {}
    per_contract: Dict[str, Dict[str, Any]] = {}
    for name, spec in indicator_list.items():
        info = catalog.info(name)
        if info is not None and info.kind == KIND_CURVE_CARRY:
            curve[name] = spec
        else:
            per_contract[name] = spec
    return curve, per_contract

#: Multi-output indicator output names (tuples returned by the calculator).
_MULTI_OUTPUT_NAMES: Dict[str, List[str]] = {
    "BBANDS": ["upper", "middle", "lower"],
    "MACD":   ["macd",  "signal", "hist"],
    "STOCH":  ["k",     "d"],
    "AROON":  ["down",  "up"],
}

#: Param names that represent a simple "period" dimension — when there is only
#: ONE swept dimension and it has one of these names, the column name uses just
#: the numeric value (e.g. ``rsi_14``) rather than the full key=value form
#: (``rsi_timeperiod14``).  Add aliases here if new parameter names arise.
_PERIOD_PARAM_NAMES: frozenset = frozenset({
    "period", "timeperiod", "time_period",
})


def _validate_regime_params(
    indicator_list: Dict[str, Any],
    regime_params: Optional[Dict],
    ctx,
) -> None:
    """Raise ValueError when a registered regime classifier is requested on
    an interday ctx but ``regime_params`` is None.

    Produce ``regime_params`` by registering an optimizer at session start
    (via ``register_regime_optimizer``) and then calling::

        params = echolon.indicators.get_regime_optimizer(name).optimize(
            df=None, n_trials=400, ctx=ctx,
        )

    Args:
        indicator_list: Flat-dict indicator spec (keys are indicator names).
        regime_params: Regime params dict, or None if not provided.
        ctx: TradingContext — used to detect interday frequency via ``ctx.is_intraday``.
    """
    if ctx.is_intraday:
        return  # regime_params not needed for intraday

    # Registry-aware check. Any indicator name that matches a registered
    # classifier requires regime_params (the classifier's hyperparameter dict).
    from echolon.indicators.registry import list_classifiers
    registered = {n.lower() for n in list_classifiers()}
    keys_lower = {k.lower() for k in indicator_list.keys()}
    needs_regime = bool(keys_lower & registered)
    if needs_regime and regime_params is None:
        raise ValueError(
            "indicator_list contains a registered regime classifier name but "
            "regime_params is None. Use the classifier registry: "
            "echolon.indicators.get_regime_optimizer('<classifier_name>').optimize("
            "df=None, n_trials=400, ctx=ctx). "
            "Register the optimizer at session startup via "
            "echolon.indicators.registry.register_regime_optimizer(...)."
        )


def _auto_params_for(
    indicator_name: str,
    regime_params: Optional[Dict],
    default_params: Optional[Dict],
    ctx,
) -> Dict[str, Any]:
    """Return library-derived params the caller need not specify for *indicator_name*.

    The caller's explicit params always override these (applied before expansion).
    """
    up = indicator_name.upper()
    dp = default_params or {}

    if up == "MARKET_REGIME":
        return dict(regime_params) if regime_params else {}

    if up == "VOLATILITY_STATE":
        return {
            "atr_period":    dp.get("atr_period", 14),
            "vol_lookback":  dp.get("vol_lookback", 100),
            "high_percentile": dp.get("volatility_high_pct", 75.0),
            "low_percentile":  dp.get("volatility_low_pct", 25.0),
        }

    if up in ("VOLUME_PERCENTILE", "VOLUME_VS_SESSION_AVG"):
        return {"bars_per_day": ctx.bars_per_day}

    if up in ("NIGHT_OR_HIGH", "NIGHT_OR_LOW", "DAY_OR_HIGH", "DAY_OR_LOW", "OR_BREAKOUT"):
        return {"bar_size_minutes": ctx.bar_size_minutes}

    return {}


def _fmt(v: Any) -> str:
    """Format a scalar value for use in a column-name suffix.

    Rules:
    - float with no fractional part → cast to int first (``2.0`` → ``"2"``)
    - float with fractional part → replace ``"."`` with ``"p"`` (``1.5`` → ``"1p5"``)
    - anything else → ``str(v)``
    """
    if isinstance(v, float):
        if v.is_integer():
            return str(int(v))
        return str(v).replace(".", "p")
    return str(v)


def _build_suffix(combo: Dict[str, Any], swept_keys: List[str]) -> str:
    """Build the column-name suffix from the swept (list-valued) keys.

    Single swept dim that is a "period" param → value only (e.g. ``"14"``).
    All other cases → ``key1value1_key2value2`` pairs.
    """
    if not swept_keys:
        return ""
    if len(swept_keys) == 1 and swept_keys[0] in _PERIOD_PARAM_NAMES:
        return _fmt(combo[swept_keys[0]])
    return "_".join(f"{k}{_fmt(combo[k])}" for k in swept_keys)


def _store_output(
    results: Dict[str, np.ndarray],
    indicator_name: str,
    combo: Dict[str, Any],
    output: Any,
    original_spec: Dict[str, Any],
) -> None:
    """Store one compute result (single or multi-output) into *results*.

    Column names encode only the parameters that were SWEPT (i.e., those whose
    value in *original_spec* is a list).  Fixed-value params are transparent to
    the caller and do not appear in column names.
    """
    base_name = indicator_name.lower()

    # Only params that had list values in the caller's spec are "swept"
    swept_keys = [k for k in combo if isinstance(original_spec.get(k), list)]
    suffix = _build_suffix(combo, swept_keys)

    if isinstance(output, tuple):
        # Multi-output indicator (e.g. BBands → upper/middle/lower)
        output_names = _MULTI_OUTPUT_NAMES.get(
            indicator_name.upper(),
            [f"out{i}" for i in range(len(output))],
        )
        for out_name, arr in zip(output_names, output):
            col = f"{base_name}_{out_name}" + (f"_{suffix}" if suffix else "")
            results[col] = arr
    else:
        col = base_name + (f"_{suffix}" if suffix else "")
        results[col] = output


def _compute_indicators_for_contract(
    df: pd.DataFrame,
    indicator_list: Dict[str, Dict[str, Any]],
    ctx,
    regime_params: Optional[Dict] = None,
    default_params: Optional[Dict] = None,
    session_availability=None,
) -> Dict[str, np.ndarray]:
    """Unified compute path — iterates *indicator_list*, resolves params, computes.

    For each indicator in *indicator_list*:
    1. Look up its TA-Lib wrapper function via :func:`get_function`.
    2. Build library-derived auto-params (regime_params, bars_per_day, etc.).
    3. Merge: ``auto_params | caller_spec`` (caller wins on conflicts).
    4. Expand the merged spec into Cartesian combos via :func:`expand_params_spec`.
    5. For each combo, call the function and store the output with a
       suffix-encoded column name.

    Args:
        df: OHLCV DataFrame.
        indicator_list: Flat-dict ``{indicator_name: {param: value_or_list}}``.
        ctx: :class:`TradingContext` — used for frequency routing and auto-param
            inference (``bars_per_day``, ``bar_size_minutes``).
        regime_params: Regime-classifier params, required when *indicator_list*
            contains ``market_regime`` on an interday ctx.
        default_params: Frequency-scaled defaults from ``ctx.get_indicator_params()``.
        session_availability: Session-availability loader (intraday only).

    Returns:
        Dict mapping column names to computed numpy arrays.
    """
    from echolon.indicators.schema import expand_params_spec
    from echolon.indicators.registry import (
        is_registered_classifier,
        get_regime_classifier,
    )

    _validate_regime_params(indicator_list, regime_params, ctx)

    frequency = "minute" if ctx.is_intraday else "day"
    results: Dict[str, np.ndarray] = {}

    for indicator_name, param_spec in indicator_list.items():
        # Registry-driven dispatch for registered classifiers. If the
        # indicator name matches a registered ``RegimeClassifier``, use its
        # ``fit_classify()`` instead of the indicator_mapping lookup. This
        # is the extension path for paradigm-specific machinery (TRS, HMM,
        # Carry, etc.). Echolon ships zero built-in classifiers; host code
        # registers via ``echolon.indicators.registry.register_regime_classifier``.
        if is_registered_classifier(indicator_name):
            classifier = get_regime_classifier(indicator_name.lower())
            # Build merged params (auto + caller spec). For classifiers,
            # ``regime_params`` is the caller-supplied hyperparameter dict;
            # _auto_params_for returns it as-is for ``MARKET_REGIME``.
            auto_params = _auto_params_for(
                indicator_name, regime_params, default_params, ctx
            )
            merged_params: Dict[str, Any] = {**auto_params, **param_spec}
            series_or_array = classifier.fit_classify(df, merged_params)
            # Normalize to ndarray expected by downstream consumers.
            arr = (
                series_or_array.values
                if hasattr(series_or_array, "values")
                else series_or_array
            )
            results[classifier.name] = arr

            # Optional companion: a per-bar confidence column for classifiers
            # that expose calibrated posteriors. A classifier OPTS IN via an
            # ``emits_confidence`` attribute (True for model-native posteriors
            # such as HMM/GMM; a rule-based score-softmax MUST stay False — an
            # uncalibrated proxy is not honest confidence and emitting it would
            # violate the No-Misleading-Fallback policy).
            #
            # The label column above is left UNCHANGED. Confidence is the
            # posterior of the ASSIGNED label (``proba[label]`` per bar), NOT
            # ``max(proba)``: for a Viterbi labeller (HMM) the most-likely-
            # sequence label can differ from the per-bar argmax of the
            # forward/smoothed posterior, so ``proba[label]`` is the only
            # label-consistent confidence (``max(proba)`` could name a different
            # regime than the stored label → a misleading value).
            #
            # Call-order contract: ``emits_confidence`` / ``fit_classify_proba``
            # are evaluated AFTER ``fit_classify`` on the SAME ``df`` +
            # ``merged_params``, so a stateful host wrapper (e.g. a
            # per-instrument pick dispatcher) can report the EFFECTIVE
            # classifier that actually produced the label and gate the column
            # off when it fell back to a non-confidence method.
            if getattr(classifier, "emits_confidence", False):
                proba_df = classifier.fit_classify_proba(df, merged_params)
                label_map = classifier.label_map
                col_pos = {col: j for j, col in enumerate(proba_df.columns)}
                proba_values = proba_df.values
                label_positions = np.array(
                    [col_pos[label_map[int(v)]] for v in arr]
                )
                confidence = proba_values[np.arange(len(arr)), label_positions]
                results[f"{classifier.name}_confidence"] = confidence
            continue

        function = _resolve_function(indicator_name, frequency=frequency)

        # Library-derived params that caller need not specify
        auto_params = _auto_params_for(indicator_name, regime_params, default_params, ctx)

        # Caller spec overrides auto-params (explicit always wins)
        merged_spec: Dict[str, Any] = {**auto_params, **param_spec}

        combos = expand_params_spec(merged_spec)

        for combo in combos:
            output = function(df, indicator_name=indicator_name, **combo)
            _store_output(results, indicator_name, combo, output, param_spec)

    return results
