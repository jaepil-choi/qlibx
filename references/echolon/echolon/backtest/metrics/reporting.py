"""
Reporting Utilities
===================

Utilities for saving and visualizing backtest results.

Functions:
- save_results_to_json: Save metrics and params to JSON
- save_trade_log: Save trades to CSV
- save_equity_curve: Save equity curve to CSV
- save_optuna_study_results: Save Optuna study results
- plot_annual_returns: Plot annual returns bar chart
- convert_to_serializable: Convert numpy/pandas types for JSON
"""

import pandas as pd
import numpy as np
from datetime import datetime
import logging
from typing import Dict, Any
import json
import os
import matplotlib.pyplot as plt

from echolon.backtest.schemas import validate_trades_dict_list

logger = logging.getLogger(__name__)

# --- Plotting Functions --- 

def plot_annual_returns(annual_returns: Dict[int, float], save_path: str = None):
    """
    Create a bar plot of annual returns.
    Note: Consider using backtrader's built-in plotting capabilities for more comprehensive charts.
    """
    if not annual_returns:
        logger.warning("[REPORTING] Plot skipped | reason=No annual returns data")
        return
        
    try:
        plt.figure(figsize=(12, 6))
        
        years = sorted(annual_returns.keys())
        returns = [annual_returns[y] for y in years]
        
        bars = plt.bar(years, returns)
        
        # Color bars based on positive/negative returns
        for i, return_value in enumerate(returns):
            bars[i].set_color('green' if return_value >= 0 else 'red')
        
        # Add value labels on bars
        for bar in bars:
            height = bar.get_height()
            plt.text(bar.get_x() + bar.get_width()/2., height,
                    f'{height:.1f}%',
                    ha='center', va='bottom' if height >= 0 else 'top')
        
        plt.title('Annual Returns (%)')
        plt.xlabel('Year')
        plt.ylabel('Return (%)')
        plt.grid(True, alpha=0.3)
        plt.xticks(years, rotation=45)
        plt.tight_layout()
        
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
            if logger.isEnabledFor(logging.INFO):
                logger.info(f"[REPORTING] Plot saved | path={save_path}")
        else:
            plt.show()
        plt.close()

    except ImportError:
        logger.error("[REPORTING] Plot failed | reason=Matplotlib not found, install=pip install matplotlib")
    except Exception as e:
        logger.error(f"[REPORTING] Plot generation failed | error={e}")

# --- JSON Saving Functions ---

def convert_to_serializable(obj: Any) -> Any:
    """
    Convert objects to JSON-serializable types.

    Handles numpy types, pandas types, datetime, and nested structures.

    Parameters
    ----------
    obj : Any
        Object to convert

    Returns
    -------
    Any
        JSON-serializable version of the object
    """
    if isinstance(obj, dict):
        return {str(k): convert_to_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_to_serializable(elem) for elem in obj]
    elif isinstance(obj, np.integer):
        return int(obj)
    elif isinstance(obj, np.floating):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, (datetime, pd.Timestamp)):
        return obj.isoformat()
    elif isinstance(obj, pd.Timedelta):
        return obj.total_seconds()
    elif isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    elif pd.isna(obj):
        return None
    return obj


def save_results_to_json(metrics: Dict, strategy_params: Dict, filepath: str):
    """
    Save backtest metrics and strategy parameters to JSON.
    Simplified version focusing on essential data.
    """
    try:
        if logger.isEnabledFor(logging.INFO):
            logger.info(f"[REPORTING] Saving results | path={filepath}")

        results_data = {
            "run_timestamp": datetime.now().isoformat(),
            "performance_metrics": convert_to_serializable({
            k: v for k, v in metrics.items() if k != 'trades'
            }),
            "strategy_parameters": convert_to_serializable({
                k: v for k, v in strategy_params.items()
                if k not in ['historical_closes_dict', 'trading_calendar', 'trades']
            }),
            "trades": convert_to_serializable(metrics.get('trades', []))
        }

        os.makedirs(os.path.dirname(filepath), exist_ok=True)

        with open(filepath, 'w') as f:
            json.dump(results_data, f, indent=4, default=str)

        if logger.isEnabledFor(logging.INFO):
            logger.info(f"[REPORTING] Results saved | path={filepath}")

    except Exception as e:
        logger.exception(f"[REPORTING] JSON save failed | path={filepath}, error={e}")

def save_optuna_study_results(study, output_dir: str, study_name: str = None):
    """
    Save Optuna study results using built-in functionality.

    Parameters
    ----------
    study : optuna.Study
        Completed Optuna study
    output_dir : str
        Directory to save results
    study_name : str, optional
        Name prefix for output files. Uses study.study_name if None.
    """
    try:
        os.makedirs(output_dir, exist_ok=True)
        study_name = study_name or study.study_name

        # Check if this is a multi-objective study
        is_multi_objective = hasattr(study, 'directions') and len(study.directions) > 1

        if is_multi_objective:
            # Multi-objective study - save info about Pareto frontier
            best_trial_data = {
                "run_timestamp": datetime.now().isoformat(),
                "study_name": study.study_name,
                "study_type": "multi_objective",
                "n_pareto_solutions": len(study.best_trials),
                "optimization_directions": [str(d) for d in study.directions],
                "note": "Multi-objective study - best_params.json contains selected solution from Pareto frontier"
            }
        else:
            # Single-objective study - save best trial info
            best_trial_data = {
                "run_timestamp": datetime.now().isoformat(),
                "study_name": study.study_name,
                "study_type": "single_objective",
                "best_trial_number": study.best_trial.number,
                "best_value": study.best_value,
                "best_params": study.best_params,
                "datetime_start": study.best_trial.datetime_start.isoformat() if study.best_trial.datetime_start else None,
                "datetime_complete": study.best_trial.datetime_complete.isoformat() if study.best_trial.datetime_complete else None,
            }

        study_info_filepath = os.path.join(output_dir, "optuna_study_info.json")

        with open(study_info_filepath, 'w') as f:
            json.dump(best_trial_data, f, indent=4)
        if logger.isEnabledFor(logging.INFO):
            logger.info(f"[REPORTING] Optuna info saved | path={study_info_filepath}")

        # Save all trials as CSV using pandas
        trials_df = study.trials_dataframe()

        # Clean datetime columns
        for col in ['datetime_start', 'datetime_complete']:
            if col in trials_df.columns:
                trials_df[col] = trials_df[col].apply(
                    lambda x: x.isoformat() if pd.notna(x) else ''
                )

        all_trials_filepath = os.path.join(output_dir, f"{study_name}_all_trials.csv")
        trials_df.to_csv(all_trials_filepath, index=False)
        if logger.isEnabledFor(logging.INFO):
            logger.info(f"[REPORTING] All trials saved | path={all_trials_filepath}")

    except Exception as e:
        logger.exception(f"[REPORTING] Optuna save failed | error={e}") 

def save_trade_log(trades_data, filepath: str):
    """Save trade log using pandas built-in functionality with schema validation."""
    # Handle different input types to get list of dicts
    if isinstance(trades_data, dict):
        # If it's a dict with 'trades' key (from analyzer)
        if 'trades' in trades_data and isinstance(trades_data['trades'], list):
            trades_list = trades_data['trades']
        else:
            logger.error(f"[REPORTING] Invalid trades data | keys={trades_data.keys()}, reason=Missing 'trades' list")
            return
    elif isinstance(trades_data, list):
        trades_list = trades_data
    elif isinstance(trades_data, pd.DataFrame):
        trades_list = trades_data.to_dict('records')
    else:
        logger.error(f"[REPORTING] Invalid trades data | type={type(trades_data)}")
        return

    if not trades_list:
        logger.warning("[REPORTING] Trade log skipped | reason=No trade data")
        return

    # Validate against schema before saving (fail-fast)
    validated_trades = validate_trades_dict_list(trades_list)
    logger.info(f"[REPORTING] Trade log validated | trades={len(validated_trades)}")

    # Convert to DataFrame and save
    df = pd.DataFrame(validated_trades)
    df.to_csv(filepath, index=False)
    logger.info(f"[REPORTING] Trade log saved | path={filepath}")

    # Debug: Print first few rows to verify structure
    logger.debug(f"Saved CSV structure - Shape: {df.shape}")
    logger.debug(f"Columns: {list(df.columns)}")
    if len(df) > 0:
        logger.debug(f"First trade: {df.iloc[0].to_dict()}")

def save_equity_curve(equity_curve_data, filepath: str):
    """Save bar-level equity curve to CSV for Performance Analyst.

    Args:
        equity_curve_data: List of dicts with 'date' and 'equity' keys
        filepath: Path to save the equity curve CSV
    """
    try:
        if not equity_curve_data:
            logger.warning("[REPORTING] Equity curve save skipped | reason=No equity curve data")
            return

        # Convert to DataFrame
        df = pd.DataFrame(equity_curve_data)

        if df.empty:
            logger.warning("[REPORTING] Equity curve save skipped | reason=Empty DataFrame")
            return

        # Save to CSV
        df.to_csv(filepath, index=False)
        logger.info(f"[REPORTING] Equity curve saved | path={filepath}, bars={len(df)}")

        # Debug: Print summary
        logger.debug(f"Equity curve shape: {df.shape}")
        logger.debug(f"Columns: {list(df.columns)}")
        if len(df) > 0:
            logger.debug(f"First equity point: {df.iloc[0].to_dict()}")
            logger.debug(f"Last equity point: {df.iloc[-1].to_dict()}")

    except Exception as e:
        logger.error(f"[REPORTING] Equity curve save failed | path={filepath}, error={e}")
        import traceback
        logger.error(f"[REPORTING] Traceback | {traceback.format_exc()}")

def save_trade_log_with_debug(strategy, trades_data, filepath: str):
    """Save trade log and debug information if available."""
    # Save the regular trade log
    save_trade_log(trades_data, filepath)
    
    # Try to save debug information if the enhanced analyzer is available
    try:
        if hasattr(strategy, 'analyzers'):
            # Look for our TradeList analyzer
            tradelist_analyzer = None
            for analyzer_name in strategy.analyzers.getnames():
                analyzer = strategy.analyzers.getbyname(analyzer_name)
                if hasattr(analyzer, 'save_debug_info'):  # Our enhanced TradeList analyzer
                    tradelist_analyzer = analyzer
                    break
            
            if tradelist_analyzer:
                tradelist_analyzer.save_debug_info(filepath)
                if logger.isEnabledFor(logging.INFO):
                    logger.info("[REPORTING] Debug info saved")
            else:
                logger.debug("No enhanced TradeList analyzer found for debug information")
    except Exception as e:
        logger.warning(f"[REPORTING] Debug save failed | error={e}")



