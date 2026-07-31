"""
Calculate MFE/MAE (Maximum Favorable/Adverse Excursion) from Historical Price Data

This module retrospectively calculates MFE/MAE for completed trades using
bar-level price data (high/low) from contract files. This enables exit quality
analysis without requiring backtest engine modifications.

MFE (Maximum Favorable Excursion): The best profit point reached during a trade
MAE (Maximum Adverse Excursion): The worst loss point reached during a trade

These metrics are critical for analyzing:
- Exit quality (profit capture rate)
- Entry timing (drawdown before profit)
- Stop loss optimization
- Exit strategy effectiveness

Multi-Market/Frequency Support:
- Uses standard data loader path resolution (MARKET_DATA_DIR)
- Works with any market (SHFE, CRYPTO, CME) and frequency (daily, intraday)
- Contract data loaded from sort_by_contract directory
"""

import pandas as pd
import os
import logging
from pathlib import Path
from typing import Dict, List, Optional

from echolon.config.markets.core.context import TradingContext

logger = logging.getLogger(__name__)


def get_contract_data_dir(
    market: str,
    instrument: str,
    market_data_dir: Optional[Path] = None,
) -> str:
    """
    Get the contract data directory path for a given market/instrument.

    Uses standard path structure: {market_data_dir}/{market}/{instrument}/sort_by_contract/

    Args:
        market: Market code (e.g., 'SHFE', 'CRYPTO', 'CME')
        instrument: Instrument name (e.g., 'aluminum', 'copper', 'bitcoin')
        market_data_dir: Optional injected market-data base directory.
            Falls back to ``PathsConfig.market_data_dir`` derived from
            ``ECHOLON_PROJECT_ROOT`` when omitted.

    Returns:
        Path to the sort_by_contract directory
    """
    if market_data_dir is None:
        from echolon.errors import raise_error
        raise_error(
            "CFG-003",
            function="get_contract_data_dir",
            param="market_data_dir=",
            paths_field="market_data_dir",
        )
    return os.path.join(str(market_data_dir), market.upper(), instrument, "sort_by_contract")


def get_intraday_data_path(
    instrument: str,
    indicator_dir: Optional[Path] = None,
) -> str:
    """
    Get the path to intraday main contract data (strategy_indicators.csv).

    For intraday trading, positions are flattened daily so no contract roll risk.
    We use the continuous main contract data for MFE/MAE calculation.

    Args:
        instrument: Instrument name (e.g., 'aluminum', 'copper')
        indicator_dir: Optional injected backtest indicator directory.
            Falls back to ``PathsConfig.indicators_backtest_dir`` derived from
            ``ECHOLON_PROJECT_ROOT`` when omitted.

    Returns:
        Path to strategy_indicators.csv
    """
    if indicator_dir is None:
        from echolon.errors import raise_error
        raise_error(
            "CFG-003",
            function="get_intraday_data_path",
            param="indicator_dir=",
            paths_field="indicators_backtest_dir",
        )
    return os.path.join(str(indicator_dir), instrument, "strategy_indicators.csv")


def calculate_mfe_mae_for_trade(
    entry_date: str,
    exit_date: str,
    entry_price: float,
    direction: str,
    contract: str,
    contract_data_dir: str,
    entry_datetime: Optional[str] = None,
    exit_datetime: Optional[str] = None
) -> Dict[str, float]:
    """
    Calculate MFE and MAE for a single trade using historical price data.

    Supports both daily and intraday data:
    - Daily: Uses 'date' column, filters by date only
    - Intraday: Uses 'datetime' column, filters by exact timestamp

    Args:
        entry_date: Trade entry date (YYYY-MM-DD)
        exit_date: Trade exit date (YYYY-MM-DD)
        entry_price: Entry price
        direction: 'long' or 'short'
        contract: Contract symbol (e.g., 'al1806')
        contract_data_dir: Path to directory containing contract CSV files
        entry_datetime: Optional exact entry timestamp for intraday (YYYY-MM-DD HH:MM:SS)
        exit_datetime: Optional exact exit timestamp for intraday (YYYY-MM-DD HH:MM:SS)

    Returns:
        Dictionary with mfe, mae, mfe_pct, mae_pct
    """
    # Default return for errors
    default_result = {
        'mfe': 0.0,
        'mae': 0.0,
        'mfe_pct': 0.0,
        'mae_pct': 0.0
    }

    # Load contract price data
    contract_file = os.path.join(contract_data_dir, f"{contract}.csv")

    if not os.path.exists(contract_file):
        logger.warning(f"Contract file not found: {contract_file}")
        return default_result

    # Read contract data
    contract_df = pd.read_csv(contract_file)

    # Detect data frequency and parse timestamps
    # Priority: 'datetime' column (intraday) > 'date' column (daily)
    if 'datetime' in contract_df.columns:
        # Intraday data - use datetime column
        contract_df['datetime'] = pd.to_datetime(contract_df['datetime'])
        timestamp_col = 'datetime'

        # Use exact timestamps if provided, otherwise fall back to dates
        if entry_datetime and exit_datetime:
            entry_dt = pd.to_datetime(entry_datetime)
            exit_dt = pd.to_datetime(exit_datetime)
        else:
            # Fallback: use date boundaries (entire day)
            entry_dt = pd.to_datetime(entry_date)
            exit_dt = pd.to_datetime(exit_date) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
    else:
        # Daily data - use date column
        # Handle multiple date formats: YYYYMMDD (int) or YYYY-MM-DD (string)
        if contract_df['date'].dtype in ['int64', 'float64']:
            contract_df['date'] = pd.to_datetime(contract_df['date'], format='%Y%m%d')
        else:
            contract_df['date'] = pd.to_datetime(contract_df['date'])
        timestamp_col = 'date'
        entry_dt = pd.to_datetime(entry_date)
        exit_dt = pd.to_datetime(exit_date)

    # Filter to trade period (inclusive)
    trade_period_df = contract_df[
        (contract_df[timestamp_col] >= entry_dt) &
        (contract_df[timestamp_col] <= exit_dt)
    ]

    if trade_period_df.empty:
        logger.warning(f"No price data found for {contract} between {entry_date} and {exit_date}")
        return default_result

    # Calculate MFE/MAE based on direction
    if direction == 'long':
        # For long positions:
        # MFE = highest high during trade - entry price (max profit potential)
        # MAE = lowest low during trade - entry price (max drawdown)
        highest_high = trade_period_df['high'].max()
        lowest_low = trade_period_df['low'].min()

        mfe = highest_high - entry_price
        mae = lowest_low - entry_price

    elif direction == 'short':
        # For short positions:
        # MFE = entry price - lowest low (max profit potential)
        # MAE = entry price - highest high (max drawdown)
        highest_high = trade_period_df['high'].max()
        lowest_low = trade_period_df['low'].min()

        mfe = entry_price - lowest_low
        mae = entry_price - highest_high

    else:
        logger.error(f"Unknown direction: {direction}")
        return {
            'mfe': 0.0,
            'mae': 0.0,
            'mfe_pct': 0.0,
            'mae_pct': 0.0
        }

    # Calculate percentages (entry_price check to avoid division by zero)
    if entry_price == 0:
        return default_result
    mfe_pct = (mfe / entry_price) * 100
    mae_pct = (mae / entry_price) * 100

    return {
        'mfe': mfe,
        'mae': mae,
        'mfe_pct': mfe_pct,
        'mae_pct': mae_pct
    }


def calculate_mfe_mae_intraday(
    entry_datetime: str,
    exit_datetime: str,
    entry_price: float,
    direction: str,
    intraday_data_path: str,
    _cached_df: Dict[str, pd.DataFrame] = {}
) -> Dict[str, float]:
    """
    Calculate MFE and MAE for intraday trades using main contract data.

    For intraday trading where positions are flattened daily, there's no
    contract roll risk. We use the continuous main contract data directly.

    Args:
        entry_datetime: Trade entry timestamp (YYYY-MM-DD HH:MM:SS)
        exit_datetime: Trade exit timestamp (YYYY-MM-DD HH:MM:SS)
        entry_price: Entry price
        direction: 'long' or 'short'
        intraday_data_path: Path to strategy_indicators.csv
        _cached_df: Cache for loaded DataFrame (avoids reloading for each trade)

    Returns:
        Dictionary with mfe, mae, mfe_pct, mae_pct
    """
    default_result = {
        'mfe': 0.0,
        'mae': 0.0,
        'mfe_pct': 0.0,
        'mae_pct': 0.0
    }

    # Load data with caching
    if intraday_data_path not in _cached_df:
        if not os.path.exists(intraday_data_path):
            logger.warning(f"Intraday data file not found: {intraday_data_path}")
            return default_result

        df = pd.read_csv(intraday_data_path)

        # Parse datetime column
        if 'datetime' in df.columns:
            df['datetime'] = pd.to_datetime(df['datetime'])
            df = df.set_index('datetime')
        elif 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'])
            df = df.set_index('date')
        else:
            logger.warning(f"No datetime/date column in {intraday_data_path}")
            return default_result

        _cached_df[intraday_data_path] = df

    df = _cached_df[intraday_data_path]

    # Parse entry/exit timestamps
    entry_dt = pd.to_datetime(entry_datetime)
    exit_dt = pd.to_datetime(exit_datetime)

    # Filter to trade period
    trade_period_df = df[(df.index >= entry_dt) & (df.index <= exit_dt)]

    if trade_period_df.empty:
        logger.warning(f"No price data found between {entry_datetime} and {exit_datetime}")
        return default_result

    # Calculate MFE/MAE based on direction
    highest_high = trade_period_df['high'].max()
    lowest_low = trade_period_df['low'].min()

    if direction == 'long':
        mfe = highest_high - entry_price
        mae = lowest_low - entry_price
    elif direction == 'short':
        mfe = entry_price - lowest_low
        mae = entry_price - highest_high
    else:
        logger.error(f"Unknown direction: {direction}")
        return default_result

    # Calculate percentages
    if entry_price == 0:
        return default_result

    mfe_pct = (mfe / entry_price) * 100
    mae_pct = (mae / entry_price) * 100

    return {
        'mfe': mfe,
        'mae': mae,
        'mfe_pct': mfe_pct,
        'mae_pct': mae_pct
    }


def enrich_trades_with_mfe_mae(
    trades_list: List[Dict],
    ctx: TradingContext,
    *,
    paths: "PathsConfig",  # type: ignore[name-defined]
) -> List[Dict]:
    """
    Enrich trades list with MFE/MAE metrics by calculating from contract price data.

    This function adds MFE/MAE columns directly to the trades list, allowing
    integration into the main backtest workflow for single-file output.

    Supports both daily and intraday trades:
    - Daily: Uses entry_date/exit_date fields
    - Intraday: Uses entry_datetime/exit_datetime if available

    Args:
        trades_list: List of trade dictionaries (from backtest results)
        ctx: TradingContext (single source of truth for market/instrument/frequency)

    Returns:
        List of trade dictionaries enriched with MFE/MAE metrics
    """
    if not trades_list:
        logger.warning("No trades to enrich with MFE/MAE")
        return trades_list

    # Get contract multiplier from context (instrument-specific)
    contract_multiplier = ctx.multiplier

    # Get market/instrument/frequency from ctx
    market = ctx.market_code
    instrument = ctx.instrument_name
    is_intraday = ctx.frequency == 'intraday'

    if is_intraday:
        # Intraday: use continuous main contract data from strategy_indicators.csv
        intraday_data_path = get_intraday_data_path(
            instrument, indicator_dir=paths.indicators_backtest_dir,
        )
        if not os.path.exists(intraday_data_path):
            logger.warning(f"Intraday data file not found: {intraday_data_path}. "
                          "MFE/MAE enrichment skipped.")
            return _add_zero_mfe_mae_columns(trades_list)
        logger.info(f"Enriching {len(trades_list)} intraday trades with MFE/MAE | "
                    f"market={market}, instrument={instrument}")
    else:
        # Interday: use contract-specific data from sort_by_contract/
        contract_data_dir = get_contract_data_dir(
            market, instrument, market_data_dir=paths.market_data_dir,
        )
        if not os.path.exists(contract_data_dir):
            logger.warning(f"Contract data directory not found: {contract_data_dir}. "
                          "MFE/MAE enrichment skipped.")
            return _add_zero_mfe_mae_columns(trades_list)
        logger.info(f"Enriching {len(trades_list)} interday trades with MFE/MAE | "
                    f"market={market}, instrument={instrument}")

    enriched_trades = []

    for trade in trades_list:
        entry_datetime = trade.get('entry_datetime')
        exit_datetime = trade.get('exit_datetime')

        if is_intraday:
            # Intraday: use continuous main contract data
            # Get entry_time which contains the full datetime
            entry_time = trade.get('entry_time')
            if entry_time and hasattr(entry_time, 'isoformat'):
                entry_dt_str = entry_time.isoformat()
            elif entry_datetime:
                entry_dt_str = str(entry_datetime)
            else:
                entry_dt_str = trade['entry_date']

            # For exit datetime, use exit_time (full datetime) if available
            exit_time = trade.get('exit_time')
            if exit_time and hasattr(exit_time, 'isoformat'):
                exit_dt_str = exit_time.isoformat()
            elif exit_datetime:
                exit_dt_str = str(exit_datetime)
            else:
                # Fallback: use exit_date as end-of-day
                exit_dt_str = trade['exit_date'] + ' 23:59:59'

            mfe_mae = calculate_mfe_mae_intraday(
                entry_datetime=entry_dt_str,
                exit_datetime=exit_dt_str,
                entry_price=trade['entry_price'],
                direction=trade['direction'],
                intraday_data_path=intraday_data_path
            )
        else:
            # Interday: use contract-specific data
            mfe_mae = calculate_mfe_mae_for_trade(
                entry_date=trade['entry_date'],
                exit_date=trade['exit_date'],
                entry_price=trade['entry_price'],
                direction=trade['direction'],
                contract=trade['entry_contract'],
                contract_data_dir=contract_data_dir,
                entry_datetime=entry_datetime,
                exit_datetime=exit_datetime
            )

        # Calculate additional metrics
        actual_profit_points = trade['exit_price'] - trade['entry_price']
        if trade['direction'] == 'short':
            actual_profit_points = -actual_profit_points

        # Profit capture rate: what % of MFE did we capture?
        if mfe_mae['mfe'] > 0:
            profit_capture_rate = (actual_profit_points / mfe_mae['mfe']) * 100
        else:
            profit_capture_rate = 0.0

        # MFE/MAE in currency (accounting for contract size)
        mfe_currency = mfe_mae['mfe'] * trade['size'] * contract_multiplier
        mae_currency = mfe_mae['mae'] * trade['size'] * contract_multiplier

        # Entry quality score: ratio of potential profit to drawdown
        # Higher is better - good entries have high MFE and low MAE
        mae_value = mfe_mae['mae']
        if mae_value < 0:
            entry_quality_score = mfe_mae['mfe'] / abs(mae_value)
        else:
            # No drawdown - excellent entry
            entry_quality_score = float('inf') if mfe_mae['mfe'] > 0 else 0.0

        # Create enriched trade dictionary with original data + MFE/MAE metrics
        enriched_trade = trade.copy()
        enriched_trade.update({
            'mfe_points': mfe_mae['mfe'],
            'mae_points': mfe_mae['mae'],
            'mfe_pct': mfe_mae['mfe_pct'],
            'mae_pct': mfe_mae['mae_pct'],
            'mfe_currency': mfe_currency,
            'mae_currency': mae_currency,
            'profit_capture_rate': profit_capture_rate,
            'profit_left_on_table': mfe_mae['mfe'] - actual_profit_points,
            'entry_drawdown_points': abs(mae_value) if mae_value < 0 else 0.0,
            'entry_quality_score': entry_quality_score,
        })

        enriched_trades.append(enriched_trade)

    logger.info(f"Successfully enriched {len(enriched_trades)} trades with MFE/MAE metrics")

    return enriched_trades


def _add_zero_mfe_mae_columns(trades_list: List[Dict]) -> List[Dict]:
    """
    Add zero-valued MFE/MAE columns to trades when calculation isn't possible.

    This ensures downstream analyzers receive the expected columns even when
    contract data is unavailable.

    Args:
        trades_list: List of trade dictionaries

    Returns:
        List of trades with zero MFE/MAE columns added
    """
    result = []
    for trade in trades_list:
        enriched = trade.copy()
        enriched.update({
            'mfe_points': 0.0,
            'mae_points': 0.0,
            'mfe_pct': 0.0,
            'mae_pct': 0.0,
            'mfe_currency': 0.0,
            'mae_currency': 0.0,
            'profit_capture_rate': 0.0,
            'profit_left_on_table': 0.0,
            'entry_drawdown_points': 0.0,
            'entry_quality_score': 0.0,
        })
        result.append(enriched)
    return result


def calculate_mfe_mae_for_all_trades(
    trades_csv_path: str,
    ctx: TradingContext,
    output_csv_path: Optional[str] = None
) -> pd.DataFrame:
    """
    Calculate MFE/MAE for all trades from a CSV file.

    Standalone function for analyzing existing backtest results.
    For integration into backtest workflow, use enrich_trades_with_mfe_mae instead.

    Args:
        trades_csv_path: Path to backtest_trades.csv
        ctx: TradingContext (single source of truth for market/instrument config)
        output_csv_path: Optional path to save enriched results CSV

    Returns:
        DataFrame with all trades enriched with MFE/MAE metrics
    """
    logger.info(f"Loading trades from: {trades_csv_path}")

    # Load backtest trades
    trades_df = pd.read_csv(trades_csv_path)
    logger.info(f"Processing {len(trades_df)} trades | "
                f"market={ctx.market_code}, instrument={ctx.instrument_name}")

    # Convert to list of dicts for enrichment
    trades_list = trades_df.to_dict('records')

    # Enrich with MFE/MAE using ctx (contract_multiplier from ctx.multiplier)
    enriched_trades = enrich_trades_with_mfe_mae(
        trades_list=trades_list,
        ctx=ctx
    )

    # Convert back to DataFrame
    results_df = pd.DataFrame(enriched_trades)

    # Save to CSV if path provided
    if output_csv_path:
        os.makedirs(os.path.dirname(output_csv_path), exist_ok=True)
        results_df.to_csv(output_csv_path, index=False)
        logger.info(f"MFE/MAE analysis saved to: {output_csv_path}")

    # Log summary statistics
    if len(results_df) > 0:
        logger.info(f"MFE/MAE Summary | "
                   f"avg_mfe={results_df['mfe_points'].mean():.2f}, "
                   f"avg_mae={results_df['mae_points'].mean():.2f}, "
                   f"avg_capture_rate={results_df['profit_capture_rate'].mean():.1f}%")

    return results_df


def main():
    """Main function to run MFE/MAE calculation on backtest results."""
    import argparse
    from echolon._internal.structured_logging import install_structured_logging
    install_structured_logging()
    from echolon.config.paths_config import PathsConfig
    from echolon.config.markets.factory import MarketFactory

    paths = PathsConfig.from_env()

    parser = argparse.ArgumentParser(description='Run MFE/MAE analysis')
    parser.add_argument('--market', required=True, help='Market code (e.g., SHFE)')
    parser.add_argument('--instrument', required=True, help='Instrument code (e.g., al)')
    parser.add_argument('--frequency', default='interday', help='interday or intraday')
    parser.add_argument('--bar-size', default='1d', help='Bar size (1m/5m/15m/30m/1h/1d)')
    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Build TradingContext from explicit CLI args — host apps own session parsing.
    ctx = MarketFactory.create(
        market=args.market,
        instrument=args.instrument,
        frequency=args.frequency,
        bar_size=args.bar_size,
    )

    # Define paths using standard workspace structure
    trades_csv = paths.backtest_results_dir / "backtest_trades.csv"
    output_csv = paths.backtest_results_dir / "trade_mfe_mae_analysis.csv"

    # Run analysis
    results_df = calculate_mfe_mae_for_all_trades(
        trades_csv_path=str(trades_csv),
        ctx=ctx,
        output_csv_path=str(output_csv)
    )

    logger.info("MFE/MAE analysis complete!")

    return results_df


if __name__ == "__main__":
    main()
