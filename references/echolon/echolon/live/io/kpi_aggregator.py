"""
Portfolio dashboard aggregator
==============================

Reads per-slot trading data from workspace CSV files and strategy state,
computes per-slot KPIs (via ``generate_dashboard_data``), enriches each
slot with config metadata + capital state, computes portfolio-level
aggregates (equity curve, KPIs, backtest comparison), and produces the
full PortfolioDashboardPayload.

Data sources (per slot):
  - trading_data_{symbol}.csv     -> equity curve, current position
  - trade_executions_{symbol}.csv -> win rate, profit factor, avg hold days
  - strategy_state.json           -> bars in position (hold days)

Output: deploy_data/portfolio/dashboard_portfolio.json

HTTP posting to a specific backend is a consumer concern and lives in the
goingmerry portal_client module.
"""

import json
import logging
import math
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd

from echolon.config.markets.factory import MarketFactory

from ..config.logging_config import get_deploy_logger
from ..config.portfolio_deploy_config import PortfolioDeployConfig, SlotConfig

logger = get_deploy_logger(__name__)


# =============================================================================
# DATA GENERATOR (per-slot)
# =============================================================================

def generate_dashboard_data(
    trading_data_dir: str,
    strategy_state_path: str,
    main_contract: str,
    symbol: str = 'aluminum',
    contract_multiplier: int = 5,
) -> Dict[str, Any]:
    """
    Generate per-slot dashboard data from workspace files.

    Strategy info, backtest comparison, and capital enrichment are handled
    by the DashboardAggregator using portfolio_deploy_config.json.

    Args:
        trading_data_dir: Directory containing trading CSVs (workspace/deploy/)
        strategy_state_path: Path to strategy_state.json
        main_contract: Current main contract (e.g. "al2604.SF")
        symbol: Instrument name used in CSV filenames
        contract_multiplier: Futures contract multiplier (aluminum = 5)

    Returns:
        Dictionary with: updated_at, equity_curve, position, kpis
    """
    # Load raw data
    trading_data = _load_trading_data(trading_data_dir, symbol)
    executions = _load_trade_executions(trading_data_dir, symbol)
    strategy_state = _load_json(strategy_state_path)

    # All public-facing data is 24h delayed: exclude today's rows so the
    # dashboard reflects yesterday's close, not today's in-progress cycle.
    delayed_data = _exclude_today_rows(trading_data)
    delayed_executions = _exclude_today_rows(executions)

    equity_curve = _build_equity_curve(delayed_data)
    position = _build_position(delayed_data, strategy_state, main_contract, contract_multiplier)
    last_trade = _build_last_trade(delayed_data, main_contract)
    kpis = _compute_kpis(delayed_data, delayed_executions)

    dashboard_data = {
        'updated_at': datetime.now().astimezone().isoformat(),
        'equity_curve': equity_curve,
        'position': position,
        'last_trade': last_trade,
        'kpis': kpis,
    }

    logger.info(
        f"Dashboard data generated: {len(equity_curve)} equity points, "
        f"position={'FLAT' if position is None else position['direction']}, "
        f"last_trade={last_trade['action'] if last_trade else 'none'}"
    )
    return dashboard_data


# -----------------------------------------------------------------------------
# Per-slot Data Loading
# -----------------------------------------------------------------------------

def _load_trading_data(trading_data_dir: str, symbol: str) -> Optional[pd.DataFrame]:
    """Load trading_data_{symbol}.csv."""
    path = os.path.join(trading_data_dir, f'trading_data_{symbol}.csv')
    if not os.path.exists(path):
        logger.warning(f"Trading data not found: {path}")
        return None
    df = pd.read_csv(path)
    if 'timestamp' in df.columns:
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df.sort_values('timestamp')
    return df


def _load_trade_executions(trading_data_dir: str, symbol: str) -> Optional[pd.DataFrame]:
    """Load trade_executions_{symbol}.csv."""
    path = os.path.join(trading_data_dir, f'trade_executions_{symbol}.csv')
    if not os.path.exists(path):
        logger.warning(f"Trade executions not found: {path}")
        return None
    df = pd.read_csv(path)
    if 'timestamp' in df.columns:
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df.sort_values('timestamp')
    return df


def _load_json(path: str) -> Optional[Dict[str, Any]]:
    """Load a JSON file, return None if not found."""
    if not path or not os.path.exists(path):
        logger.warning(f"JSON file not found: {path}")
        return None
    with open(path, 'r') as f:
        return json.load(f)


# -----------------------------------------------------------------------------
# 24h Delay
# -----------------------------------------------------------------------------

def _exclude_today_rows(df: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
    """
    Exclude rows whose timestamp matches today's date to enforce 24h public delay.

    The generator runs immediately after today's trading cycle, so today's
    rows contain current position and equity. Filtering by date (instead of
    blindly dropping the last row) is correct because some DataFrames like
    trade_executions may not have any row from today.
    """
    if df is None or df.empty:
        return df
    if 'timestamp' not in df.columns:
        return df
    today = datetime.now().date()
    mask = df['timestamp'].dt.date != today
    filtered = df.loc[mask]
    return filtered if not filtered.empty else df.iloc[:0].copy()


# -----------------------------------------------------------------------------
# Equity Curve
# -----------------------------------------------------------------------------

def _build_equity_curve(trading_data: Optional[pd.DataFrame]) -> list:
    """Extract (date, value) pairs from trading data snapshots."""
    if trading_data is None or trading_data.empty:
        return []

    points = []
    for _, row in trading_data.iterrows():
        date_str = row['timestamp'].strftime('%Y-%m-%d') if hasattr(row['timestamp'], 'strftime') else str(row['timestamp'])[:10]
        points.append({
            'date': date_str,
            'value': round(float(row['total_account_value']), 2),
        })
    return points


# -----------------------------------------------------------------------------
# Position
# -----------------------------------------------------------------------------

def _build_position(
    trading_data: Optional[pd.DataFrame],
    strategy_state: Optional[Dict[str, Any]],
    main_contract: str,
    contract_multiplier: int,
) -> Optional[Dict[str, Any]]:
    """Build current position info from latest trading data row + strategy state."""
    if trading_data is None or trading_data.empty:
        return None

    latest = trading_data.iloc[-1]
    size = float(latest.get('current_position_size', 0))

    if size == 0:
        return None

    # Read direction directly from CSV column, fall back to scanning for old data
    direction = 'LONG'
    if 'position_direction' in latest.index and latest.get('position_direction'):
        direction = str(latest['position_direction']).upper()
    else:
        # Fallback for old CSV data without position_direction column
        for idx in range(len(trading_data) - 1, -1, -1):
            action = str(trading_data.iloc[idx].get('last_action', ''))
            if 'ENTRY_LONG' in action:
                direction = 'LONG'
                break
            elif 'ENTRY_SHORT' in action:
                direction = 'SHORT'
                break

    entry_price = float(latest.get('current_position_avg_price', 0))
    unrealized_pnl = float(latest.get('unrealized_pnl', 0))

    # Read position contract from CSV column, fallback to main_contract
    contract = ''
    if 'position_contract' in latest.index:
        contract = str(latest.get('position_contract', '') or '')
    if not contract:
        contract = main_contract

    # Calculate PnL percentage relative to notional value
    notional = entry_price * abs(size) * contract_multiplier
    unrealized_pnl_pct = (unrealized_pnl / notional * 100) if notional > 0 else 0.0

    # Hold days: count rows from last ENTRY to current row
    hold_days = 0
    for idx in range(len(trading_data) - 1, -1, -1):
        action = str(trading_data.iloc[idx].get('last_action', ''))
        if 'ENTRY' in action:
            hold_days = len(trading_data) - 1 - idx
            break

    return {
        'direction': direction,
        'contract': contract,
        'entry_price': entry_price,
        'unrealized_pnl': unrealized_pnl,
        'unrealized_pnl_pct': round(unrealized_pnl_pct, 2),
        'hold_days': hold_days,
    }


# -----------------------------------------------------------------------------
# Last Trade Action
# -----------------------------------------------------------------------------

def _build_last_trade(
    trading_data: Optional[pd.DataFrame],
    main_contract: str,
) -> Optional[Dict[str, Any]]:
    """Extract the last trade action (ENTRY/EXIT) from the most recent row.

    Returns None if no trade action occurred on the latest day.
    """
    if trading_data is None or trading_data.empty:
        return None

    latest = trading_data.iloc[-1]
    action = str(latest.get('last_action', ''))

    if 'ENTRY' not in action and 'EXIT' not in action:
        return None

    # Read action contract from CSV (new column), fallback to main_contract
    contract = ''
    if 'action_contract' in latest.index:
        contract = str(latest.get('action_contract', ''))
    if not contract:
        contract = main_contract

    return {
        'action': action,
        'price': float(latest.get('last_action_price', 0)),
        'contract': contract,
    }


# -----------------------------------------------------------------------------
# KPI Computation (per-slot)
# -----------------------------------------------------------------------------

def _compute_kpis(
    trading_data: Optional[pd.DataFrame],
    executions: Optional[pd.DataFrame],
) -> Dict[str, Any]:
    """Compute all KPIs from trading data and execution history.

    Minimum data requirements to avoid misleading annualized metrics:
      - Sharpe ratio:  >= 30 trading days
      - Annual return: >= 20 trading days
      - Max drawdown:  >= 10 trading days
    Below these thresholds the KPI stays None (displayed as "-").
    """
    MIN_DAYS_SHARPE = 30
    MIN_DAYS_ANNUAL_RETURN = 20
    MIN_DAYS_MAX_DRAWDOWN = 10

    kpis: Dict[str, Any] = {
        'sharpe_ratio': None,
        'annual_return': None,
        'max_drawdown': None,
        'win_rate': None,
        'profit_factor': None,
        'avg_hold_days': None,
        'trades_per_week': None,
    }

    if trading_data is not None and len(trading_data) >= 2:
        values = trading_data['total_account_value'].values
        n_days = len(values)

        # Max drawdown
        if n_days >= MIN_DAYS_MAX_DRAWDOWN:
            peak = values[0]
            max_dd = 0.0
            for v in values:
                if v > peak:
                    peak = v
                dd = (v - peak) / peak
                if dd < max_dd:
                    max_dd = dd
            kpis['max_drawdown'] = round(max_dd, 4)

        # Annual return (annualized from first to last)
        if n_days >= MIN_DAYS_ANNUAL_RETURN:
            first_val = float(values[0])
            last_val = float(values[-1])
            if first_val > 0:
                total_return = last_val / first_val
                annualized = total_return ** (252.0 / n_days) - 1
                kpis['annual_return'] = round(annualized, 4)

        # Sharpe ratio
        if n_days >= MIN_DAYS_SHARPE:
            daily_returns = []
            for i in range(1, len(values)):
                if values[i - 1] > 0:
                    daily_returns.append(values[i] / values[i - 1] - 1)
            if daily_returns:
                mean_ret = sum(daily_returns) / len(daily_returns)
                variance = sum((r - mean_ret) ** 2 for r in daily_returns) / len(daily_returns)
                std_ret = math.sqrt(variance)
                if std_ret > 0:
                    kpis['sharpe_ratio'] = round(mean_ret / std_ret * math.sqrt(252), 2)

    # Trade-level metrics from executions
    if executions is not None and len(executions) > 0:
        # Filter to exit trades (they have realized_pnl)
        exits = executions[executions['direction'].str.contains('EXIT', na=False)]

        if len(exits) > 0:
            pnls = exits['realized_pnl'].astype(float)
            wins = pnls[pnls > 0]
            losses = pnls[pnls < 0]

            total_trades = len(exits)
            kpis['win_rate'] = round(len(wins) / total_trades, 3) if total_trades > 0 else 0.0

            if len(losses) > 0 and abs(losses.sum()) > 0:
                kpis['profit_factor'] = round(float(wins.sum()) / abs(float(losses.sum())), 2)
            elif len(wins) > 0:
                kpis['profit_factor'] = 99.0  # All winners, cap display

            # Trades per week
            if trading_data is not None and len(trading_data) >= 2:
                first_ts = trading_data['timestamp'].iloc[0]
                last_ts = trading_data['timestamp'].iloc[-1]
                weeks = max((last_ts - first_ts).days / 7.0, 1.0)
                kpis['trades_per_week'] = round(total_trades / weeks, 1)

            # Avg hold days - pair entries with exits chronologically
            entries = executions[executions['direction'].str.contains('ENTRY', na=False)]
            if len(entries) > 0 and len(exits) > 0:
                entry_times = entries['timestamp'].values
                exit_times = exits['timestamp'].values
                hold_days_list = []
                for j in range(min(len(entry_times), len(exit_times))):
                    days = (exit_times[j] - entry_times[j]) / pd.Timedelta(days=1)
                    if days >= 0:
                        hold_days_list.append(days)
                if hold_days_list:
                    kpis['avg_hold_days'] = round(sum(hold_days_list) / len(hold_days_list), 1)

    # Win rate from trading_data if no exit trades yet
    if kpis['win_rate'] is None and trading_data is not None and len(trading_data) > 0:
        latest = trading_data.iloc[-1]
        trade_count = int(latest.get('trade_count', 0))
        win_rate_raw = float(latest.get('win_rate', 0))
        if trade_count > 0:
            kpis['win_rate'] = round(win_rate_raw / 100.0, 3)

    return kpis


# =============================================================================
# AGGREGATOR (portfolio-level)
# =============================================================================

def _compute_portfolio_equity_and_peak(
    deploy_config: PortfolioDeployConfig,
    deploy_data_dir: str,
) -> tuple:
    """Compute current portfolio equity + historical peak from per-slot CSVs.

    Equity = sum of latest total_account_value across slots (falling back to
    initial_capital when a slot has no CSV yet).
    Peak = max over time of the aggregate curve.
    """
    enabled = deploy_config.get_enabled_slots()

    per_slot_curves: Dict[str, Dict[str, float]] = {}
    latest_equity: Dict[str, float] = {}
    for slot in enabled:
        csv_path = os.path.join(deploy_data_dir, "slots", slot.slot_id, f"trading_data_{slot.instrument}.csv")
        if not os.path.exists(csv_path):
            latest_equity[slot.slot_id] = slot.initial_capital
            continue
        df = pd.read_csv(csv_path)
        if "timestamp" in df.columns and "total_account_value" in df.columns:
            df["date"] = pd.to_datetime(df["timestamp"]).dt.strftime("%Y-%m-%d")
            per_slot_curves[slot.slot_id] = dict(zip(df["date"], df["total_account_value"].astype(float)))
            latest_equity[slot.slot_id] = float(df["total_account_value"].iloc[-1])
        else:
            latest_equity[slot.slot_id] = slot.initial_capital

    equity = sum(latest_equity[s.slot_id] for s in enabled)

    if per_slot_curves:
        all_dates = sorted({d for curve in per_slot_curves.values() for d in curve})
        peak = 0.0
        for date in all_dates:
            total = sum(
                per_slot_curves.get(slot.slot_id, {}).get(date, slot.initial_capital)
                for slot in enabled
            )
            peak = max(peak, total)
    else:
        peak = sum(s.initial_capital for s in enabled)

    return equity, peak


def generate_portfolio_dashboard(
    deploy_config: PortfolioDeployConfig,
    deploy_data_dir: str,
    portfolio_equity: Optional[float] = None,
    portfolio_peak: Optional[float] = None,
    slot_statuses: Optional[Dict[str, str]] = None,
    exclude_today: bool = True,
) -> Dict[str, Any]:
    """
    Generate portfolio dashboard with per-slot + aggregate views.

    Args:
        deploy_config: Loaded PortfolioDeployConfig with slot definitions.
        deploy_data_dir: Base deploy data directory.
        portfolio_equity: Current total portfolio equity. Auto-computed from
            per-slot CSVs when None.
        portfolio_peak: Peak portfolio equity (for DD calculation). Auto-computed
            when None.
        slot_statuses: Mapping of slot_id -> "OK" / "ERROR". Defaults to all
            "OK" when None.

    Returns:
        Full PortfolioDashboardPayload matching the migration schema.
    """
    # Auto-compute equity/peak if not supplied
    if portfolio_equity is None or portfolio_peak is None:
        equity_auto, peak_auto = _compute_portfolio_equity_and_peak(deploy_config, deploy_data_dir)
        if portfolio_equity is None:
            portfolio_equity = equity_auto
        if portfolio_peak is None:
            portfolio_peak = peak_auto
    if slot_statuses is None:
        slot_statuses = {s.slot_id: "OK" for s in deploy_config.get_enabled_slots()}
    enabled_slots = deploy_config.get_enabled_slots()
    slot_dashboards: List[Dict[str, Any]] = []

    for slot_config in sorted(enabled_slots, key=lambda s: s.slot_id):
        slot_id = slot_config.slot_id
        status = slot_statuses.get(slot_id, 'OK')
        strategy_state: Dict[str, Any] = {}

        # Generate runtime data (equity curve, position, kpis)
        try:
            slot_dir = os.path.join(deploy_data_dir, 'slots', slot_id)
            trading_data_dir = slot_dir
            state_path = os.path.join(slot_dir, 'strategy_state.json')
            strategy_state = _load_json(state_path) or {}

            # Resolve main contract from strategy state
            main_contract = strategy_state.get('position_symbol', '')

            dd = generate_dashboard_data(
                trading_data_dir=trading_data_dir,
                strategy_state_path=state_path,
                main_contract=main_contract,
                symbol=slot_config.instrument,
                contract_multiplier=_get_multiplier(slot_config),
            )
        except Exception as e:
            logger.warning(f"[{slot_id}] Dashboard generation failed: {e}")
            dd = {
                'updated_at': datetime.now().astimezone().isoformat(),
                'equity_curve': [],
                'position': None,
                'kpis': _empty_kpis(),
            }
            status = 'ERROR'

        # Enrich with config metadata + capital
        enriched = _enrich_slot_data(dd, slot_config, strategy_state, status)
        slot_dashboards.append(enriched)

    # Build portfolio aggregate
    total_initial_capital = sum(s.initial_capital for s in enabled_slots)

    # Use real equity from slot curves if available, else fallback
    if slot_dashboards:
        portfolio_equity_from_curves = sum(
            sd['capital']['equity'] for sd in slot_dashboards
            if sd['status'] == 'OK'
        )
        if portfolio_equity_from_curves > 0:
            portfolio_equity = portfolio_equity_from_curves

    portfolio_equity_curve = _build_portfolio_equity_curve(slot_dashboards)
    portfolio_kpis = _compute_portfolio_kpis(portfolio_equity_curve, slot_dashboards, exclude_today)
    portfolio_backtest = _build_portfolio_backtest_comparison(
        portfolio_kpis, deploy_config
    )

    dd_pct = 0.0
    if portfolio_peak > 0:
        dd_pct = round((portfolio_peak - portfolio_equity) / portfolio_peak * 100.0, 2)

    total_return_pct = 0.0
    if total_initial_capital > 0:
        total_return_pct = round(
            (portfolio_equity - total_initial_capital) / total_initial_capital * 100.0, 2
        )

    active_count = sum(1 for sd in slot_dashboards if sd['status'] == 'OK')
    errored_count = sum(1 for sd in slot_dashboards if sd['status'] == 'ERROR')

    payload = {
        'updated_at': datetime.now().astimezone().isoformat(),
        'portfolio': {
            'equity_curve': portfolio_equity_curve,
            'total_equity': round(portfolio_equity, 2),
            'total_initial_capital': round(total_initial_capital, 2),
            'total_return_pct': total_return_pct,
            'kpis': portfolio_kpis,
            'backtest_comparison': portfolio_backtest,
            'peak_equity': round(portfolio_peak, 2),
            'drawdown_pct': dd_pct,
            'active_slots': active_count,
            'errored_slots': errored_count,
            'total_slots': len(deploy_config.slots),
        },
        'slots': slot_dashboards,
    }

    return payload


def save_portfolio_dashboard(
    dashboard: Dict[str, Any],
    output_path: str,
) -> None:
    """Save portfolio dashboard to JSON."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(dashboard, f, indent=2, default=str)
    logger.info(f"Portfolio dashboard saved to {output_path}")


# -----------------------------------------------------------------------------
# Slot Enrichment
# -----------------------------------------------------------------------------

def _enrich_slot_data(
    slot_dashboard: Dict[str, Any],
    slot_config: SlotConfig,
    strategy_state: Dict[str, Any],
    status: str,
) -> Dict[str, Any]:
    """Add metadata, strategy info, backtest comparison, and capital to per-slot data."""
    capital_state = strategy_state.get('custom', {}).get('capital', {})
    db = slot_config.dashboard

    # Metadata from config (strategy_id excluded - not for public display)
    slot_dashboard['slot_id'] = slot_config.slot_id
    slot_dashboard['instrument'] = slot_config.instrument
    slot_dashboard['instrument_code'] = slot_config.instrument_code
    slot_dashboard['status'] = status

    # Strategy info from config (replaces hardcoded _build_strategy_info)
    slot_dashboard['strategy'] = {
        'name': db.strategy_name,
        'type': db.strategy_type,
        'market': db.display_market,
        'frequency': db.display_frequency,
        'live_since': db.live_since,
        'steps': [{'title': s.title, 'desc': s.desc} for s in db.strategy_steps],
    }

    # Backtest comparison from config
    bt = db.backtest_metrics
    live_kpis = slot_dashboard.get('kpis', {})
    slot_dashboard['backtest_comparison'] = {
        'sharpe_ratio': {
            'backtest': bt.get('sharpe_ratio', 0),
            'live': live_kpis.get('sharpe_ratio'),
        },
        'annual_return': {
            'backtest': bt.get('annual_return', 0),
            'live': live_kpis.get('annual_return'),
        },
        'max_drawdown': {
            'backtest': bt.get('max_drawdown', 0),
            'live': live_kpis.get('max_drawdown'),
        },
    }

    # Capital from strategy_state.json
    unrealized_pnl = 0.0
    if slot_dashboard.get('position'):
        unrealized_pnl = slot_dashboard['position'].get('unrealized_pnl', 0.0)

    equity = slot_config.initial_capital
    if slot_dashboard.get('equity_curve'):
        equity = slot_dashboard['equity_curve'][-1]['value']

    slot_dashboard['capital'] = {
        'initial': capital_state.get('initial_capital', slot_config.initial_capital),
        'equity': equity,
        'realized_pnl': capital_state.get('realized_pnl', 0.0),
        'unrealized_pnl': unrealized_pnl,
    }

    return slot_dashboard


# -----------------------------------------------------------------------------
# Portfolio Equity Curve
# -----------------------------------------------------------------------------

def _build_portfolio_equity_curve(
    slot_dashboards: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Sum per-slot equity curves aligned by date.

    For dates where a slot has no data point (started later or errored),
    use that slot's initial_capital as the value.
    """
    ok_slots = [sd for sd in slot_dashboards if sd.get('status') == 'OK']
    if not ok_slots:
        return []

    # Pre-build date-to-value maps once per slot (avoid O(dates*slots*curve) rebuild)
    slot_curves = []
    all_date_set: set = set()
    for sd in ok_slots:
        curve_map = {p['date']: p['value'] for p in sd.get('equity_curve', [])}
        slot_curves.append((curve_map, sd['capital']['initial']))
        all_date_set.update(curve_map.keys())

    all_dates = sorted(all_date_set)

    portfolio_curve = []
    for date in all_dates:
        total = 0.0
        for curve_map, initial in slot_curves:
            total += curve_map.get(date, initial)
        portfolio_curve.append({'date': date, 'value': round(total, 2)})

    return portfolio_curve


# -----------------------------------------------------------------------------
# Portfolio KPIs
# -----------------------------------------------------------------------------

def _compute_portfolio_kpis(
    portfolio_equity_curve: List[Dict[str, Any]],
    slot_dashboards: List[Dict[str, Any]],
    exclude_today: bool = True,
) -> Dict[str, Any]:
    """Compute portfolio KPIs from aggregate equity curve + per-slot trade stats.

    Applies 24h delay (excludes today's data point) for curve-derived KPIs
    unless exclude_today is False.
    """
    MIN_DAYS_SHARPE = 30
    MIN_DAYS_ANNUAL_RETURN = 20
    MIN_DAYS_MAX_DRAWDOWN = 10

    kpis: Dict[str, Any] = _empty_kpis()

    # Apply 24h delay - exclude today's data point
    if exclude_today:
        today_str = datetime.now().strftime('%Y-%m-%d')
        delayed_curve = [p for p in portfolio_equity_curve if p['date'] != today_str]
    else:
        delayed_curve = list(portfolio_equity_curve)
    values = [p['value'] for p in delayed_curve]

    if len(values) >= 2:
        n_days = len(values)

        # Max drawdown
        if n_days >= MIN_DAYS_MAX_DRAWDOWN:
            peak = values[0]
            max_dd = 0.0
            for v in values:
                if v > peak:
                    peak = v
                dd = (v - peak) / peak
                if dd < max_dd:
                    max_dd = dd
            kpis['max_drawdown'] = round(max_dd, 4)

        # Annual return
        if n_days >= MIN_DAYS_ANNUAL_RETURN:
            first_val = float(values[0])
            last_val = float(values[-1])
            if first_val > 0:
                total_return = last_val / first_val
                annualized = total_return ** (252.0 / n_days) - 1
                kpis['annual_return'] = round(annualized, 4)

        # Sharpe ratio
        if n_days >= MIN_DAYS_SHARPE:
            daily_returns = []
            for i in range(1, len(values)):
                if values[i - 1] > 0:
                    daily_returns.append(values[i] / values[i - 1] - 1)
            if daily_returns:
                mean_ret = sum(daily_returns) / len(daily_returns)
                variance = sum((r - mean_ret) ** 2 for r in daily_returns) / len(daily_returns)
                std_ret = math.sqrt(variance)
                if std_ret > 0:
                    kpis['sharpe_ratio'] = round(mean_ret / std_ret * math.sqrt(252), 2)

    # Trade-aggregated KPIs from per-slot values (OK slots only)
    ok_slots = [sd for sd in slot_dashboards if sd.get('status') == 'OK']
    for kpi_key in ['win_rate', 'profit_factor', 'avg_hold_days', 'trades_per_week']:
        slot_values = [
            sd['kpis'][kpi_key]
            for sd in ok_slots
            if sd.get('kpis', {}).get(kpi_key) is not None
        ]
        if not slot_values:
            kpis[kpi_key] = None
        elif kpi_key == 'trades_per_week':
            kpis[kpi_key] = round(sum(slot_values), 1)
        else:
            kpis[kpi_key] = round(sum(slot_values) / len(slot_values), 3)

    return kpis


# -----------------------------------------------------------------------------
# Portfolio Backtest Comparison
# -----------------------------------------------------------------------------

def _build_portfolio_backtest_comparison(
    portfolio_kpis: Dict[str, Any],
    deploy_config: PortfolioDeployConfig,
) -> Dict[str, Any]:
    """Combine config backtest metrics with live portfolio KPIs."""
    bt = deploy_config.deploy.portfolio_backtest_metrics
    return {
        'sharpe_ratio': {
            'backtest': bt.get('sharpe_ratio', 0),
            'live': portfolio_kpis.get('sharpe_ratio'),
        },
        'annual_return': {
            'backtest': bt.get('annual_return', 0),
            'live': portfolio_kpis.get('annual_return'),
        },
        'max_drawdown': {
            'backtest': bt.get('max_drawdown', 0),
            'live': portfolio_kpis.get('max_drawdown'),
        },
    }


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def _empty_kpis() -> Dict[str, Any]:
    return {
        'sharpe_ratio': None,
        'annual_return': None,
        'max_drawdown': None,
        'win_rate': None,
        'profit_factor': None,
        'avg_hold_days': None,
        'trades_per_week': None,
    }


def _get_multiplier(slot_config: SlotConfig) -> int:
    """Get contract multiplier from instrument specs via MarketFactory."""
    spec = MarketFactory.get_instrument(slot_config.market, slot_config.instrument_code)
    if spec:
        return int(spec.multiplier)
    logger.warning(
        f"[{slot_config.slot_id}] Unknown instrument {slot_config.market}/{slot_config.instrument_code}, "
        f"using default multiplier 5"
    )
    return 5


# =============================================================================
# Public API aliases (stable names for consumers like goingmerry)
# =============================================================================

def aggregate_portfolio(
    deploy_config: PortfolioDeployConfig,
    workspace_dir: str,
    exclude_today: bool = True,
) -> Dict[str, Any]:
    """Public entry point: aggregate per-slot state into a portfolio dashboard payload.

    Automatically computes portfolio equity + peak from per-slot CSVs.

    Args:
        deploy_config: Loaded PortfolioDeployConfig.
        workspace_dir: Directory containing `deploy/slots/{slot_id}/...` files.
            (Typically `./workspace` — the function appends `/deploy` internally.)
        exclude_today: Apply 24h public-delay filter.
    """
    deploy_data_dir = os.path.join(workspace_dir, "deploy")
    return generate_portfolio_dashboard(
        deploy_config=deploy_config,
        deploy_data_dir=deploy_data_dir,
        exclude_today=exclude_today,
    )


def load_slot_state(workspace_dir: str, slot_id: str) -> Optional[Dict[str, Any]]:
    """Read a slot's strategy_state.json safely. Returns None if missing."""
    path = os.path.join(workspace_dir, "deploy", "slots", slot_id, "strategy_state.json")
    return _load_json(path)


def load_equity_curve(workspace_dir: str, slot_id: str, instrument: str):
    """Read a slot's trading_data CSV as a DataFrame. Returns None if missing."""
    return _load_trading_data(
        os.path.join(workspace_dir, "deploy", "slots", slot_id),
        instrument,
    )
