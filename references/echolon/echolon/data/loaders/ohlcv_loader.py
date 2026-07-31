"""
OHLCV Data Loader
=================

Provides unified interface for loading standardized OHLCV data.
Ensures proper data types for downstream consumption (e.g., talib requires float64).

Multi-frequency support (Q48 NEGATIVE finding — qorka 2026-05-12 audit,
shipped as Wave 1A Gate 1A T23):
- Daily (1d): legacy single-file layout
  ``{market_data_dir}/{MARKET}/{asset}/sort_by_date.csv``
- Intraday (1m/5m/15m/1h): frequency-disambiguated subdirectory layout
  ``{market_data_dir}/{MARKET}/{asset}/{frequency}/sort_by_date.csv``

Default `frequency="1d"` preserves backward compatibility for all
existing callers — only new intraday consumers (TRS hardened regime
features, intraday-paradigm Wave 4 scope) pass non-default frequency.
"""
import os
import logging
import numpy as np
import pandas as pd
from typing import Literal, Optional, List
from pathlib import Path

from echolon.errors import raise_error

logger = logging.getLogger(__name__)

# Columns that must be float64 for numeric computation (e.g., talib)
NUMERIC_COLUMNS = ['open', 'high', 'low', 'close', 'volume', 'turnover', 'open_interest']

# Datetime columns per schema (must be datetime64[ns])
DATETIME_COLUMNS = ['date', 'datetime']

# Supported frequency literals per Q48 spec (qorka docs/4_plans/wave_1/
# 2026-05-13-gate-1a-foundation.md T23). Daily is the legacy default;
# 1m/5m/15m/1h are intraday tiers added 2026-05-13.
FrequencyLiteral = Literal["1d", "1m", "5m", "15m", "1h"]
SUPPORTED_FREQUENCIES = frozenset({"1d", "1m", "5m", "15m", "1h"})


def _ensure_numeric_types(df: pd.DataFrame) -> pd.DataFrame:
    """
    Ensure OHLCV columns are float64 for numeric computation.

    Args:
        df: DataFrame with OHLCV data

    Returns:
        DataFrame with proper numeric types
    """
    for col in NUMERIC_COLUMNS:
        if col in df.columns:
            df[col] = df[col].astype(np.float64)
    return df


def _ensure_datetime_types(df: pd.DataFrame) -> pd.DataFrame:
    """
    Ensure datetime columns are datetime64[ns] per schema.

    When loading from CSV, datetime columns become strings.
    This converts them back to proper datetime type.

    Args:
        df: DataFrame with potential datetime columns

    Returns:
        DataFrame with proper datetime types
    """
    for col in DATETIME_COLUMNS:
        if col in df.columns and not pd.api.types.is_datetime64_any_dtype(df[col]):
            if pd.api.types.is_integer_dtype(df[col]):
                # Integer dates in YYYYMMDD format (e.g., 20250318)
                df[col] = pd.to_datetime(df[col].astype(str), format='%Y%m%d')
            else:
                df[col] = pd.to_datetime(df[col])
    return df


def load_ohlcv(
    market: str,
    asset: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    *,
    market_data_dir: Path,
    frequency: FrequencyLiteral = "1d",
) -> pd.DataFrame:
    """
    Load standardized OHLCV data for a market/asset at a given frequency.

    Args:
        market: Market code (e.g., "SHFE")
        asset: Asset name (e.g., "aluminum")
        start_date: Optional start date filter (YYYY-MM-DD)
        end_date: Optional end date filter (YYYY-MM-DD)
        market_data_dir: Required root directory for processed market data
              (typically ``paths.market_data_dir``).
        frequency: Bar frequency. ``"1d"`` (default — backward-compat for
              all pre-2026-05-13 callers) resolves to the legacy single-file
              layout ``{market_data_dir}/{MARKET}/{asset}/sort_by_date.csv``.
              Intraday frequencies (``"1m"``, ``"5m"``, ``"15m"``, ``"1h"``)
              resolve to ``{market_data_dir}/{MARKET}/{asset}/{frequency}/sort_by_date.csv``.
              Per Q48 (qorka decisions_log.md 2026-05-12).

    Returns:
        DataFrame with OHLCV data. For ``frequency="1d"``, the time column is
        ``date``; for intraday frequencies, it's ``datetime`` (per `_ensure_datetime_types`).
        Date-range filters apply to whichever column is present.

    Raises:
        ValueError: if ``frequency`` is not in :data:`SUPPORTED_FREQUENCIES`.
        Echolon DAT-001 error: if the resolved file path does not exist.
    """
    if frequency not in SUPPORTED_FREQUENCIES:
        raise_error(
            "DAT-005",
            frequency=frequency,
            supported=sorted(SUPPORTED_FREQUENCIES),
        )

    # Per Q48 spec: daily uses legacy single-file layout; intraday uses
    # frequency-disambiguated subdirectory. Backward-compat for daily
    # callers is the explicit goal of the default.
    if frequency == "1d":
        data_file = os.path.join(
            str(market_data_dir), market.upper(), asset, "sort_by_date.csv"
        )
    else:
        data_file = os.path.join(
            str(market_data_dir), market.upper(), asset, frequency, "sort_by_date.csv"
        )

    if not os.path.exists(data_file):
        logger.error(f"[OHLCV_LOADER] File not found: {data_file}")
        raise_error("DAT-001", path=data_file, field="market_data_dir")

    df = pd.read_csv(data_file)

    # Ensure proper data types per schema
    df = _ensure_numeric_types(df)
    df = _ensure_datetime_types(df)

    # Apply date filters — intraday data uses 'datetime' column, daily uses 'date'.
    # Pick whichever exists; this keeps the API uniform across frequencies.
    time_col = 'datetime' if 'datetime' in df.columns else 'date'
    if start_date:
        df = df[df[time_col] >= pd.to_datetime(start_date)]
    if end_date:
        df = df[df[time_col] <= pd.to_datetime(end_date)]

    logger.info(
        f"[OHLCV_LOADER] Loaded {len(df)} rows | {market}/{asset} | frequency={frequency}"
    )
    return df


def load_contract_ohlcv(
    market: str,
    asset: str,
    contract: str,
    *,
    market_data_dir: Path,
) -> Optional[pd.DataFrame]:
    """
    Load OHLCV data for a specific contract.

    Args:
        market: Market code (e.g., "SHFE")
        asset: Asset name (e.g., "aluminum")
        contract: Contract identifier (e.g., "al2403")
        market_data_dir: Required root directory for processed market data
              (typically ``paths.market_data_dir``). Resolved as
              ``{market_data_dir}/{MARKET}/{asset}/sort_by_contract/{contract}.csv``.

    Returns:
        DataFrame with contract OHLCV data, or None if not found
    """
    contract_file = os.path.join(
        str(market_data_dir), market.upper(), asset, "sort_by_contract", f"{contract}.csv"
    )

    if not os.path.exists(contract_file):
        logger.warning(f"[OHLCV_LOADER] Contract not found: {contract}")
        return None

    df = pd.read_csv(contract_file)

    # Ensure proper data types per schema
    df = _ensure_numeric_types(df)
    df = _ensure_datetime_types(df)

    return df


def get_available_contracts(
    market: str,
    asset: str,
    *,
    market_data_dir: Optional[Path] = None,
) -> List[str]:
    """
    Get list of available contracts for a market/asset.

    Args:
        market: Market code (e.g., "SHFE")
        asset: Asset name (e.g., "aluminum")
        market_data_dir: Required root directory for processed market data
              (typically ``paths.market_data_dir``). Missing value raises CFG-003.

    Returns:
        List of contract identifiers
    """
    if market_data_dir is None:
        raise_error(
            "CFG-003",
            function="get_available_contracts",
            param="market_data_dir=",
            paths_field="market_data_dir",
        )
    contract_dir = os.path.join(str(market_data_dir), market.upper(), asset, "sort_by_contract")

    if not os.path.exists(contract_dir):
        return []

    contracts = []
    for f in Path(contract_dir).glob("*.csv"):
        contracts.append(f.stem)

    return sorted(contracts)
