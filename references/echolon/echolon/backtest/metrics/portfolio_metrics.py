"""
Portfolio Metrics
=================

Compute portfolio-level performance metrics from per-slot backtest results.

Functions:
- compute_portfolio_metrics(): Sharpe, DD, Calmar, per-slot contribution
- compute_correlation_matrix(): Pairwise daily return correlation
- validate_margin(): Post-hoc margin check from trade logs
"""

import logging
import math
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def compute_portfolio_metrics(
    combined_equity: pd.Series,
    per_slot_equity: Dict[str, pd.Series],
    initial_capital: float,
    risk_free_rate: float = 0.0,
) -> Dict[str, Any]:
    """
    Compute portfolio-level performance metrics.

    Args:
        combined_equity: Combined portfolio equity curve (date-indexed)
        per_slot_equity: Dict of slot_id -> equity series
        initial_capital: Total initial capital
        risk_free_rate: Annual risk-free rate (default 0)

    Returns:
        Dict with portfolio metrics.
    """
    if combined_equity.empty or len(combined_equity) < 2:
        return _empty_metrics()

    values = combined_equity.values.astype(float)
    n_days = len(values)

    # Daily returns
    daily_returns = np.diff(values) / values[:-1]

    # Sharpe ratio (annualized)
    mean_ret = np.mean(daily_returns)
    std_ret = np.std(daily_returns, ddof=1)
    sharpe = (mean_ret - risk_free_rate / 252) / std_ret * math.sqrt(252) if std_ret > 0 else 0.0

    # Max drawdown
    peak = np.maximum.accumulate(values)
    drawdowns = (values - peak) / peak
    max_dd = float(np.min(drawdowns))

    # Annual return
    total_return = values[-1] / values[0]
    annual_return = total_return ** (252.0 / n_days) - 1

    # Calmar ratio
    calmar = annual_return / abs(max_dd) if abs(max_dd) > 0 else 0.0

    # Per-slot contribution
    slot_contributions = {}
    total_final = float(combined_equity.iloc[-1])
    for slot_id, eq in per_slot_equity.items():
        if eq.empty:
            continue
        slot_final = float(eq.iloc[-1])
        slot_initial = float(eq.iloc[0])
        slot_return = (slot_final - slot_initial) / slot_initial if slot_initial > 0 else 0.0
        slot_contributions[slot_id] = {
            'final_equity': slot_final,
            'return_pct': round(slot_return * 100, 2),
            'weight': round(slot_final / total_final * 100, 2) if total_final > 0 else 0.0,
        }

    return {
        'sharpe_ratio': round(sharpe, 4),
        'annual_return': round(annual_return, 4),
        'max_drawdown': round(max_dd, 4),
        'calmar_ratio': round(calmar, 4),
        'total_return': round(total_return - 1, 4),
        'n_days': n_days,
        'initial_capital': initial_capital,
        'final_equity': round(float(values[-1]), 2),
        'slot_contributions': slot_contributions,
    }


def compute_correlation_matrix(
    per_slot_equity: Dict[str, pd.Series],
) -> Optional[pd.DataFrame]:
    """
    Compute pairwise daily return correlation between slots.

    Args:
        per_slot_equity: Dict of slot_id -> equity series (date-indexed)

    Returns:
        Correlation DataFrame, or None if fewer than 2 slots.
    """
    if len(per_slot_equity) < 2:
        return None

    returns_df = pd.DataFrame()
    for slot_id, eq in per_slot_equity.items():
        if eq.empty or len(eq) < 2:
            continue
        daily_ret = eq.pct_change().dropna()
        returns_df[slot_id] = daily_ret

    if returns_df.shape[1] < 2:
        return None

    return returns_df.corr()


def validate_margin(
    per_slot_equity: Dict[str, pd.Series],
    per_slot_margin: Dict[str, pd.Series],
    max_total_capital: float,
) -> Dict[str, Any]:
    """
    Post-hoc margin validation: check that total margin never exceeded capital.

    Args:
        per_slot_equity: Dict of slot_id -> equity series
        per_slot_margin: Dict of slot_id -> margin used series
        max_total_capital: Maximum total capital limit

    Returns:
        Dict with validation results.
    """
    # Align all series by date
    all_dates = set()
    for eq in per_slot_equity.values():
        all_dates.update(eq.index)
    all_dates = sorted(all_dates)

    violations = []
    max_margin_seen = 0.0

    for dt in all_dates:
        total_margin = 0.0
        total_equity = 0.0
        for slot_id in per_slot_equity:
            eq = per_slot_equity[slot_id]
            mg = per_slot_margin.get(slot_id, pd.Series(dtype=float))
            if dt in eq.index:
                total_equity += float(eq.loc[dt])
            if dt in mg.index:
                total_margin += float(mg.loc[dt])

        max_margin_seen = max(max_margin_seen, total_margin)

        if total_margin > max_total_capital:
            violations.append({
                'date': str(dt),
                'total_margin': round(total_margin, 2),
                'total_equity': round(total_equity, 2),
                'limit': max_total_capital,
            })

    return {
        'passed': len(violations) == 0,
        'max_margin_seen': round(max_margin_seen, 2),
        'violation_count': len(violations),
        'violations': violations[:10],  # First 10 only
    }


def compute_per_year_returns(
    combined_equity: pd.Series,
    per_slot_equity: Dict[str, pd.Series],
) -> Dict[str, Any]:
    """
    Compute per-calendar-year returns from a continuous equity curve.

    For each year present in the data, computes:
    - Portfolio return (from first to last equity value of the year)
    - Per-slot returns
    - Portfolio Sharpe for that year

    Args:
        combined_equity: Combined portfolio equity curve (date-indexed)
        per_slot_equity: Dict of slot_id -> equity series

    Returns:
        Dict with 'years' list of per-year stats.
    """
    if combined_equity.empty or len(combined_equity) < 2:
        return {'years': []}

    years_data = []
    equity_by_year = combined_equity.groupby(combined_equity.index.year)

    for year, year_eq in equity_by_year:
        if len(year_eq) < 2:
            continue

        start_val = float(year_eq.iloc[0])
        end_val = float(year_eq.iloc[-1])
        year_return = (end_val / start_val - 1) * 100

        # Annualized Sharpe for this year
        daily_rets = year_eq.pct_change().dropna().values
        if len(daily_rets) > 1 and np.std(daily_rets) > 0:
            year_sharpe = round(
                float(np.mean(daily_rets) / np.std(daily_rets, ddof=1) * math.sqrt(252)),
                3,
            )
        else:
            year_sharpe = 0.0

        # Max drawdown for this year
        vals = year_eq.values.astype(float)
        peak = np.maximum.accumulate(vals)
        dd = (vals - peak) / peak
        year_max_dd = round(float(np.min(dd)) * 100, 2)

        # Per-slot returns for this year
        slot_returns = {}
        for slot_id, eq in per_slot_equity.items():
            slot_year = eq[eq.index.year == year]
            if len(slot_year) >= 2:
                s_start = float(slot_year.iloc[0])
                s_end = float(slot_year.iloc[-1])
                slot_returns[slot_id] = round((s_end / s_start - 1) * 100, 2)

        years_data.append({
            'year': int(year),
            'return_pct': round(year_return, 2),
            'sharpe': year_sharpe,
            'max_dd_pct': year_max_dd,
            'trading_days': len(year_eq),
            'start_equity': round(start_val, 2),
            'end_equity': round(end_val, 2),
            'slot_returns': slot_returns,
        })

    return {'years': years_data}


def _empty_metrics() -> Dict[str, Any]:
    """Return empty metrics dict."""
    return {
        'sharpe_ratio': 0.0,
        'annual_return': 0.0,
        'max_drawdown': 0.0,
        'calmar_ratio': 0.0,
        'total_return': 0.0,
        'n_days': 0,
        'initial_capital': 0.0,
        'final_equity': 0.0,
        'slot_contributions': {},
    }
