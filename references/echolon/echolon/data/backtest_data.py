"""
Data Pipeline Entry Point
=========================

Main orchestrator for market data extraction and preprocessing.

Data Flow:
- Source: data/{market}/{instrument_code}/     (raw data from API/extractor)
- Output: workspace/data/market_data/     (processed data for consumers)

Separation of Concerns:
- Extractors: Retrieve raw data from sources (files, APIs) → save to data/
- Transformers: Process and standardize data
- Loaders: Provide data access for downstream consumers
"""
# NOTE: Do NOT add `from __future__ import annotations` to this module.
# The paths-injection smoke test (tests/data/test_paths_injection.py)
# reads run_data_pipeline's `paths` parameter annotation at runtime
# via inspect.signature(); PEP 563 stringification makes the check silently
# return False.
import logging
from pathlib import Path
from typing import Optional
import pandas as pd

from echolon.config.paths_config import PathsConfig
from echolon.config.markets.factory import MarketFactory
from echolon.config.markets.core.context import TradingContext
from .transformers.ohlcv_standardizer import OHLCVStandardizer
from .transformers.session_filter import SessionFilter
from .transformers.ohlcv_resampler import OHLCVResampler
from .transformers.contract_splitter import ContractSplitter
from .transformers.calendar_generator import CalendarGenerator
from .transformers.shfe_session_analyzer import SHFESessionAnalyzer
from .loaders.calendar_loader import get_trading_calendar_instance

logger = logging.getLogger(__name__)


def run_data_pipeline(
    ctx: TradingContext,
    *,
    paths: PathsConfig | None = None,
    input_dir: Optional[str] = None,
    output_dir: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    skip_extraction: bool = False,
    # Minute-specific options
    start_contract: Optional[str] = None,
) -> bool:
    """
    Run the complete file-based data pipeline.

    This orchestrates:
    1. Raw data extraction from exchange files (Extractor)
    1.5. Generate trading calendar (must happen before standardization)
    2. Data standardization (Transformer: OHLCVStandardizer)
    3. Session filtering - remove out-of-session bars (Transformer: SessionFilter)
    4. Resampling to target frequency (Transformer: OHLCVResampler)
    5. Splitting data by contract (Transformer: ContractSplitter)

    Note: Calendar generation happens early (Step 1.5) because OHLCVStandardizer
    needs it to correctly assign trading_date for night session bars.

    For minute data from API, Step 1 also downloads OHLCV for each contract.

    For live/incremental updates (MiniQMT), use ``run_live_data_update`` from
    ``echolon.data.live_data`` instead.

    Args:
        ctx: TradingContext with market, instrument, frequency configuration
        paths: PathsConfig supplying library-owned directory layout.
               When None the conventional layout rooted at ECHOLON_PROJECT_ROOT
               is used (deprecated fallback — callers SHOULD supply paths).
        input_dir: Raw data input directory (optional, uses default)
        output_dir: Processed data output directory (optional, uses default)
        start_date: Start date for filtering (YYYY-MM-DD)
        end_date: End date for filtering (YYYY-MM-DD)
        skip_extraction: Skip raw data extraction step (reuse existing raw data)
        start_contract: For minute API data - starting contract code (e.g., "2301")

    Returns:
        True if successful

    Example:
        >>> from echolon.config.markets.factory import MarketFactory
        >>> ctx = MarketFactory.create(
        ...     market='SHFE', instrument='al', frequency='interday', bar_size='1d',
        ... )
        >>> run_data_pipeline(ctx, skip_extraction=True)
    """
    if paths is None:
        paths = PathsConfig.from_env()

    # Extract from TradingContext
    market = ctx.market_code
    instrument = ctx.instrument_name
    is_intraday = ctx.is_intraday
    bar_size = ctx.bar_size
    timezone = ctx.timezone

    logger.info(
        f"[DATA_PIPELINE] Starting | market={market}, instrument={instrument}, "
        f"frequency={'intraday' if is_intraday else 'interday'}, bar_size={bar_size}"
    )

    # Determine output directory: workspace/data/market_data/{market}/{instrument}/
    output_path = Path(output_dir) if output_dir else paths.market_data_dir / market / instrument
    output_path.mkdir(parents=True, exist_ok=True)

    # Map frequency for extractor: interday -> "day", intraday -> "minute"
    extractor_frequency = "minute" if is_intraday else "day"

    # Select extractor based on market and frequency (file-based only)
    extractor = _get_extractor(market, instrument, extractor_frequency, paths=paths)

    raw_data = None

    # Step 1: Extract raw data (Extractor responsibility)
    if not skip_extraction:
        # File source: full extraction
        logger.info("[DATA_PIPELINE] Step 1: Extracting raw data")
        raw_data = extractor.extract_raw(
            input_dir=input_dir,
            output_dir=str(output_path),
            start_date=start_date,
            end_date=end_date
        )
        if raw_data.empty:
            logger.error("[DATA_PIPELINE] Extraction failed: no data")
            return False
        logger.info(f"[DATA_PIPELINE] Extracted {len(raw_data)} rows")

        # For minute API extraction, also download OHLCV data per contract
        if is_intraday and hasattr(extractor, 'download_minute_data'):
            logger.info("[DATA_PIPELINE] Step 1b: Downloading minute OHLCV data")
            if start_contract:
                success = extractor.download_minute_data(
                    start_contract=start_contract,
                    period="1m",
                    output_dir=str(output_path)
                )
                if not success:
                    logger.error("[DATA_PIPELINE] Minute data download failed")
                    return False
    else:
        # Load existing raw data from source directory
        logger.info("[DATA_PIPELINE] Step 1: Loading existing raw data (extraction skipped)")
        raw_data = _load_source_data(market, instrument, extractor_frequency, paths=paths)
        if raw_data is None or raw_data.empty:
            logger.error("[DATA_PIPELINE] No existing data found to process")
            return False
        logger.info(f"[DATA_PIPELINE] Loaded {len(raw_data)} rows from source")

    # Step 1.5: Generate trading calendar BEFORE standardization
    # File source: derive calendar from data if it doesn't exist
    _generate_calendar_if_needed(
        raw_data=raw_data,
        output_path=output_path,
        start_date=start_date,
        end_date=end_date,
        timezone=timezone
    )

    # Step 2: Standardize data (Transformer responsibility)
    if raw_data is not None:
        logger.info("[DATA_PIPELINE] Step 2: Standardizing data")
        # Load trading calendar for intraday trading_date calculation
        trading_calendar = get_trading_calendar_instance(
            market, instrument, market_data_dir=paths.market_data_dir,
        )
        standardizer = OHLCVStandardizer(
            fill_missing=True,
            market=market,
            trading_calendar=trading_calendar,
            bar_size=bar_size,  # Pass bar_size for correct session phase names
        )
        raw_data = standardizer.standardize(raw_data, timezone=timezone)
        logger.info(f"[DATA_PIPELINE] Standardized {len(raw_data)} rows")

    # Step 2.5: Analyze session availability (SHFE intraday only)
    # Detects which sessions were active for each trading date (handles holidays)
    if is_intraday and raw_data is not None and market.upper() == "SHFE":
        logger.info("[DATA_PIPELINE] Step 2.5: Analyzing SHFE session availability")
        _analyze_shfe_sessions(
            standardized_data=raw_data,
            output_path=output_path,
            bar_size=bar_size
        )

    # Step 3: Filter out-of-session bars (for intraday only)
    # Removes bars during breaks and outside trading hours
    if is_intraday and raw_data is not None:
        logger.info("[DATA_PIPELINE] Step 3: Filtering out-of-session bars")
        session_filter = SessionFilter(market=market)
        raw_data = session_filter.filter(raw_data)

    # Step 4: Resample to target frequency (for intraday only)
    # Converts 1-minute bars to user-specified frequency (e.g., 5m, 15m, 1h)
    if is_intraday and raw_data is not None and bar_size != "1m":
        logger.info(f"[DATA_PIPELINE] Step 4: Resampling to {bar_size}")
        resampler = OHLCVResampler(target_frequency=bar_size)
        raw_data = resampler.resample(raw_data)
        logger.info(f"[DATA_PIPELINE] Resampled to {len(raw_data)} rows")

    # Step 5: Split by contract (Transformer responsibility)
    if raw_data is not None:
        logger.info("[DATA_PIPELINE] Step 5: Splitting by contract")
        splitter = ContractSplitter(output_dir=str(output_path))
        contracts = splitter.split(raw_data)
        logger.info(f"[DATA_PIPELINE] Split into {len(contracts)} contracts")

    # Step 6: Populate main_contract.csv (required by SHFE adapter +
    # contract-aware broker). Two sources, in priority order:
    #   1. Pre-computed file at {raw_data_dir}/{market}/{instrument_code}/
    #      main_contract.csv — host apps that ship a curated main-contract
    #      timeline (e.g., qorka) keep it next to the raw extractor input
    #      tree. Copy it verbatim.
    #   2. Derive max-volume-per-day from the standardized OHLCV. Used by
    #      fresh `echolon init` workspaces that don't ship a curated file.
    # Goal: every `run_data_pipeline` call leaves market_data_dir/{instrument}/
    # with all four canonical artifacts (sort_by_date.csv, sort_by_contract/,
    # trading_calendar.csv, main_contract.csv) — no separate scaffolding step.
    if raw_data is not None and not is_intraday:
        import shutil
        main_contract_path = output_path / "main_contract.csv"
        raw_main_contract = (
            paths.raw_data_dir / market / ctx.instrument_code / "main_contract.csv"
        )
        if raw_main_contract.is_file():
            logger.info(f"[DATA_PIPELINE] Step 6: Copying main_contract.csv from {raw_main_contract}")
            shutil.copyfile(raw_main_contract, main_contract_path)
        else:
            from echolon.native.cli.init import _derive_main_contract_from_volume
            logger.info("[DATA_PIPELINE] Step 6: Deriving main_contract.csv (max-volume rule)")
            _derive_main_contract_from_volume(raw_data, main_contract_path)

    # Note: Calendar generation moved to Step 1.5 (before standardization)
    # to ensure calendar exists when OHLCVStandardizer calculates trading_date

    logger.info("[DATA_PIPELINE] Complete")
    return True


def _generate_calendar_if_needed(
    raw_data: pd.DataFrame,
    output_path: Path,
    start_date: Optional[str],
    end_date: Optional[str],
    timezone: str = None
) -> None:
    """
    Generate trading calendar from raw data if it doesn't already exist.

    This must run BEFORE standardization because OHLCVStandardizer needs
    the calendar to correctly assign trading_date for night session bars.

    Args:
        raw_data: Raw OHLCV data with datetime information
        output_path: Directory to save calendar file
        start_date: Optional start date filter
        end_date: Optional end date filter
        timezone: Timezone for epoch timestamp conversion (e.g., 'Asia/Shanghai').
                  Required for intraday data with epoch millisecond timestamps.
    """
    if raw_data is None:
        return

    calendar_file = output_path / "trading_calendar.csv"

    # Skip if calendar already exists
    if calendar_file.exists():
        logger.info(f"[DATA_PIPELINE] Trading calendar exists, skipping generation: {calendar_file}")
        return

    logger.info("[DATA_PIPELINE] Generating trading calendar (required for standardization)")
    calendar_gen = CalendarGenerator(output_dir=str(output_path), timezone=timezone)
    calendar = calendar_gen.generate(
        df=raw_data,
        start_date=start_date,
        end_date=end_date
    )
    logger.info(f"[DATA_PIPELINE] Generated calendar with {len(calendar)} trading days")


def _get_extractor(
    market: str,
    instrument: str,
    frequency: str,
    *,
    paths: PathsConfig,
):
    """Get the appropriate file-based extractor for market/frequency combination.

    Forwards ``paths.raw_data_dir`` to the extractor constructor so raw input
    paths respect the caller's ``PathsConfig`` rather than falling back to
    the project-root-derived default.

    For live/incremental extraction (MiniQMT), use
    ``echolon.data.live_data._get_live_extractor`` instead.

    Args:
        market: Market code (e.g., "SHFE")
        instrument: Instrument name (e.g., "aluminum")
        frequency: Data frequency ("day", "minute", etc.)
        paths: Injected PathsConfig (supplies ``raw_data_dir``).
    """
    market_upper = market.upper()

    if market_upper == "SHFE":
        if frequency == "day":
            from .extractors.shfe.file_day_extractor import SHFEFileDayExtractor
            return SHFEFileDayExtractor(market, instrument, raw_data_dir=paths.raw_data_dir)
        elif frequency in ("minute", "1m", "5m", "15m", "1h"):
            from .extractors.shfe.api_minute_extractor import SHFEApiMinuteExtractor
            return SHFEApiMinuteExtractor(market, instrument, raw_data_dir=paths.raw_data_dir)
        else:
            raise ValueError(f"Unsupported frequency: {frequency}")

    elif market_upper == "CRYPTO":
        # TODO: Implement crypto extractor
        raise NotImplementedError("Crypto extractor not yet implemented")

    else:
        raise ValueError(f"Unsupported market: {market}")


def _load_source_data(
    market: str,
    instrument: str,
    frequency: str,
    *,
    paths: PathsConfig,
) -> Optional[pd.DataFrame]:
    """
    Load existing raw data from source directory.

    Source locations:
    - Day data: data/{market}/raw_data/*.xls* or data/{market}/{instrument_code}/sort_by_date.csv
    - Minute data: data/{market}/{instrument_code}/minute_data/*.csv

    Args:
        market: Market code (e.g., "SHFE")
        instrument: Instrument name (e.g., "aluminum")
        frequency: Data frequency ("day", "minute", etc.)
        paths: PathsConfig supplying ``raw_data_dir``.

    Returns:
        DataFrame with combined data, or None if not found
    """
    # Get instrument code using MarketFactory (supports both code and name lookup)
    instrument_spec = MarketFactory.get_instrument_flexible(market, instrument)
    instrument_code = instrument_spec.code
    is_minute = frequency in ("minute", "1m", "5m", "15m", "1h")

    if is_minute:
        # Load minute data: multiple per-contract files
        source_dir = paths.raw_data_dir / market / instrument_code / "minute_data"
        if not source_dir.exists():
            logger.warning(f"[DATA_PIPELINE] Minute data directory not found: {source_dir}")
            return None

        csv_files = list(source_dir.glob("*.csv"))
        if not csv_files:
            logger.warning(f"[DATA_PIPELINE] No CSV files found in {source_dir}")
            return None

        logger.info(f"[DATA_PIPELINE] Loading {len(csv_files)} contract files from {source_dir}")

        all_data = []
        for csv_file in csv_files:
            df = pd.read_csv(csv_file)
            # Add contract column from filename if not present
            if 'contract' not in df.columns:
                contract_name = csv_file.stem  # e.g., "al2301"
                df['contract'] = contract_name
            all_data.append(df)

        if not all_data:
            return None

        combined = pd.concat(all_data, ignore_index=True)

        # Filter out suspended bars (suspendFlag=0 means active, suspendFlag=1 means suspended)
        # This is critical for SHFE minute data where bars exist but trading was suspended
        # (e.g., night session before holidays)
        if 'suspendFlag' in combined.columns:
            before_count = len(combined)
            combined = combined[combined['suspendFlag'] == 0]
            filtered_count = before_count - len(combined)
            if filtered_count > 0:
                logger.info(
                    f"[DATA_PIPELINE] Filtered {filtered_count} suspended bars "
                    f"(suspendFlag=1), {len(combined)} active bars remaining"
                )

        return combined

    else:
        # Load pre-extracted day data from sort_by_date.csv
        source_csv = paths.raw_data_dir / market / instrument_code / "sort_by_date.csv"
        if source_csv.exists():
            logger.info(f"[DATA_PIPELINE] Loading day data from {source_csv}")
            return pd.read_csv(source_csv)

        logger.warning(
            f"[DATA_PIPELINE] Pre-extracted day data not found at {source_csv}. "
            f"Run once with skip_extraction=False to populate it."
        )
        return None


def _analyze_shfe_sessions(
    standardized_data: pd.DataFrame,
    output_path: Path,
    bar_size: str
) -> None:
    """
    Analyze SHFE session availability from standardized OHLCV data.

    This detects which sessions (night, morning, afternoon) were active
    for each trading date, handling irregular session availability due
    to holidays.

    Uses session definitions from: config/markets/shfe/phases.py

    Args:
        standardized_data: Standardized OHLCV data with session_phase and trading_date
        output_path: Directory to save session availability file
        bar_size: Bar size string (e.g., "5m", "15m")
    """
    # Parse bar size to minutes
    bar_size_minutes = _parse_bar_size_minutes(bar_size)

    # Analyze sessions - pass bar_size for correct phase names (granular vs aggregated)
    analyzer = SHFESessionAnalyzer(bar_size_minutes=bar_size_minutes, bar_size=bar_size)
    session_info = analyzer.analyze_from_ohlcv(standardized_data)

    # Save session availability info
    analyzer.save_session_info(session_info, output_path)

    # Enhance calendar with session info if calendar exists
    calendar_file = output_path / "trading_calendar.csv"
    if calendar_file.exists():
        calendar_df = pd.read_csv(calendar_file)
        enhanced_calendar = analyzer.enhance_calendar(calendar_df, session_info)
        enhanced_calendar.to_csv(calendar_file, index=False)
        logger.info(f"[DATA_PIPELINE] Enhanced calendar with session availability: {calendar_file}")


def _parse_bar_size_minutes(bar_size: str) -> int:
    """
    Parse bar size string to minutes.

    Args:
        bar_size: Bar size string (e.g., "1m", "5m", "15m", "1h", "1d")

    Returns:
        Bar size in minutes
    """
    if bar_size.endswith('min'):
        return int(bar_size[:-3])
    elif bar_size.endswith('m'):
        return int(bar_size[:-1])
    elif bar_size.endswith('h'):
        return int(bar_size[:-1]) * 60
    elif bar_size.endswith('d'):
        return int(bar_size[:-1]) * 60 * 24
    else:
        raise ValueError(
            f"Cannot parse bar_size '{bar_size}' - expected format like '5m', '15min', '1h', or '1d'"
        )

