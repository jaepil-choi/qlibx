"""
Live Data-Update Orchestrator
==============================

Incremental bar downloads and live-source calendar updates via a
caller-injected client.

Typical call from a live-deploy runner::

    from echolon.data.live_data import run_live_data_update
    run_live_data_update(ctx, client=xtdc, trading_calendar_path=config.trading_calendar_path)
"""
# NOTE: Do NOT add `from __future__ import annotations` to this module.
# The paths-injection smoke test (tests/data/test_paths_injection.py)
# reads run_live_data_update's `paths` parameter annotation at runtime
# via inspect.signature(); PEP 563 stringification makes the check silently
# return False. If you want PEP 604 union syntax (`PathsConfig | None`),
# Python 3.10+ already provides it at runtime without the __future__ import.
import logging
from pathlib import Path
from typing import Optional

import pandas as pd

from echolon.config.markets.core.context import TradingContext
from echolon.config.paths_config import PathsConfig
from .transformers.ohlcv_standardizer import OHLCVStandardizer
from .transformers.session_filter import SessionFilter
from .transformers.ohlcv_resampler import OHLCVResampler
from .transformers.contract_splitter import ContractSplitter
from .transformers.shfe_session_analyzer import SHFESessionAnalyzer
from .loaders.calendar_loader import get_trading_calendar_instance

logger = logging.getLogger(__name__)


def run_live_data_update(
    ctx: TradingContext,
    client,                                         # XtdataClient or similar; required
    *,
    paths: Optional[PathsConfig] = None,
    output_dir: Optional[str] = None,
    trading_calendar_path: Optional[str] = None,
    present_date=None,
    skip_calendar: bool = False,
) -> bool:
    """Incremental bar download + transform for a running live deploy.

    The two key live-specific steps:

    * Step 1  — ``extractor.extract_raw(output_dir=…)``  (incremental update,
      uses the injected *client* internally)
    * Step 1.5 — ``extractor.generate_trading_calendar(source_path=…)``  for
      SHFE extractors that support it

    Shared transformation steps (standardise → session-filter → resample →
    split) are identical to the file-based pipeline.

    Args:
        ctx:                    TradingContext with market/instrument/frequency.
        client:                 Caller-injected data client (protocol: XtdataClient).
                                Required — echolon does not ship a broker SDK.
        paths:                  PathsConfig supplying library-owned directory layout.
                                When None the conventional layout rooted at
                                ECHOLON_PROJECT_ROOT is used (deprecated fallback —
                                callers SHOULD supply paths).
        output_dir:             Destination for per-contract CSVs.  Defaults to
                                ``paths.market_data_dir / {market} / {instrument}``.
        trading_calendar_path:  Path to user-supplied ``trading_calendar.csv``
                                (SHFE live deploys require this).
        present_date:           Reference date; defaults to today.
        skip_calendar:          Skip the live calendar update step (set when the
                                caller has already ensured the calendar).

    Returns:
        True if successful.
    """
    if paths is None:
        paths = PathsConfig.from_env()

    market = ctx.market_code
    instrument = ctx.instrument_name
    is_intraday = ctx.is_intraday
    bar_size = ctx.bar_size
    timezone = ctx.timezone

    logger.info(
        f"[LIVE_DATA] Starting | market={market}, instrument={instrument}, "
        f"frequency={'intraday' if is_intraday else 'interday'}, bar_size={bar_size}"
    )

    output_path = Path(output_dir) if output_dir else paths.market_data_dir / market / instrument
    output_path.mkdir(parents=True, exist_ok=True)

    extractor_frequency = "minute" if is_intraday else "day"
    extractor = _get_live_extractor(market, instrument, extractor_frequency)

    # Inject caller-supplied client and present_date
    # All extractors from _get_live_extractor support these (no hasattr check needed)
    extractor.set_client(client)
    if present_date is not None:
        extractor.present_date = present_date

    # Step 1: Incremental extraction
    contract_data_dir = str(output_path / f"{extractor.futures_code}_by_contract")
    logger.info(
        f"[LIVE_DATA] Step 1: Incremental update via live client → {contract_data_dir}"
    )
    raw_data = extractor.extract_raw(output_dir=contract_data_dir, save=False)
    if raw_data is None or raw_data.empty:
        logger.error("[LIVE_DATA] Live incremental update failed: no data returned")
        return False
    logger.info(f"[LIVE_DATA] Incremental update: {len(raw_data)} rows")

    # Step 1.5: Update trading calendar from caller-supplied CSV
    # All extractors support generate_trading_calendar; check capability to avoid
    # unnecessary calls (calendar_load extractors load pre-computed, calendar_generate
    # ones derive from data)
    if not skip_calendar and (
        "calendar_generate" in extractor.capabilities
        or "calendar_load" in extractor.capabilities
    ):
        logger.info("[LIVE_DATA] Step 1.5: Updating trading calendar")
        calendar = extractor.generate_trading_calendar(
            source_path=trading_calendar_path,
            output_dir=str(output_path),
        )
        if not calendar.empty:
            logger.info(f"[LIVE_DATA] Trading calendar updated: {len(calendar)} dates")
        else:
            logger.warning("[LIVE_DATA] Trading calendar update returned empty")

    # Step 2: Standardise
    logger.info("[LIVE_DATA] Step 2: Standardising data")
    trading_calendar = get_trading_calendar_instance(
        market, instrument, market_data_dir=paths.market_data_dir,
    )
    standardizer = OHLCVStandardizer(
        fill_missing=True,
        market=market,
        trading_calendar=trading_calendar,
        bar_size=bar_size,
    )
    raw_data = standardizer.standardize(raw_data, timezone=timezone)
    logger.info(f"[LIVE_DATA] Standardised {len(raw_data)} rows")

    # Step 2.5: Analyse SHFE session availability (intraday only)
    if is_intraday and raw_data is not None and market.upper() == "SHFE":
        logger.info("[LIVE_DATA] Step 2.5: Analysing SHFE session availability")
        _analyze_shfe_sessions(
            standardized_data=raw_data,
            output_path=output_path,
            bar_size=bar_size,
        )

    # Step 3: Filter out-of-session bars
    if is_intraday and raw_data is not None:
        logger.info("[LIVE_DATA] Step 3: Filtering out-of-session bars")
        session_filter = SessionFilter(market=market)
        raw_data = session_filter.filter(raw_data)

    # Step 4: Resample
    if is_intraday and raw_data is not None and bar_size != "1m":
        logger.info(f"[LIVE_DATA] Step 4: Resampling to {bar_size}")
        resampler = OHLCVResampler(target_frequency=bar_size)
        raw_data = resampler.resample(raw_data)
        logger.info(f"[LIVE_DATA] Resampled to {len(raw_data)} rows")

    # Step 5: Split by contract
    if raw_data is not None:
        logger.info("[LIVE_DATA] Step 5: Splitting by contract")
        splitter = ContractSplitter(output_dir=str(output_path))
        contracts = splitter.split(raw_data)
        logger.info(f"[LIVE_DATA] Split into {len(contracts)} contracts")

    # Step 6: Copy main_contract.csv to canonical location.
    # extract_raw writes it to <instrument>/<futures_code>_by_contract/main_contract.csv
    # but the SHFE contract loader (echolon/markets/shfe/contract_rules.py)
    # reads it from <instrument>/main_contract.csv. Without this copy, the
    # live runner's slot.initialize() fails with DAT-003 immediately.
    # Mirrors backtest_data.run_data_pipeline Step 6.
    if not is_intraday:
        import shutil
        canonical_path = output_path / "main_contract.csv"
        source_path = output_path / f"{extractor.futures_code}_by_contract" / "main_contract.csv"
        if source_path.is_file():
            logger.info(
                f"[LIVE_DATA] Step 6: Copying main_contract.csv "
                f"{source_path} → {canonical_path}"
            )
            shutil.copyfile(source_path, canonical_path)
        else:
            logger.warning(
                f"[LIVE_DATA] Step 6: main_contract.csv missing at {source_path}; "
                "downstream slot.initialize() will fail with DAT-003"
            )

    logger.info("[LIVE_DATA] Complete")
    return True


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _get_live_extractor(market: str, instrument: str, frequency: str):
    """Return a live-capable extractor for the given market/frequency.

    Currently only SHFE interday live extraction is supported
    (``SHFEApiDayExtractor``).  Raise ``ValueError`` for unsupported
    combinations so callers get a clear error rather than a silent fallback
    to file-based extraction.
    """
    market_upper = market.upper()

    if market_upper == "SHFE":
        if frequency == "day":
            from .extractors.shfe.api_day_extractor import SHFEApiDayExtractor
            return SHFEApiDayExtractor(market, instrument)
        else:
            raise ValueError(
                f"Live extraction for SHFE frequency '{frequency}' is not yet supported. "
                "Only 'day' (interday) is available via SHFEApiDayExtractor."
            )

    raise ValueError(
        f"Live extraction is not supported for market '{market}'. "
        "Currently supported: SHFE/day."
    )


def _analyze_shfe_sessions(
    standardized_data: pd.DataFrame,
    output_path: Path,
    bar_size: str,
) -> None:
    """Analyse SHFE session availability from standardised OHLCV data."""
    bar_size_minutes = _parse_bar_size_minutes(bar_size)
    analyzer = SHFESessionAnalyzer(bar_size_minutes=bar_size_minutes, bar_size=bar_size)
    session_info = analyzer.analyze_from_ohlcv(standardized_data)
    analyzer.save_session_info(session_info, output_path)

    calendar_file = output_path / "trading_calendar.csv"
    if calendar_file.exists():
        calendar_df = pd.read_csv(calendar_file)
        enhanced_calendar = analyzer.enhance_calendar(calendar_df, session_info)
        enhanced_calendar.to_csv(calendar_file, index=False)
        logger.info(f"[LIVE_DATA] Enhanced calendar with session availability: {calendar_file}")


def _parse_bar_size_minutes(bar_size: str) -> int:
    """Parse a bar-size string (e.g. '5m', '15min', '1h', '1d') to minutes."""
    if bar_size.endswith("min"):
        return int(bar_size[:-3])
    elif bar_size.endswith("m"):
        return int(bar_size[:-1])
    elif bar_size.endswith("h"):
        return int(bar_size[:-1]) * 60
    elif bar_size.endswith("d"):
        return int(bar_size[:-1]) * 60 * 24
    else:
        raise ValueError(
            f"Cannot parse bar_size '{bar_size}' — expected format like '5m', '15min', '1h', or '1d'"
        )
