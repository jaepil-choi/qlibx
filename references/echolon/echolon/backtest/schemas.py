"""Backtest schemas — contracts between backtest engine and downstream consumers.

Schemas defined here:
    - BacktestResultsSchemaV4   (backtest_results.json)
    - TradeRecordSchema         (backtest_trades.csv)
    - StrategyLogRecordSchema   (Bridge_default.csv)
    - SelectedTrialSchema       (selected_robust_trial.json)

Producer: echolon/backtest/engine/* + optimization/trial_selector.py.
Consumer: backtest_metrics/utils/backtest_loader.py.
"""

import math
from datetime import datetime, date
from datetime import datetime as dt
from math import isnan
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _is_nan(v) -> bool:
    """Check if value is NaN (handles float NaN from pandas)."""
    if v is None:
        return True
    if isinstance(v, float) and math.isnan(v):
        return True
    if v == '':
        return True
    return False


# =============================================================================
# BACKTEST RESULTS SCHEMA (was backtest_results.py, v4.0)
# =============================================================================

# ----- Trade Analyzer Nested Schemas -----

class TradeAnalyzerStreakSchema(BaseModel):
    """Streak statistics for won/lost trades."""
    current: int = Field(ge=0)
    longest: int = Field(ge=0)


class TradeAnalyzerPnLSchema(BaseModel):
    """PnL statistics."""
    total: float
    average: float
    max: Optional[float] = None


class TradeAnalyzerWonLostSchema(BaseModel):
    """Won/Lost trade statistics."""
    total: int = Field(ge=0)
    pnl: TradeAnalyzerPnLSchema


class TradeAnalyzerLengthStatsSchema(BaseModel):
    """Trade length statistics."""
    total: int = Field(ge=0)
    average: float
    max: int = Field(ge=0)
    min: int = Field(ge=0)
    won: Optional[Dict[str, Any]] = None
    lost: Optional[Dict[str, Any]] = None


class TradeAnalyzerDirectionSchema(BaseModel):
    """Long/Short direction breakdown."""
    model_config = ConfigDict(extra='allow')

    total: int = Field(ge=0)
    pnl: Dict[str, Any]  # Complex nested structure
    won: int = Field(ge=0)
    lost: int = Field(ge=0)


class TotalSchema(BaseModel):
    """Total trades breakdown."""
    total: int
    open: int = 0  # Default 0 for zero-trade backtests
    closed: int


class StreakSchema(BaseModel):
    """Streak statistics."""
    won: TradeAnalyzerStreakSchema
    lost: TradeAnalyzerStreakSchema


class GrossNetPnLSchema(BaseModel):
    """Gross/Net PnL breakdown."""
    total: float
    average: float


class PnLSchema(BaseModel):
    """Overall PnL structure."""
    gross: GrossNetPnLSchema
    net: GrossNetPnLSchema


class TradeAnalyzerDetailsSchema(BaseModel):
    """Backtrader TradeAnalyzer output schema."""
    model_config = ConfigDict(extra='allow')  # Allow extra fields

    total: TotalSchema
    streak: StreakSchema
    pnl: PnLSchema
    won: TradeAnalyzerWonLostSchema
    lost: TradeAnalyzerWonLostSchema

    long: Optional[TradeAnalyzerDirectionSchema] = None
    short: Optional[TradeAnalyzerDirectionSchema] = None

    len: Optional[TradeAnalyzerLengthStatsSchema] = None


class TimeDrawdownSchema(BaseModel):
    """Time-based drawdown analysis."""
    model_config = ConfigDict(extra='allow')

    max_drawdown_duration: int = Field(ge=0)
    drawdown_periods: Dict[str, Any] = Field(default_factory=dict)
    money_down_periods: Dict[str, Any] = Field(default_factory=dict)


class PeriodStatsSchema(BaseModel):
    """Period statistics (annual returns analysis)."""
    average: float
    stddev: float = Field(ge=0.0)
    positive: int = Field(ge=0)
    negative: int = Field(ge=0)
    nochange: int = Field(ge=0)
    best: float
    worst: float


# ----- Performance Metrics Schema -----

class PerformanceMetricsSchema(BaseModel):
    """Top-level performance metrics from backtrader analyzers."""
    model_config = ConfigDict(extra='allow')

    # REQUIRED FIELDS (Core KPIs)
    sharpe_ratio_annual: float = Field(
        description="Annualized Sharpe ratio from backtrader's SharpeRatio analyzer"
    )
    total_return_pct: float = Field(
        description="Total return percentage over backtest period"
    )
    max_drawdown_pct: float = Field(
        description="Maximum drawdown percentage (positive value in current format)"
    )
    total_trades: int = Field(
        description="Total number of closed trades",
        ge=0
    )
    winning_trades: int = Field(ge=0)
    losing_trades: int = Field(ge=0)
    win_rate_pct: float = Field(ge=0.0, le=100.0)

    initial_value: float = Field(gt=0)
    final_value: float = Field(gt=0)

    initial_capital: float = Field(gt=0)
    final_portfolio_value: float = Field(gt=0)
    trades_open: int = Field(ge=0)
    trades_closed: int = Field(ge=0)

    win_rate_analyzer: float = Field(ge=0.0, le=100.0)
    avg_win_pnl: float
    avg_loss_pnl: float
    profit_factor_analyzer: float = Field(ge=0.0)

    # OPTIONAL FIELDS (Extended metrics)
    sharpe_ratio_monthly: Optional[float] = None
    sharpe_ratio_weekly: Optional[float] = None
    calmar_ratio: Optional[float] = None
    sqn: Optional[float] = Field(None, description="System Quality Number")
    vwr: Optional[float] = Field(None, description="Variability-Weighted Return")

    average_annual_return_pct: Optional[float] = None
    max_drawdown_len: Optional[int] = Field(None, ge=0)

    # COMPLEX NESTED STRUCTURES
    trade_analyzer_details: Optional[TradeAnalyzerDetailsSchema] = None
    time_drawdown: Optional[TimeDrawdownSchema] = None
    period_stats: Optional[PeriodStatsSchema] = None

    # Time-based returns (can be large, allow as optional dict)
    daily_returns: Optional[Dict[str, float]] = Field(
        default=None,
        description="Daily returns dict {date_str: return_pct}"
    )
    monthly_returns: Optional[Dict[str, float]] = None
    annual_returns: Optional[Dict[str, float]] = None
    weekly_returns: Optional[Dict[str, float]] = None


# ----- Walk-Forward Analysis (WFA) Schemas -----

class WFAWindowDetailSchema(BaseModel):
    """Per-window WFA detail."""
    model_config = ConfigDict(extra='allow')

    window_id: int
    is_start: str
    is_end: str
    oos_start: str
    oos_end: str
    is_years: float
    oos_years: float
    is_sharpe: Optional[float] = None
    oos_sharpe: Optional[float] = None
    walk_forward_efficiency: Optional[float] = None
    oos_metrics: Optional[Dict[str, Any]] = None
    selected_trial_number: Optional[int] = None


class WFASummarySchema(BaseModel):
    """WFA aggregate summary metrics."""
    model_config = ConfigDict(extra='allow')

    total_windows: int
    completed_windows: int
    windows_zero_trades: int = 0
    wfe_mean: Optional[float] = None
    wfe_min: Optional[float] = None
    wfe_max: Optional[float] = None
    oos_sharpe_mean: Optional[float] = None
    oos_sharpe_std: Optional[float] = None
    oos_sharpe_min: Optional[float] = None
    oos_sharpe_consistency: Optional[float] = None
    parameter_stability_cv: Optional[Dict[str, float]] = None
    degradation_ratios: Optional[list] = None
    windows_positive_oos: int = 0


# ----- Deployment Readiness Score (DRS) Schemas -----

class DRSGateResultSchema(BaseModel):
    """Result of a single DRS hard gate check."""
    gate_id: str = Field(description="Gate identifier (G1-G6)")
    passed: bool
    value: float
    threshold: float
    description: str


class DRSComponentSchema(BaseModel):
    """Score for a single DRS component."""
    name: str = Field(description="Component name: oos_return, return_level, oos_edge, temporal_stability, oos_risk, param_confidence, gate_bonus")
    score: float = Field(ge=0.0)
    max_score: float = Field(gt=0.0)
    details: Dict[str, Any] = Field(default_factory=dict)


class DRSSchema(BaseModel):
    """Deployment Readiness Score - composite 0-100 score measuring deployment readiness.

    Architecture: Constrained Return Maximization
    - Return components (40pts): oos_return (25pts) + return_level (15pts)
    - Robustness components (35pts): oos_edge (20pts) + temporal_stability (15pts)
    - Risk constraint (10pts): oos_risk
    - Quality (8pts): param_confidence
    - Bonus (7pts): gate_bonus
    - 6 hard gates (G1-G6) must all pass or DRS=0
    """
    model_config = ConfigDict(extra='allow')

    drs_score: float = Field(ge=0.0, le=100.0, description="Composite DRS (0-100)")
    gates_passed: bool = Field(description="True if all 6 hard gates passed")
    weighted_oos_annual_return_pct: float = Field(
        description="Recency-weighted mean OOS annual return percentage"
    )
    recency_weighted_oos_sharpe: Optional[float] = Field(
        default=None,
        description="Deprecated: use weighted_oos_annual_return_pct instead"
    )
    gate_results: List[DRSGateResultSchema] = Field(
        description="Per-gate pass/fail details (G1-G6)"
    )
    components: Optional[List[DRSComponentSchema]] = Field(
        default=None,
        description="Per-component scores (only present when gates pass)"
    )
    component_breakdown: Optional[Dict[str, float]] = Field(
        default=None,
        description="Component name to score mapping (only present when gates pass)"
    )


class BacktestResultsSchemaV4(BaseModel):
    """
    Backtest results schema - contract between backtest engine and downstream consumers.

    Version: 4.0
    Updated: 2026-01-15

    Breaking changes from v3.0:
    - Renamed sharpe_ratio -> sharpe_ratio_annual
    - Added trade_analyzer_details nested structure
    - Standardized field naming conventions
    """
    model_config = ConfigDict(extra='allow')  # Forward compatibility

    # METADATA
    schema_version: str = Field(
        default='4.0',
        description="Schema version for migration support"
    )
    run_timestamp: str = Field(
        description="ISO format timestamp of backtest run"
    )
    run_context: str = Field(
        default="best_trial",
        description="Context: best_trial, optimization, manual"
    )

    # MARKET METADATA
    market: str = Field(description="Market code: SHFE, CRYPTO, CME")
    instrument: Optional[str] = Field(None, description="Instrument name (e.g., 'aluminum', 'bitcoin')")
    instrument_code: Optional[str] = Field(None, description="Instrument code (e.g., 'al', 'btc')")

    # PERFORMANCE METRICS (REQUIRED)
    performance_metrics: PerformanceMetricsSchema

    # STRATEGY PARAMETERS
    strategy_parameters: Dict[str, Any] = Field(default_factory=dict)

    # WFA FIELDS (Optional - present when WFA_ENABLED)
    wfa_summary: Optional[WFASummarySchema] = Field(
        default=None,
        description="Walk-Forward Analysis aggregate metrics"
    )
    wfa_windows: Optional[List[WFAWindowDetailSchema]] = Field(
        default=None,
        description="Per-window WFA details"
    )

    # DRS (Optional - computed after WFA)
    drs: Optional[DRSSchema] = Field(
        default=None,
        description="Deployment Readiness Score (0-100) from OOS metrics"
    )


# =============================================================================
# TRADE LOG SCHEMA (was trade_log.py, v1.1 frequency-adaptive)
# =============================================================================

class TradeRecordSchema(BaseModel):
    """
    Schema for a single trade record in backtest_trades.csv (30 columns).

    Frequency-Adaptive Validation:
    - INTERDAY: entry_time/exit_time are date-only, session fields are None
    - INTRADAY: entry_time/exit_time are full datetime, session fields required
    """
    model_config = ConfigDict(extra='allow')  # Forward compatibility

    # REQUIRED FIELDS - Entry/Exit Basic Info
    entry_date: date = Field(description="Entry date (YYYY-MM-DD)")
    exit_date: date = Field(description="Exit date (YYYY-MM-DD)")

    entry_time: Optional[datetime] = Field(
        None,
        description="Entry datetime. INTERDAY: date at midnight. INTRADAY: full datetime."
    )
    exit_time: Optional[datetime] = Field(
        None,
        description="Exit datetime. INTERDAY: date at midnight or None. INTRADAY: full datetime."
    )

    direction: Literal['long', 'short'] = Field(description="Trade direction")
    size: float = Field(gt=0, description="Position size (contracts/shares)")

    entry_price: float = Field(gt=0, description="Entry price")
    exit_price: float = Field(gt=0, description="Exit price")

    # REQUIRED FIELDS - PnL Metrics
    pnl: float = Field(description="Profit/Loss before commission")
    commission: float = Field(ge=0, description="Total commission paid")
    pnlcomm: float = Field(description="Net PnL after commission")
    return_pct: float = Field(description="Return percentage")

    exit_reason: Optional[str] = Field(
        None,
        description="Why trade was exited (strategy_exit, stop_loss, etc.)"
    )

    # CONDITIONAL FIELDS - Frequency Dependent
    # INTERDAY ONLY (TRS-paradigm: regime label populated; other paradigms may leave None)
    entry_regime: Optional[str] = Field(
        None,
        description=(
            "TRS-paradigm: market regime label at entry execution date. Other "
            "paradigms (TSMOM, etc.) typically leave None."
        )
    )
    decision_regime: Optional[str] = Field(
        None,
        description=(
            "TRS-paradigm: market regime label at signal generation date "
            "(previous trading day). Other paradigms typically leave None."
        )
    )

    # INTRADAY ONLY - All optional to support interday
    entry_session_phase: Optional[str] = Field(
        None,
        description="Session phase at entry (night, morning, afternoon). INTRADAY only."
    )
    entry_session_type: Optional[str] = Field(
        None,
        description="Session type (day, night). INTRADAY only."
    )
    session_id: Optional[str] = Field(
        None,
        description="Session identifier (YYYY-MM-DD_day). INTRADAY only."
    )
    entry_bar_of_session: Optional[int] = Field(
        None,
        ge=0,
        description="Bar number at entry within session. INTRADAY only."
    )
    exit_bar_of_session: Optional[int] = Field(
        None,
        ge=0,
        description="Bar number at exit within session. INTRADAY only."
    )
    total_bars_in_session: Optional[int] = Field(
        None,
        ge=0,
        description="Total bars in the session. INTRADAY only."
    )

    # OPTIONAL FIELDS - MFE/MAE Metrics
    mfe_points: Optional[float] = Field(None, description="Maximum Favorable Excursion in price points")
    mae_points: Optional[float] = Field(None, description="Maximum Adverse Excursion in price points (negative value)")
    mfe_pct: Optional[float] = Field(None, description="MFE as percentage of entry price")
    mae_pct: Optional[float] = Field(None, description="MAE as percentage of entry price (negative value)")
    mfe_currency: Optional[float] = Field(None, description="MFE in currency terms")
    mae_currency: Optional[float] = Field(None, description="MAE in currency terms (negative value)")

    # OPTIONAL FIELDS - Profit Capture Metrics
    profit_capture_rate: Optional[float] = Field(None, description="Percentage of MFE captured as actual profit")
    profit_left_on_table: Optional[float] = Field(None, description="Unrealized profit from MFE peak to exit")

    # OPTIONAL FIELDS - Entry Quality Metrics
    entry_drawdown_points: Optional[float] = Field(None, description="Drawdown from entry to MAE in points")
    entry_quality_score: Optional[float] = Field(None, description="Quality score for entry timing")

    # OPTIONAL FIELDS - Contract Info
    entry_contract: Optional[str] = Field(None, description="Contract code at entry (e.g., cu2303)")
    price_correction: Optional[float] = Field(None, description="Price correction applied")
    pnl_correction: Optional[float] = Field(None, description="PnL correction applied")

    # VALIDATORS
    @field_validator('entry_date', 'exit_date', mode='before')
    @classmethod
    def parse_dates(cls, v):
        """Parse date strings to date objects."""
        if isinstance(v, str):
            return datetime.strptime(v, '%Y-%m-%d').date()
        if isinstance(v, date):
            return v
        return v

    @field_validator('entry_time', 'exit_time', mode='before')
    @classmethod
    def parse_datetimes(cls, v):
        """Parse datetime strings to datetime objects.

        Frequency-adaptive:
        - INTERDAY: Date-only string 'YYYY-MM-DD' -> datetime at midnight
        - INTRADAY: Full datetime 'YYYY-MM-DD HH:MM:SS' -> datetime
        - NaN/None/empty -> None
        """
        if _is_nan(v):
            return None
        if isinstance(v, datetime):
            return v
        if isinstance(v, str):
            if len(v) > 10:
                return datetime.strptime(v, '%Y-%m-%d %H:%M:%S')
            return datetime.strptime(v, '%Y-%m-%d')
        return v

    @field_validator(
        'entry_session_phase', 'entry_session_type', 'session_id',
        'entry_regime', 'decision_regime', 'exit_reason', 'entry_contract',
        mode='before'
    )
    @classmethod
    def parse_optional_strings(cls, v):
        """Convert NaN to None for optional string fields."""
        if _is_nan(v):
            return None
        return str(v) if v is not None else None

    @field_validator(
        'entry_bar_of_session', 'exit_bar_of_session', 'total_bars_in_session',
        mode='before'
    )
    @classmethod
    def parse_optional_ints(cls, v):
        """Convert NaN to None for optional integer fields."""
        if _is_nan(v):
            return None
        if isinstance(v, float):
            return int(v)
        return v

    @field_validator(
        'mfe_points', 'mae_points', 'mfe_pct', 'mae_pct',
        'mfe_currency', 'mae_currency',
        'profit_capture_rate', 'profit_left_on_table',
        'entry_drawdown_points', 'entry_quality_score',
        'price_correction', 'pnl_correction',
        mode='before'
    )
    @classmethod
    def parse_optional_floats(cls, v):
        """Convert NaN to None for optional float fields."""
        if _is_nan(v):
            return None
        return v


def validate_trade_log_dataframe(
    df_dict_records: List[dict],
    frequency: str = "interday"
) -> List[TradeRecordSchema]:
    """
    Validate entire trade log DataFrame with frequency-adaptive rules.
    """
    validated_trades = []
    errors = []
    is_intraday = frequency.lower() == 'intraday'

    for idx, record in enumerate(df_dict_records):
        try:
            validated = TradeRecordSchema(**record)

            if is_intraday:
                missing_session = []
                if validated.entry_session_phase is None:
                    missing_session.append('entry_session_phase')
                if validated.session_id is None:
                    missing_session.append('session_id')
                if missing_session:
                    errors.append(
                        f"Row {idx}: INTRADAY requires session fields: {missing_session}"
                    )
                    continue
            else:
                pass

            validated_trades.append(validated)
        except Exception as e:
            errors.append(f"Row {idx}: {e}")

    if errors:
        error_msg = f"Trade log validation failed for {len(errors)} / {len(df_dict_records)} trades:\n"
        error_msg += "\n".join(errors[:10])
        if len(errors) > 10:
            error_msg += f"\n... and {len(errors) - 10} more errors"
        raise ValueError(error_msg)

    return validated_trades


def validate_trades_dict_list(
    trades: List[dict],
    frequency: str = "interday"
) -> List[dict]:
    """Validate trades and return as list of dicts (for DataFrame construction)."""
    validated = validate_trade_log_dataframe(trades, frequency=frequency)
    return [trade.model_dump() for trade in validated]


# =============================================================================
# STRATEGY LOG SCHEMA (was strategy_log.py, v1.0)
# =============================================================================

class StrategyLogRecordSchema(BaseModel):
    """
    Schema for a single bar's strategy decision record.

    Captures the complete decision flow for one bar:
    1. Entry evaluation -> 2. Exit evaluation -> 3. Sizing -> 4. Risk check -> 5. Order -> 6. Execution
    """
    model_config = ConfigDict(extra='allow')

    # BAR METADATA
    datetime: dt = Field(description="Bar datetime (YYYY-MM-DD HH:MM:SS format)")
    bar_count: int = Field(ge=1, description="Sequential bar number from start of backtest")

    # ENTRY SIGNAL COMPONENT
    entry_signal: Literal['HOLD', 'LONG', 'SHORT'] = Field(
        description="Entry signal output: HOLD (no entry), LONG, or SHORT"
    )
    entry_strength: float = Field(
        ge=0.0, le=1.0, description="Signal strength/confidence (0.0 to 1.0)"
    )
    entry_type: Optional[str] = Field(
        None, description="Entry type: 'hold', 'entry_long', 'entry_short', or None"
    )
    entry_reason: str = Field(description="Human-readable explanation of entry decision")
    entry_regime: Optional[str] = Field(
        None,
        description=(
            "Optional context label at entry evaluation. TRS strategies "
            "populate with market regime; intraday strategies may populate "
            "with session phase. TSMOM strategies typically leave None."
        )
    )

    # EXIT SIGNAL COMPONENT
    exit_should_exit: bool = Field(description="Whether exit signal triggered")
    exit_reason: str = Field(description="Exit reason or 'No position to exit'")
    exit_position_size: float = Field(ge=0.0, description="Current position size for exit evaluation")
    exit_bars_since_entry: int = Field(ge=0, description="Bars held since entry (0 if no position)")

    # POSITION SIZING COMPONENT
    sizing_calculated_size: float = Field(ge=0.0, description="Final calculated position size")
    sizing_raw_size: float = Field(ge=0.0, description="Raw size before adjustments")
    sizing_signal_direction: Literal['HOLD', 'LONG', 'SHORT'] = Field(
        description="Direction for sizing calculation"
    )
    sizing_reason: str = Field(description="Sizing calculation explanation")

    # RISK MANAGEMENT COMPONENT
    risk_trading_allowed: bool = Field(description="Whether trading is allowed by risk manager")
    risk_reason: str = Field(description="Risk check result explanation")

    # ORDER MANAGEMENT
    order_action: Optional[str] = Field(None, description="Order action: 'submit' or None")
    order_side: Optional[str] = Field(None, description="Order side (buy/sell indicator)")
    order_size: float = Field(ge=0.0, description="Order size submitted")
    order_status: Optional[str] = Field(None, description="Order status")
    order_ref: Optional[str] = Field(None, description="Order reference ID")
    order_executed: bool = Field(description="Whether order was executed")

    # EXECUTION DETAILS
    execution_date: Optional[dt] = Field(None, description="Execution datetime (nullable)")
    execution_price: float = Field(ge=0.0, description="Execution price")
    execution_size: float = Field(ge=0.0, description="Executed size")

    # FORCED EXIT
    is_forced_exit: bool = Field(
        description="Whether this was a forced exit (contract expiry, session end)"
    )
    forced_exit_reason: Optional[str] = Field(None, description="Forced exit reason (nullable)")

    @model_validator(mode='before')
    @classmethod
    def convert_nan_to_none(cls, values):
        """Convert NaN values to None for proper Optional field handling."""
        if isinstance(values, dict):
            for key, value in values.items():
                if isinstance(value, float):
                    try:
                        if isnan(value):
                            values[key] = None
                    except (TypeError, ValueError):
                        pass
        return values

    @field_validator('datetime', mode='before')
    @classmethod
    def parse_datetime(cls, v):
        """Parse datetime string to datetime object."""
        if isinstance(v, dt):
            return v
        if isinstance(v, str):
            if len(v) > 10:
                return dt.strptime(v, '%Y-%m-%d %H:%M:%S')
            return dt.strptime(v, '%Y-%m-%d')
        return v

    @field_validator('execution_date', mode='before')
    @classmethod
    def parse_execution_date(cls, v):
        """Parse execution_date, handling empty strings, NaN, and datetime strings."""
        if v is None or v == '':
            return None
        if isinstance(v, float) and isnan(v):
            return None
        if isinstance(v, dt):
            return v
        if isinstance(v, str):
            if len(v) > 10:
                return dt.strptime(v, '%Y-%m-%d %H:%M:%S')
            return dt.strptime(v, '%Y-%m-%d')
        return v


def validate_strategy_log_dataframe(df_dict_records: list[dict]) -> list[StrategyLogRecordSchema]:
    """Validate entire strategy log DataFrame."""
    validated_records = []
    errors = []

    for idx, record in enumerate(df_dict_records):
        try:
            validated = StrategyLogRecordSchema(**record)
            validated_records.append(validated)
        except Exception as e:
            errors.append(f"Row {idx}: {e}")

    if errors:
        error_msg = f"Strategy log validation failed for {len(errors)} / {len(df_dict_records)} records:\n"
        error_msg += "\n".join(errors[:10])
        if len(errors) > 10:
            error_msg += f"\n... and {len(errors) - 10} more errors"
        raise ValueError(error_msg)

    return validated_records


def validate_strategy_log_dict_list(records: list[dict]) -> list[dict]:
    """Validate strategy log records and return as list of dicts."""
    validated = validate_strategy_log_dataframe(records)
    return [record.model_dump() for record in validated]


# =============================================================================
# SELECTED TRIAL SCHEMA (was selected_trial.py, v1.0)
# =============================================================================

class TrialMetricsSchema(BaseModel):
    """Performance metrics for the selected trial."""
    model_config = ConfigDict(extra='allow')  # Allow additional metrics

    sharpe_ratio: float = Field(description="Sharpe ratio of the trial")
    annual_return: float = Field(description="Annualized return percentage")
    max_drawdown_pct: float = Field(
        description="Maximum drawdown percentage (negative value)"
    )


class SelectedTrialSchema(BaseModel):
    """
    Schema for selected_robust_trial.json.

    This file contains the trial selected from Optuna optimization based on
    robustness analysis (cluster stability, parameter stability).
    """
    model_config = ConfigDict(extra='allow')  # Forward compatibility

    # TRIAL IDENTIFICATION
    trial_number: int = Field(ge=0, description="Optuna trial number")
    selection_reason: str = Field(description="Reason for selecting this trial")

    # CLUSTER ANALYSIS
    cluster_id: int = Field(ge=0, description="Parameter cluster ID from robustness analysis")
    cluster_robustness_score: float = Field(description="Robustness score of the cluster (-1 to 1)")
    parameter_stability_score: float = Field(
        ge=0.0, le=1.0, description="Parameter stability score (0 to 1)"
    )

    # PERFORMANCE METRICS
    metrics: TrialMetricsSchema = Field(description="Performance metrics for this trial")

    # STRATEGY PARAMETERS
    params: Dict[str, Any] = Field(
        default_factory=dict,
        description="Optimized strategy parameters (variable keys)"
    )

    # PARAMETER CLASSIFICATIONS
    param_classifications: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Parameter FIXED/FLOAT/INT classifications from StrategyParameterFramework"
    )

    def get_param(self, key: str, default: Any = None) -> Any:
        """Get a parameter value with optional default."""
        return self.params.get(key, default)

    def get_period_params(self) -> Dict[str, int]:
        """Extract all period parameters from params."""
        period_mapping = {}
        for key, value in self.params.items():
            if key.endswith('_period') and isinstance(value, (int, float)):
                parts = key.replace('_period', '').split('_')
                if len(parts) >= 2:
                    indicator_name = parts[-1]
                    period_mapping[indicator_name] = int(value)
        return period_mapping
