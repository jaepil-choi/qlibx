"""
Data Loader for Quant Engine
============================

Unified data loading utilities for backtesting and optimization.

All functions accept TradingContext (ctx) as the single source of truth
for market and instrument configuration.

Usage:
    from echolon.config.markets.factory import MarketFactory

    ctx = MarketFactory.create(
        market='SHFE', instrument='al', frequency='interday', bar_size='1d',
    )
    indicators, calendar = load_backtest_data(ctx)
    metadata = load_indicator_metadata(ctx)
"""

import pandas as pd
import os
import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional

from echolon.config.markets.factory import MarketFactory
from echolon.config.markets.core.context import TradingContext

logger = logging.getLogger(__name__)


def _convert_contract_to_numeric(contract_str: str, contract_prefix: str) -> int:
    """
    Convert SHFE contract string (e.g., 'al1803') to numeric (e.g., 1803).

    Backtrader data feed lines must be numeric. This converts the contract
    identifier while preserving the contract month information needed for
    expiry detection.

    Args:
        contract_str: Contract string like 'al1803', 'cu2401'
        contract_prefix: Instrument code prefix like 'al', 'cu'

    Returns:
        Numeric contract identifier (e.g., 1803, 2401) or 0 if invalid
    """
    if pd.isna(contract_str):
        return 0
    contract_str = str(contract_str).lower()
    if contract_str.startswith(contract_prefix):
        numeric_part = contract_str[len(contract_prefix):]
        return int(numeric_part) if numeric_part.isdigit() else 0
    return int(contract_str) if str(contract_str).isdigit() else 0


# Session phase encoding - use TradingContext.encode_phase() which is bar_size-aware
# For 30m/1h bars: 'night_session'->1, 'day_session'->2
# For 5m/15m bars: 'night'->1, 'morning'->2, etc.


def load_backtest_data(
    ctx: TradingContext,
    indicators_path: Optional[str] = None,
    *,
    indicator_dir: Optional[Path] = None,
    market_data_dir: Optional[Path] = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Load previously prepared backtest data (enriched continuous OHLCV, trading calendar)
    from the processed data directory.

    Args:
        ctx: TradingContext with market and instrument configuration
        indicators_path: Optional explicit path to strategy_indicators.csv.
            If provided, loads from this path instead of the default
            indicator_dir/{instrument}/strategy_indicators.csv.
        indicator_dir: Root directory for pre-calculated indicators
            (PathsConfig.indicators_backtest_dir). When None, falls back to a
            PathsConfig built from ECHOLON_PROJECT_ROOT (deprecated — callers
            SHOULD supply indicator_dir).
        market_data_dir: Root directory for processed market data. When None,
            falls back to a PathsConfig built from ECHOLON_PROJECT_ROOT
            (deprecated — callers SHOULD supply market_data_dir).

    Returns:
        Tuple of (indicators_data DataFrame, trading_calendar DataFrame).
    """
    market = ctx.market_code
    instrument = ctx.instrument_name
    instrument_code = ctx.instrument_code

    indicators_data = None
    trading_calendar = None

    # --- Load pre-calculated indicators ---
    if indicators_path is None:
        if indicator_dir is None:
            from echolon.errors import raise_error
            raise_error(
                "CFG-003",
                function="load_backtest_data",
                param="indicators_path= or indicator_dir=",
                paths_field="indicators_backtest_dir",
            )
        indicators_path = os.path.join(str(indicator_dir), instrument, "strategy_indicators.csv")
    indicators_data = pd.read_csv(indicators_path)

    # Surface IND-003 sidecar warnings written by indicators/engine/processor
    import json as _json
    _sidecar_path = Path(indicators_path).with_suffix(Path(indicators_path).suffix + ".warnings.json")
    if _sidecar_path.exists():
        try:
            _payload = _json.loads(_sidecar_path.read_text())
            for _col, _info in _payload.get("warnings", {}).items():
                logger.warning(
                    f"[DATA_LOADER] {_info.get('code', 'IND-003')}: indicator "
                    f"'{_col}' has {_info.get('nan_ratio', 0):.1%} NaN "
                    f"({_info.get('nan_rows')}/{_info.get('rows')} rows)"
                )
        except (_json.JSONDecodeError, OSError):
            pass  # Sidecar is best-effort; don't let a corrupt sidecar break loading

    # For intraday data: use 'datetime' column as index (has time component)
    # For interday data: fall back to 'date' column
    # Backtrader's PandasData uses the index for datetime tracking (datetime=None in params)
    if 'datetime' in indicators_data.columns:
        # Use datetime column as index - this provides unique timestamps per bar
        indicators_data['datetime'] = pd.to_datetime(indicators_data['datetime'])
        indicators_data = indicators_data.set_index('datetime')
        indicators_data = indicators_data.sort_index()  # Ensure chronological order
        # Drop redundant date column
        if 'date' in indicators_data.columns:
            indicators_data = indicators_data.drop(columns=['date'])
    elif 'date' in indicators_data.columns:
        # Fallback for interday data
        indicators_data['date'] = pd.to_datetime(indicators_data['date'])
        indicators_data = indicators_data.set_index('date')
        indicators_data = indicators_data.sort_index()  # Ensure chronological order

    indicators_data.index.name = None  # Remove index name to avoid backtrader conflicts

    # Convert string columns to numeric for backtrader compatibility
    # Backtrader lines must be numeric - strings will cause TypeError

    # 1. Convert contract column (e.g., 'al1803' -> 1803)
    if 'contract' in indicators_data.columns:
        indicators_data['contract'] = indicators_data['contract'].apply(
            lambda x: _convert_contract_to_numeric(x, instrument_code)
        )

    # 2. Convert session_phase columns to numeric encoding
    # Uses ctx.encode_phase() which is bar_size-aware (30m/1h uses aggregated encoding)
    for col in indicators_data.columns:
        if col.lower().startswith('session_phase'):
            indicators_data[col] = indicators_data[col].apply(
                lambda x: ctx.encode_phase(x) if pd.notna(x) else 0
            )

    if logger.isEnabledFor(logging.INFO):
        logger.info(f"[DATA_LOADER] Indicator data loaded | path={indicators_path}")

    # --- Load trading calendar ---
    if market_data_dir is None:
        from echolon.errors import raise_error
        raise_error(
            "CFG-003",
            function="load_backtest_data",
            param="market_data_dir=",
            paths_field="market_data_dir",
        )
    calendar_path = os.path.join(str(market_data_dir), market.upper(), instrument, "trading_calendar.csv")
    trading_calendar = pd.read_csv(calendar_path)
    trading_calendar['date'] = pd.to_datetime(trading_calendar['date'])
    if logger.isEnabledFor(logging.INFO):
        logger.info(f"[DATA_LOADER] Trading calendar loaded | path={calendar_path}")

    return indicators_data, trading_calendar


def load_best_params(params_file_path: str) -> dict:
    """
    Loads the best parameters from a JSON file.

    Args:
        params_file_path: Path to the parameters JSON file.

    Returns:
        A dictionary containing the best parameters.
    """
    with open(params_file_path, 'r') as f:
        best_params = json.load(f)
    if logger.isEnabledFor(logging.INFO):
        logger.info(f"[DATA_LOADER] Best parameters loaded | path={params_file_path}")
    return best_params


def load_indicator_metadata(
    ctx: TradingContext,
    metadata_path: Optional[str] = None,
    *,
    indicator_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Load indicator metadata from the standard location.

    Args:
        ctx: TradingContext with market and instrument configuration
        metadata_path: Optional explicit path to metadata JSON.
            If provided, loads from this path instead of the default.
        indicator_dir: Root directory for pre-calculated indicators
            (PathsConfig.indicators_backtest_dir). When None, falls back to a
            PathsConfig built from ECHOLON_PROJECT_ROOT (deprecated — callers
            SHOULD supply indicator_dir).

    Returns:
        Indicator metadata dictionary
    """
    if metadata_path is None:
        if indicator_dir is None:
            from echolon.errors import raise_error
            raise_error(
                "CFG-003",
                function="load_indicator_metadata",
                param="metadata_path= or indicator_dir=",
                paths_field="indicators_backtest_dir",
            )
        instrument = ctx.instrument_name
        metadata_path = os.path.join(str(indicator_dir), instrument, "strategy_indicator_metadata.json")
    with open(metadata_path, 'r') as f:
        metadata = json.load(f)
    return metadata
