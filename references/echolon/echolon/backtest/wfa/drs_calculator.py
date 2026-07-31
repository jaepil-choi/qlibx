"""
Deployment Readiness Score (DRS) Calculator.

Computes a 0-100 composite score measuring how ready a strategy is for live
deployment, structured as **constrained return maximization**:

    PRIMARY:    Annual return >= target  -> return components (40 pts)
    CONSTRAINT: Max DD <= target         -> risk component   (10 pts)
    QUALIFIER:  Robust across all periods -> robustness      (35 pts)
    QUALITY:    Parameter confidence      -> quality          (8 pts)
    BONUS:      Gate margin               -> bonus            (7 pts)

Components (100 points total):
    1. OOS Return           (25 pts) — recency-weighted OOS annual return vs target
    2. Return Level         (15 pts) — full-sample annual return vs target
    3. OOS Edge             (20 pts) — uniform-weighted OOS Sharpe with worst-window penalty
    4. Temporal Stability   (15 pts) — year-over-year consistency from full-sample
    5. OOS Risk             (10 pts) — worst OOS drawdown containment
    6. Parameter Confidence  (8 pts) — deployed parameter reliability
    7. Gate Bonus            (7 pts) — margin above hard gate thresholds

Hard Gates (must all pass, or DRS = 0):
    G1: No OOS window Sharpe < -0.5         (survive ANY period)
    G2: Mean OOS trades/window >= threshold  (statistical reliability)
    G3: Majority of windows positive Sharpe  (consistency floor)
    G4: Full-sample Sharpe > 0.5             (sanity floor)
    G5: No OOS window DD exceeds hard limit  (risk containment)
    G6: No calendar year return < -5%        (no catastrophic year)
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION
# =============================================================================

@dataclass
class DRSConfig:
    """Configuration for DRS calculation thresholds and weights."""

    # --- Hard Gate Thresholds ---
    min_any_window_oos_sharpe: float = -0.5         # G1: no window below this
    min_mean_oos_trades: int = 5                     # G2: mean OOS trades/window
    min_positive_window_fraction: float = 0.6        # G3: fraction of positive windows
    min_full_sample_sharpe: float = 0.5              # G4: full-sample Sharpe floor
    max_oos_dd_pct: float = 16.0                     # G5: max OOS DD hard limit
    min_calendar_year_return_pct: float = -5.0       # G6: no year worse than this

    # --- Component: OOS Return (25 pts) ---
    # Weights ordered most-recent-first: [W_last, W_last-1, ..., W_first]
    oos_return_recency_weights: List[float] = field(
        default_factory=lambda: [0.30, 0.25, 0.20, 0.15, 0.10]
    )
    annual_return_target_pct: float = 40.0           # ceiling for return scoring

    # --- Component: OOS Edge (20 pts) ---
    max_oos_sharpe_for_scoring: float = 2.0          # Sharpe ceiling for scoring
    trade_count_normalizer: int = 10                 # trade reliability discount

    # --- Component: Temporal Stability (15 pts) ---
    min_year_return_pct_for_bonus: float = -3.0      # sub-score 3: bonus if all years above

    # --- Component: OOS Risk (10 pts) ---
    oos_dd_floor_pct: float = 8.0   # DD <= this -> full points
    oos_dd_ceiling_pct: float = 15.0  # DD >= this -> 0 points

    # --- Component: Parameter Confidence (8 pts) ---
    cv_excellent: float = 0.15  # mean CV <= this -> full points
    cv_poor: float = 0.45       # mean CV >= this -> 0 points
    excluded_cv_params: List[str] = field(
        default_factory=lambda: ["risk_drawdown_halt_pct"]
    )
    cv_instability_threshold: float = 2.0  # CVs above this excluded as degenerate

    @classmethod
    def from_target_params(
        cls,
        sharpe_target: Optional[float] = None,
        max_drawdown_target: Optional[float] = None,
        annual_return_target: Optional[float] = None,
        trades_per_week_target_min: Optional[float] = None,
    ) -> "DRSConfig":
        """Build target-calibrated :class:`DRSConfig` from raw target values.

        Takes plain floats so any host project can call this without a
        schema type — decoupling the scoring library from any host app's
        workflow types.

        Args:
            sharpe_target: Annual Sharpe target (e.g., 2.0). Defaults to 2.0.
            max_drawdown_target: Max drawdown pct (e.g., 15.0 for 15%). Defaults to 15.0.
            annual_return_target: Annual return pct (e.g., 25.0). Defaults to 40.0.
            trades_per_week_target_min: Minimum trades per week target, if any.
                When provided, scales gate thresholds by the implied annual trade count.
        """
        sharpe_target = sharpe_target if sharpe_target is not None else 2.0
        max_dd_target = max_drawdown_target if max_drawdown_target is not None else 15.0
        annual_return = annual_return_target if annual_return_target is not None else 40.0

        if trades_per_week_target_min and trades_per_week_target_min > 0:
            expected_oos_trades = trades_per_week_target_min * 52
            min_mean_oos_trades = max(5, int(expected_oos_trades * 0.15))
            trade_count_normalizer = max(10, int(expected_oos_trades * 0.5))
        else:
            min_mean_oos_trades = 5
            trade_count_normalizer = 10

        return cls(
            # Gates
            min_any_window_oos_sharpe=-0.5,
            min_full_sample_sharpe=max(0.5, sharpe_target * 0.25),
            max_oos_dd_pct=max_dd_target + 1.0,
            min_mean_oos_trades=min_mean_oos_trades,
            min_calendar_year_return_pct=-5.0,
            # Components
            annual_return_target_pct=annual_return,
            max_oos_sharpe_for_scoring=sharpe_target,
            trade_count_normalizer=trade_count_normalizer,
            oos_dd_floor_pct=max_dd_target * 0.5,
            oos_dd_ceiling_pct=max_dd_target,
        )

# =============================================================================
# RESULT TYPES
# =============================================================================

@dataclass
class GateResult:
    """Result of a single hard gate check."""
    gate_id: str
    passed: bool
    value: float
    threshold: float
    description: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "gate_id": self.gate_id,
            "passed": self.passed,
            "value": round(self.value, 4),
            "threshold": round(self.threshold, 4),
            "description": self.description,
        }


@dataclass
class ComponentScore:
    """Score for a single DRS component."""
    name: str
    score: float
    max_score: float
    details: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "score": round(self.score, 1),
            "max_score": self.max_score,
            "details": {k: round(v, 4) if isinstance(v, float) else v
                        for k, v in self.details.items()},
        }


@dataclass
class DRSResult:
    """Complete DRS calculation result."""
    drs_score: float
    gates_passed: bool
    gate_results: List[GateResult]
    components: List[ComponentScore]
    weighted_oos_annual_return_pct: float
    calibration: Dict[str, Any] = field(default_factory=dict)

    @property
    def component_breakdown(self) -> Dict[str, float]:
        """Component name -> score mapping."""
        return {c.name: c.score for c in self.components}

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to JSON-compatible dict for backtest_results.json."""
        result = {
            "drs_score": round(self.drs_score, 1),
            "gates_passed": self.gates_passed,
            "weighted_oos_annual_return_pct": round(self.weighted_oos_annual_return_pct, 2),
            "gate_results": [g.to_dict() for g in self.gate_results],
        }
        if self.components:
            result["components"] = [c.to_dict() for c in self.components]
            result["component_breakdown"] = {
                c.name: round(c.score, 1) for c in self.components
            }
        if self.calibration:
            result["calibration"] = self.calibration
        return result


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

def compute_drs(
    backtest_results: Dict[str, Any],
    config: DRSConfig = None,
) -> DRSResult:
    """
    Compute Deployment Readiness Score from backtest results.

    Args:
        backtest_results: Dict containing performance_metrics, wfa_summary,
            and wfa_windows (as produced by WFARunner._build_final_results).
        config: DRS configuration. Uses defaults if not provided.

    Returns:
        DRSResult with score, gate results, and component breakdown.
    """
    if config is None:
        config = DRSConfig()

    perf_metrics = backtest_results['performance_metrics']
    wfa_summary = backtest_results['wfa_summary']
    wfa_windows = backtest_results['wfa_windows']

    # Sort windows by window_id ascending (W1=oldest, WN=most recent)
    wfa_windows = sorted(wfa_windows, key=lambda w: w['window_id'])

    # --- Hard Gates ---
    gate_results = _check_gates(perf_metrics, wfa_summary, wfa_windows, config)
    gates_passed = all(g.passed for g in gate_results)

    calibration = {
        "sharpe_target": config.max_oos_sharpe_for_scoring,
        "max_dd_target_pct": config.oos_dd_ceiling_pct,
        "annual_return_target_pct": config.annual_return_target_pct,
        "min_mean_oos_trades": config.min_mean_oos_trades,
        "trade_count_normalizer": config.trade_count_normalizer,
    }

    if not gates_passed:
        failed = [g for g in gate_results if not g.passed]
        logger.info(
            f"DRS=0 (gates failed: "
            f"{[f'{g.gate_id}: {g.description}' for g in failed]})"
        )
        return DRSResult(
            drs_score=0.0,
            gates_passed=False,
            gate_results=gate_results,
            components=[],
            weighted_oos_annual_return_pct=0.0,
            calibration=calibration,
        )

    # --- Component 1: OOS Return (25 pts) ---
    score_1, weighted_ret, details_1 = _compute_oos_return(wfa_windows, config)
    comp_1 = ComponentScore("oos_return", score_1, 25.0, details_1)

    # --- Component 2: Return Level (15 pts) ---
    score_2, details_2 = _compute_return_level(perf_metrics, config)
    comp_2 = ComponentScore("return_level", score_2, 15.0, details_2)

    # --- Component 3: OOS Edge (20 pts) ---
    score_3, details_3 = _compute_oos_edge(wfa_windows, config)
    comp_3 = ComponentScore("oos_edge", score_3, 20.0, details_3)

    # --- Component 4: Temporal Stability (15 pts) ---
    score_4, details_4 = _compute_temporal_stability(perf_metrics, config)
    comp_4 = ComponentScore("temporal_stability", score_4, 15.0, details_4)

    # --- Component 5: OOS Risk Containment (10 pts) ---
    score_5, details_5 = _compute_oos_risk(wfa_windows, config)
    comp_5 = ComponentScore("oos_risk", score_5, 10.0, details_5)

    # --- Component 6: Parameter Confidence (8 pts) ---
    score_6, details_6 = _compute_param_confidence(wfa_summary, config)
    comp_6 = ComponentScore("param_confidence", score_6, 8.0, details_6)

    # --- Component 7: Gate Bonus (7 pts) ---
    score_7, details_7 = _compute_gate_bonus(gate_results)
    comp_7 = ComponentScore("gate_bonus", score_7, 7.0, details_7)

    components = [comp_1, comp_2, comp_3, comp_4, comp_5, comp_6, comp_7]
    drs_score = round(sum(c.score for c in components), 1)

    # Add target-relative metric to calibration
    calibration["oos_return_vs_target_pct"] = round(
        weighted_ret / config.annual_return_target_pct * 100, 1
    ) if config.annual_return_target_pct > 0 else 0.0

    logger.info(
        f"DRS={drs_score:.1f} "
        f"[OOSReturn={score_1:.1f}/25, RetLevel={score_2:.1f}/15, "
        f"Edge={score_3:.1f}/20, Stability={score_4:.1f}/15, "
        f"Risk={score_5:.1f}/10, Params={score_6:.1f}/8, Bonus={score_7:.1f}/7]"
    )

    return DRSResult(
        drs_score=drs_score,
        gates_passed=True,
        gate_results=gate_results,
        components=components,
        weighted_oos_annual_return_pct=weighted_ret,
        calibration=calibration,
    )


# =============================================================================
# HARD GATES
# =============================================================================

def _check_gates(
    perf_metrics: Dict[str, Any],
    wfa_summary: Dict[str, Any],
    wfa_windows: List[Dict[str, Any]],
    config: DRSConfig,
) -> List[GateResult]:
    """Evaluate all hard gates. All must pass for DRS > 0."""
    gates = []

    # G1: No OOS window Sharpe < -0.5 (checks ALL windows)
    worst_window_sharpe = min(
        w['oos_metrics']['sharpe_ratio_annual'] for w in wfa_windows
    )
    gates.append(GateResult(
        gate_id="G1",
        passed=worst_window_sharpe >= config.min_any_window_oos_sharpe,
        value=worst_window_sharpe,
        threshold=config.min_any_window_oos_sharpe,
        description=(
            f"Worst window OOS Sharpe {worst_window_sharpe:.3f} "
            f"{'>=' if worst_window_sharpe >= config.min_any_window_oos_sharpe else '<'} "
            f"{config.min_any_window_oos_sharpe}"
        ),
    ))

    # G2: Mean OOS trades across all windows >= minimum (statistical reliability)
    mean_oos_trades = sum(
        w['oos_metrics']['total_trades'] for w in wfa_windows
    ) / len(wfa_windows)
    gates.append(GateResult(
        gate_id="G2",
        passed=mean_oos_trades >= config.min_mean_oos_trades,
        value=mean_oos_trades,
        threshold=float(config.min_mean_oos_trades),
        description=(
            f"Mean OOS trades/window {mean_oos_trades:.1f} "
            f"{'>=' if mean_oos_trades >= config.min_mean_oos_trades else '<'} "
            f"{config.min_mean_oos_trades}"
        ),
    ))

    # G3: Majority of windows have positive OOS Sharpe
    total_windows = wfa_summary['total_windows']
    positive_windows = wfa_summary['windows_positive_oos']
    positive_fraction = positive_windows / total_windows if total_windows > 0 else 0.0
    gates.append(GateResult(
        gate_id="G3",
        passed=positive_fraction >= config.min_positive_window_fraction,
        value=positive_fraction,
        threshold=config.min_positive_window_fraction,
        description=(
            f"Positive OOS windows {positive_windows}/{total_windows} "
            f"({positive_fraction:.0%}) "
            f"{'>=' if positive_fraction >= config.min_positive_window_fraction else '<'} "
            f"{config.min_positive_window_fraction:.0%}"
        ),
    ))

    # G4: Full-sample Sharpe > sanity floor
    full_sharpe = perf_metrics['sharpe_ratio_annual']
    gates.append(GateResult(
        gate_id="G4",
        passed=full_sharpe > config.min_full_sample_sharpe,
        value=full_sharpe,
        threshold=config.min_full_sample_sharpe,
        description=(
            f"Full-sample Sharpe {full_sharpe:.3f} "
            f"{'>' if full_sharpe > config.min_full_sample_sharpe else '<='} "
            f"{config.min_full_sample_sharpe}"
        ),
    ))

    # G5: No OOS window DD exceeds hard limit
    max_oos_dd = max(
        w['oos_metrics']['max_drawdown_pct'] for w in wfa_windows
    )
    gates.append(GateResult(
        gate_id="G5",
        passed=max_oos_dd <= config.max_oos_dd_pct,
        value=max_oos_dd,
        threshold=config.max_oos_dd_pct,
        description=(
            f"Max OOS DD {max_oos_dd:.2f}% "
            f"{'<=' if max_oos_dd <= config.max_oos_dd_pct else '>'} "
            f"{config.max_oos_dd_pct}%"
        ),
    ))

    # G6: No calendar year return < -5%
    annual_returns = perf_metrics.get('annual_returns', {})
    if annual_returns:
        worst_year_return = min(annual_returns.values())
        gates.append(GateResult(
            gate_id="G6",
            passed=worst_year_return >= config.min_calendar_year_return_pct,
            value=worst_year_return,
            threshold=config.min_calendar_year_return_pct,
            description=(
                f"Worst calendar year return {worst_year_return:.2f}% "
                f"{'>=' if worst_year_return >= config.min_calendar_year_return_pct else '<'} "
                f"{config.min_calendar_year_return_pct}%"
            ),
        ))
    else:
        # Skip G6 when the WFA window is too short to have annual returns —
        # treat as a non-applicable gate rather than a failure.
        gates.append(GateResult(
            gate_id="G6",
            passed=True,
            value=0.0,
            threshold=config.min_calendar_year_return_pct,
            description="G6 skipped: annual_returns data not available",
        ))

    return gates


# =============================================================================
# COMPONENT CALCULATORS
# =============================================================================

def _compute_oos_return(
    wfa_windows: List[Dict[str, Any]],
    config: DRSConfig,
) -> tuple:
    """
    Component 1: Recency-Weighted OOS Return (25 points max).

    Recency-weighted mean of per-window OOS annual returns, scored against
    the annual return target.

    Returns:
        (score, weighted_annual_return, details_dict)
    """
    n_windows = len(wfa_windows)

    # Build base weights: recency_weights[0] = most recent window
    # wfa_windows[0] = oldest, wfa_windows[-1] = most recent -> reverse
    base_weights = config.oos_return_recency_weights[:n_windows]
    if len(base_weights) < n_windows:
        base_weights.extend([0.05] * (n_windows - len(base_weights)))
    base_weights = list(reversed(base_weights))  # align: [0]=oldest

    # Normalize weights to sum to 1.0
    weight_sum = sum(base_weights)
    if weight_sum <= 0:
        return 0.0, 0.0, {"note": "no valid weights"}
    weights = [w / weight_sum for w in base_weights]

    # Compute per-window annual return
    window_annual_returns = []
    for w in wfa_windows:
        oos_years = w.get('oos_years', 1.0)
        total_return = w['oos_metrics']['total_return_pct']
        ann_return = total_return / oos_years if oos_years > 0 else 0.0
        window_annual_returns.append(ann_return)

    # Weighted mean
    weighted_return = sum(
        weights[i] * window_annual_returns[i] for i in range(n_windows)
    )

    # Linear scoring: return >= target -> 25 pts, return <= 0 -> 0 pts
    target = config.annual_return_target_pct
    if target <= 0:
        score = 25.0 if weighted_return > 0 else 0.0
    else:
        score = 25.0 * max(0.0, min(weighted_return / target, 1.0))

    details = {
        "weighted_oos_annual_return_pct": round(weighted_return, 2),
        "target_annual_return_pct": target,
        "per_window_annual_returns": [round(r, 2) for r in window_annual_returns],
        "recency_weights_applied": [round(w, 4) for w in weights],
    }

    return round(score, 1), round(weighted_return, 2), details


def _compute_return_level(
    perf_metrics: Dict[str, Any],
    config: DRSConfig,
) -> tuple:
    """
    Component 2: Full-Sample Return Level (15 points max).

    Full-sample average annual return scored against the annual return target.

    Returns:
        (score, details_dict)
    """
    avg_annual = perf_metrics.get('average_annual_return_pct', 0.0) or 0.0
    target = config.annual_return_target_pct

    if target <= 0:
        score = 15.0 if avg_annual > 0 else 0.0
    else:
        score = 15.0 * max(0.0, min(avg_annual / target, 1.0))

    details = {
        "average_annual_return_pct": round(avg_annual, 2),
        "target_annual_return_pct": target,
    }

    return round(score, 1), details


def _compute_oos_edge(
    wfa_windows: List[Dict[str, Any]],
    config: DRSConfig,
) -> tuple:
    """
    Component 3: Uniform-Weighted OOS Sharpe Edge (20 points max).

    Uniform mean of all OOS window Sharpe ratios with a penalty applied
    when the worst window has negative Sharpe.

    Returns:
        (score, details_dict)
    """
    n_windows = len(wfa_windows)

    sharpe_values = [w['oos_metrics']['sharpe_ratio_annual'] for w in wfa_windows]
    uniform_mean = sum(sharpe_values) / n_windows
    worst_sharpe = min(sharpe_values)

    # Penalty if worst window < 0: factor ranges from 0.5 (worst=-0.5) to 1.0 (worst=0)
    if worst_sharpe < 0:
        penalty_factor = max(0.5, 1.0 + worst_sharpe)
    else:
        penalty_factor = 1.0

    adjusted_sharpe = uniform_mean * penalty_factor

    # Linear scoring: Sharpe >= target -> 20 pts
    target = config.max_oos_sharpe_for_scoring
    score = 20.0 * max(0.0, min(adjusted_sharpe / target, 1.0))

    details = {
        "uniform_mean_oos_sharpe": round(uniform_mean, 4),
        "worst_window_sharpe": round(worst_sharpe, 4),
        "penalty_factor": round(penalty_factor, 4),
        "adjusted_sharpe": round(adjusted_sharpe, 4),
    }

    return round(score, 1), details


def _compute_temporal_stability(
    perf_metrics: Dict[str, Any],
    config: DRSConfig,
) -> tuple:
    """
    Component 4: Temporal Stability (15 points max).

    Year-over-year consistency from full-sample annual returns.
    Sub-scores:
        1. Fraction of positive years (8 pts)
        2. Low annual return CV (4 pts)
        3. No year below threshold (3 pts bonus)

    Returns:
        (score, details_dict)
    """
    annual_returns = perf_metrics.get('annual_returns', {})

    if not annual_returns or len(annual_returns) < 2:
        return 0.0, {"status": "no_annual_returns_data"}

    returns = list(annual_returns.values())
    n_years = len(returns)

    # Sub-score 1: fraction of positive years (8 pts)
    positive_years = sum(1 for r in returns if r > 0)
    frac_positive = positive_years / n_years
    score_positive = 8.0 * frac_positive

    # Sub-score 2: low annual return CV (4 pts)
    mean_ret = sum(returns) / n_years
    annual_return_cv = None
    if mean_ret > 0:
        std_ret = (sum((r - mean_ret) ** 2 for r in returns) / n_years) ** 0.5
        annual_return_cv = std_ret / mean_ret
        # CV <= 0.5 -> 4 pts, CV >= 2.0 -> 0 pts
        score_cv = 4.0 * max(0.0, min((2.0 - annual_return_cv) / 1.5, 1.0))
    else:
        score_cv = 0.0

    # Sub-score 3: no year below threshold (3 pts bonus)
    worst_year = min(returns)
    score_floor = 3.0 if worst_year >= config.min_year_return_pct_for_bonus else 0.0

    total = round(score_positive + score_cv + score_floor, 1)

    details = {
        "n_years": n_years,
        "positive_years": positive_years,
        "frac_positive": round(frac_positive, 4),
        "score_positive_years": round(score_positive, 1),
        "annual_return_cv": round(annual_return_cv, 4) if annual_return_cv is not None else None,
        "score_cv": round(score_cv, 1),
        "worst_year_return_pct": round(worst_year, 2),
        "score_no_bad_year": round(score_floor, 1),
    }

    return total, details


def _compute_oos_risk(
    wfa_windows: List[Dict[str, Any]],
    config: DRSConfig,
) -> tuple:
    """
    Component 5: OOS Risk Containment (10 points max).

    Based on worst-case OOS max drawdown across all windows.
    Linear mapping: DD <= floor -> full pts, DD >= ceiling -> 0 pts.

    Returns:
        (score, details_dict)
    """
    max_pts = 10.0

    max_oos_dd = max(
        w['oos_metrics']['max_drawdown_pct'] for w in wfa_windows
    )

    floor = config.oos_dd_floor_pct
    ceiling = config.oos_dd_ceiling_pct

    if max_oos_dd <= floor:
        score = max_pts
    elif max_oos_dd >= ceiling:
        score = 0.0
    else:
        score = max_pts * (ceiling - max_oos_dd) / (ceiling - floor)

    score = round(max(0.0, score), 1)
    details = {
        "max_oos_dd_pct": round(max_oos_dd, 2),
        "dd_floor_pct": floor,
        "dd_ceiling_pct": ceiling,
    }

    return score, details


def _compute_param_confidence(
    wfa_summary: Dict[str, Any],
    config: DRSConfig,
) -> tuple:
    """
    Component 6: Parameter Confidence (8 points max).

    Based on mean CV of core parameters across WFA windows.
    Excludes fixed parameters (CV=0) and degenerate parameters.

    Returns:
        (score, details_dict)
    """
    max_pts = 8.0

    cv_dict = wfa_summary.get('parameter_stability_cv', {})

    filtered_cvs = []
    excluded_count = 0
    for param, cv in cv_dict.items():
        if param in config.excluded_cv_params:
            excluded_count += 1
            continue
        if cv > config.cv_instability_threshold:
            excluded_count += 1
            continue
        filtered_cvs.append(cv)

    if not filtered_cvs:
        mean_cv = 0.30  # Neutral default when no params to evaluate
    else:
        mean_cv = sum(filtered_cvs) / len(filtered_cvs)

    excellent = config.cv_excellent
    poor = config.cv_poor

    if mean_cv <= excellent:
        score = max_pts
    elif mean_cv >= poor:
        score = 0.0
    else:
        score = max_pts * (poor - mean_cv) / (poor - excellent)

    score = round(max(0.0, score), 1)
    details = {
        "mean_cv": round(mean_cv, 4),
        "params_evaluated": float(len(filtered_cvs)),
        "params_excluded": float(excluded_count),
        "cv_excellent_threshold": excellent,
        "cv_poor_threshold": poor,
    }

    return score, details


def _compute_gate_bonus(
    gate_results: List[GateResult],
) -> tuple:
    """
    Component 7: Gate Bonus (7 points max).

    Rewards strategies that pass gates comfortably rather than barely.
    Average normalized margin above gate thresholds.

    Returns:
        (score, details_dict)
    """
    margins = {}
    for gate in gate_results:
        if not gate.passed:
            return 0.0, {"note": "gates not all passed"}

        # Normalize margin: how far above threshold as fraction of threshold magnitude
        if abs(gate.threshold) > 0.001:
            margin = (gate.value - gate.threshold) / abs(gate.threshold)
        else:
            margin = 1.0 if gate.value > gate.threshold else 0.0
        margins[gate.gate_id] = max(0.0, margin)

    # Average margin, capped at 1.0
    margin_values = list(margins.values())
    avg_margin = min(1.0, sum(margin_values) / len(margin_values)) if margin_values else 0.0
    score = round(7.0 * avg_margin, 1)

    details = {
        "avg_gate_margin": round(avg_margin, 4),
        "per_gate_margins": {k: round(v, 4) for k, v in margins.items()},
    }

    return score, details
