"""
Indicators Module Entry Point
=============================

Main orchestrator for technical indicator calculation.
Uses data_pipeline loaders for standardized data access.

Output directory: workspace/data/indicators/backtest/{instrument}/
"""
import os
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime
import pandas as pd

from echolon.config.markets.core.context import TradingContext
from echolon.errors import raise_error
from echolon.indicators.schema import IndicatorList

logger = logging.getLogger(__name__)


def run_indicator_calculation(
    ctx: TradingContext,
    output_dir: str,
    indicator_list: Dict[str, Dict[str, Any]],
    *,
    trading_dates: Optional[List[datetime]] = None,
    use_parallel: bool = True,
    regime_params: Optional[Dict[str, Any]] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    paths: "PathsConfig",  # type: ignore[name-defined]
) -> pd.DataFrame:
    """
    Run indicator calculation on market data.

    This orchestrates:
    1. Loading OHLCV data via data_pipeline loaders
    2. Calculating technical indicators for each contract
    3. Extracting main contract indicators
    4. Saving results

    Args:
        ctx: TradingContext with market, instrument, frequency configuration.
        output_dir: Directory to save indicator files.
        indicator_list: Flat-dict indicator specification passed directly to
            :class:`IndicatorProcessor`.  Keys are indicator names (lower-case);
            values are param dicts supporting Cartesian sweeps.  For example::

                {"rsi": {"timeperiod": [5, 30]}, "market_regime": {}}

        trading_dates: List of trading dates to process (optional; loads from
            calendar if None). If None, start_date and end_date are required.
        use_parallel: Use parallel processing.
        regime_params: Regime classification parameters required when
            *indicator_list* contains a registered classifier name on an
            interday ctx. Produce via
            ``echolon.indicators.get_regime_optimizer(name).optimize(
            df=None, n_trials=400, ctx=ctx)`` after the optimizer has been
            registered. Register classifiers + optimizers via
            ``echolon.indicators.registry.register_regime_classifier()`` /
            ``register_regime_optimizer()`` at session startup.
        start_date: ISO date string for backtest start (e.g. ``"2018-01-01"``).
            Required if trading_dates is None.
        end_date: ISO date string for backtest end.
            Required if trading_dates is None.
        paths: Required PathsConfig built once at program startup.

    Returns:
        DataFrame with main contract indicators.

    Raises:
        ValueError: If trading_dates is None and start_date/end_date are not provided.
    """
    # Validate indicator_list schema early for fail-fast
    IndicatorList.model_validate(indicator_list)

    # Extract from TradingContext
    market = ctx.market_code
    instrument = ctx.instrument_name
    is_intraday = ctx.is_intraday

    # Map frequency for processor: interday -> "day", intraday -> "minute"
    processor_frequency = "minute" if is_intraday else "day"

    logger.info(
        f"[INDICATORS] Starting | market={market}, instrument={instrument}, "
        f"freq={processor_frequency}, indicators={len(indicator_list)}"
    )

    # Ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)
    logger.info(f"[INDICATORS] Output directory | path={output_dir}")

    # Load trading dates if not provided
    if trading_dates is None:
        if start_date is None or end_date is None:
            raise ValueError(
                "start_date and end_date are required when trading_dates is None. "
                "Pass both start_date and end_date, or provide trading_dates directly."
            )
        # Forward paths so the calendar lookup honors workspace-local overrides.
        trading_dates = _load_trading_dates(
            market, instrument, start_date, end_date,
            market_data_dir=paths.market_data_dir,
        )

    logger.info(f"[INDICATORS] Processing {len(trading_dates)} trading dates")

    # Import and create processor
    from .engine.processor import IndicatorProcessor

    # Derive backtest_start_year from start_date if available
    backtest_start_year = None
    if start_date is not None:
        backtest_start_year = int(start_date[:4])

    processor = IndicatorProcessor(
        ctx=ctx,
        trading_date_list=trading_dates,
        indicator_list=indicator_list,
        output_dir=output_dir,
        regime_params=regime_params,
        backtest_start_year=backtest_start_year,
        paths=paths,
    )

    # Process all contracts
    result = processor.process_all_contracts(use_multiprocessing=use_parallel)

    if isinstance(result, pd.DataFrame) and not result.empty:
        logger.info(f"[INDICATORS] Complete | rows={len(result)}")
    else:
        logger.warning("[INDICATORS] Complete | no data returned")

    return result


def compute_indicators_from_frame(
    ohlcv: pd.DataFrame,
    indicator_list: Dict[str, Dict[str, Any]],
    ctx: TradingContext,
    *,
    regime_params: Optional[Dict[str, Any]] = None,
) -> pd.DataFrame:
    """Compute indicators from a caller-provided continuous OHLCV frame.

    Generic injectable-frame entry point for callers that already have a
    continuous OHLCV series in memory — block-bootstrap resamples, synthetic
    data, or any other caller-assembled frame — and want the SAME per-bar
    indicator computations :func:`run_indicator_calculation` applies to its
    stitched main-contract series, without touching contract files, the roll
    table, or any disk I/O. This is the identity contract: feed this function
    the exact continuous OHLCV columns the standard pipeline would have
    produced for a given (market, instrument, date range), and the shared
    indicator columns match — see "Semantics reproduced" below for exactly
    which bars that identity holds on.

    How the standard pipeline actually computes indicators (context for the
    semantics boundary below): ``IndicatorProcessor`` computes each contract's
    indicators over THAT CONTRACT's own full per-contract OHLCV history
    (which starts however long before the contract becomes the front/main
    contract — not just the days it is main), then assembles the saved
    continuous ``strategy_indicators.csv`` by selecting, for each trading
    date, the row from whichever contract was main that date. Indicator
    computation itself is per-contract and roll-BLIND (a contract's own
    rolling window has no concept of "the previous main contract"); only the
    row SELECTION is roll-aware.

    This function instead runs the SAME per-bar computation
    (``echolon.indicators.engine.processor._compute_indicators_for_contract``)
    treating the entire input frame as one continuous series in a single pass
    — i.e. genuine "post-stitch continuous-series" semantics, exactly what a
    caller holding only a continuous OHLCV frame (no contract lineage) can
    mean by "compute this indicator on this series".

    Semantics reproduced vs. NOT reproduced:

    - **Reproduced (identical, modulo the float note below):** any bar whose
      indicator lookback window falls entirely within a single contiguous
      "same main contract" stretch of the caller's date range. There, the
      standard pipeline's per-contract window and this function's continuous
      window are drawn from the exact same trailing prices, so the two
      computations agree.
    - **NOT reproduced (diverges near a main-contract change):** for a bar
      within ``lookback - 1`` bars of the date the main contract changed, the
      standard pipeline's per-contract computation used the NEW main
      contract's OWN pre-roll price history (its quotes from before it
      became main — a different, real price series, e.g. a different point
      on the futures curve). The continuous OHLCV frame instead carries the
      OLD main contract's prices for those pre-roll dates. A single-pass
      continuous computation over the frame therefore uses different
      trailing values than the standard pipeline did for those few bars.
      This is not a bug in either computation — the caller-provided series
      simply lacks the per-contract lineage needed to reproduce the pre-roll
      tail. If your series has no contract-roll structure at all (the usual
      case for block-bootstrap / synthetic data), this boundary never
      applies.
    - **Not computable at all — HARD FAILS (IND-009):** ``curve_carry``-kind
      indicators (``carry_front_back``, ``carry_z_3m``, ...). These are built
      once from the full multi-contract forward curve, not from any single
      price series; a continuous frame cannot supply the other contracts'
      quotes. Drop them from ``indicator_list``, or compute them separately
      via
      ``echolon.indicators.calculators.interday.carry.series_builder.build_carry_indicator_frame``
      and merge the columns in yourself.
    - **Out of scope — caller's responsibility:** registered regime-classifier
      columns (e.g. a ``market_regime`` name) ARE computed when declared —
      trivially, via the same dispatch ``_compute_indicators_for_contract``
      already uses — but this function does nothing extra to make them
      meaningful on a synthetic frame; the classifier still needs
      ``regime_params`` and still classifies whatever series it is given. If
      your use case needs those columns held CONSTANT across resamples (the
      typical block-bootstrap ask), recompute them separately on your real
      data and carry them through rather than declaring them here.

    Floating-point note: some TA-Lib wrappers (e.g. SMA) use an incremental
    sliding-window sum rather than re-summing each window from scratch, so a
    bar's value can differ at the machine-epsilon level (~1e-13 relative)
    depending on how much history precedes it, even when the trailing window
    values are bit-identical. Treat "reproduced" above as exact modulo
    floating-point non-associativity, not necessarily bit-for-bit.

    Args:
        ohlcv: Continuous OHLCV DataFrame — the same shape/columns
            :func:`run_indicator_calculation` would have produced for this
            ctx/date range (at minimum ``open``/``high``/``low``/``close``
            and a ``date`` or ``datetime`` column). Not mutated — a
            normalized copy is used internally.
        indicator_list: Flat-dict indicator specification, same schema as
            :func:`run_indicator_calculation` (validated the same way).
        ctx: TradingContext — used for frequency routing and the same
            auto-param inference (``bars_per_day``, frequency-scaled
            defaults) :class:`IndicatorProcessor` uses.
        regime_params: Regime-classifier params, required when
            ``indicator_list`` contains a registered classifier name on an
            interday ctx (same contract as ``run_indicator_calculation``).
            On an intraday ctx this is forced to ``None`` regardless of what
            the caller passes — identical to ``IndicatorProcessor.__init__``,
            which only keeps regime_params for interday frequency (intraday
            uses session_phase + volatility_state instead).

    Returns:
        A copy of ``ohlcv`` (normalized: missing open/high/low filled from
        close, date/datetime converted, sorted) with one column appended per
        computed indicator/param-combo, using the same column-naming rules
        as the standard pipeline. No contract-lineage metadata (``contract``,
        ``contract_expiry``, ``trading_date``) is added — a caller-provided
        frame carries no contract identity.

    Raises:
        pydantic.ValidationError: ``indicator_list`` fails the
            :class:`IndicatorList` schema.
        EchelonError (IND-009): ``indicator_list`` declares a ``curve_carry``
            indicator (see above).
    """
    IndicatorList.model_validate(indicator_list)

    from .engine.processor import (
        _compute_indicators_for_contract,
        _prepare_ohlcv_frame,
        _split_curve_carry,
    )

    curve_carry, per_contract = _split_curve_carry(indicator_list)
    if curve_carry:
        raise_error("IND-009", indicators=sorted(curve_carry))

    # Regime params: caller-provided or None — same routing as
    # IndicatorProcessor.__init__ (which keeps them only when frequency ==
    # "day"). Intraday uses session_phase + volatility_state; regime_params
    # unused — forwarding the caller's dict here would make the frame path
    # compute something the standard pipeline never does, breaking the
    # "SAME computations" identity contract.
    if ctx.is_intraday:
        regime_params = None

    df = _prepare_ohlcv_frame(ohlcv)

    default_params = ctx.get_indicator_params()
    indicator_results = _compute_indicators_for_contract(
        df,
        indicator_list=per_contract,
        ctx=ctx,
        regime_params=regime_params,
        default_params=default_params,
        session_availability=None,
    )

    indicator_dfs = []
    for indicator_name, values in indicator_results.items():
        if len(values) == len(df):
            indicator_dfs.append(pd.DataFrame({indicator_name: values}, index=df.index))
        else:
            logger.warning(
                f"[INDICATORS] Length mismatch | indicator={indicator_name}, "
                f"expected={len(df)}, got={len(values)}"
            )

    return pd.concat([df] + indicator_dfs, axis=1)


def _load_trading_dates(
    market: str,
    instrument: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    *,
    market_data_dir: Path,
) -> List[datetime]:
    """Load trading dates from calendar."""
    from echolon.data.loaders.calendar_loader import get_trading_dates

    dates = get_trading_dates(
        market=market,
        asset=instrument,
        start_date=start_date,
        end_date=end_date,
        market_data_dir=market_data_dir,
    )

    return dates
