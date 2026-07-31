"""Walk-Forward Analysis metric computation."""

import logging
import numpy as np
from typing import Dict, Any, List

from .window import WFAWindow

logger = logging.getLogger(__name__)


class WalkForwardAnalyzer:
    """Computes WFA aggregate metrics from completed windows."""

    def __init__(self, windows: List[WFAWindow]):
        self.windows = windows

    def _has_trades(self, w: WFAWindow) -> bool:
        """Check if a window produced at least one OOS trade."""
        if not w.oos_results:
            return False
        return w.oos_results.get("total_trades", 0) > 0

    def compute_summary(self) -> Dict[str, Any]:
        """
        Compute WFA summary metrics.

        Zero-trade windows are excluded from WFE and OOS Sharpe aggregates
        because "no trades" is undefined performance, not zero performance.

        Returns dict with:
        - wfe_mean/min/max: Walk Forward Efficiency across traded windows
        - oos_sharpe_mean/std/min: OOS Sharpe distribution (traded windows only)
        - oos_sharpe_consistency: mean/std ratio
        - parameter_stability_cv: CV of optimized parameters across windows
        - degradation_ratios: OOS sharpe ratio between consecutive windows
        - windows_positive_oos: count with OOS sharpe > 0
        - windows_zero_trades: count of windows with no OOS trades
        """
        traded_windows = [w for w in self.windows if self._has_trades(w)]
        zero_trade_count = len(self.windows) - len(traded_windows)

        if zero_trade_count > 0:
            zero_ids = [w.window_id for w in self.windows if not self._has_trades(w)]
            logger.warning(
                f"WFA: {zero_trade_count} window(s) with zero OOS trades "
                f"(windows {zero_ids}) — excluded from aggregates"
            )

        wfe_values = [
            w.walk_forward_efficiency for w in traded_windows
            if w.walk_forward_efficiency is not None
        ]
        oos_sharpes = [
            w.oos_sharpe for w in traded_windows
            if w.oos_sharpe is not None
        ]

        wfe_mean = float(np.mean(wfe_values)) if wfe_values else None
        wfe_min = float(np.min(wfe_values)) if wfe_values else None
        wfe_max = float(np.max(wfe_values)) if wfe_values else None

        oos_sharpe_mean = float(np.mean(oos_sharpes)) if oos_sharpes else None
        oos_sharpe_std = float(np.std(oos_sharpes)) if oos_sharpes else None
        oos_sharpe_min = float(np.min(oos_sharpes)) if oos_sharpes else None

        oos_sharpe_consistency = None
        if oos_sharpe_std and oos_sharpe_std > 0 and oos_sharpe_mean:
            oos_sharpe_consistency = float(oos_sharpe_mean / oos_sharpe_std)

        param_stability = self._compute_parameter_stability()
        degradation_ratios = self._compute_degradation_ratios()

        windows_positive = sum(1 for s in oos_sharpes if s > 0) if oos_sharpes else 0

        return {
            "total_windows": len(self.windows),
            "completed_windows": len([w for w in self.windows if w.oos_results]),
            "windows_zero_trades": zero_trade_count,
            "wfe_mean": wfe_mean,
            "wfe_min": wfe_min,
            "wfe_max": wfe_max,
            "oos_sharpe_mean": oos_sharpe_mean,
            "oos_sharpe_std": oos_sharpe_std,
            "oos_sharpe_min": oos_sharpe_min,
            "oos_sharpe_consistency": oos_sharpe_consistency,
            "parameter_stability_cv": param_stability,
            "degradation_ratios": degradation_ratios,
            "windows_positive_oos": windows_positive,
        }

    def compute_window_details(self) -> List[Dict[str, Any]]:
        """Return per-window detail records for backtest_results.json."""
        details = []
        for w in self.windows:
            detail = {
                "window_id": w.window_id,
                "is_start": w.is_start,
                "is_end": w.is_end,
                "oos_start": w.oos_start,
                "oos_end": w.oos_end,
                "is_years": round(w.is_years, 1),
                "oos_years": round(w.oos_years, 1),
                "is_sharpe": w.is_sharpe,
                "oos_sharpe": w.oos_sharpe,
                "walk_forward_efficiency": (
                    round(w.walk_forward_efficiency, 3)
                    if w.walk_forward_efficiency is not None else None
                ),
                "oos_metrics": self._extract_oos_metrics(w),
                "selected_trial_number": (
                    w.selected_trial.get('trial_number')
                    if w.selected_trial else None
                ),
            }
            details.append(detail)
        return details

    def _compute_parameter_stability(self) -> Dict[str, float]:
        """
        Compute coefficient of variation of optimized parameters across windows.

        Excludes fixed (non-optimized) parameters where std=0, since those are
        hardcoded constants — their CV=0 is trivially true and not informative.
        """
        param_values: Dict[str, List[float]] = {}
        for w in self.windows:
            if w.selected_trial and 'params' in w.selected_trial:
                for k, v in w.selected_trial['params'].items():
                    if isinstance(v, (int, float)):
                        param_values.setdefault(k, []).append(float(v))

        stability = {}
        for param_name, values in param_values.items():
            if len(values) >= 2:
                std_val = np.std(values)
                if std_val == 0:
                    continue  # Fixed/non-optimized parameter — skip
                mean_val = np.mean(values)
                cv = float(std_val / abs(mean_val)) if mean_val != 0 else float('inf')
                stability[param_name] = round(cv, 4)

        return stability

    def _compute_degradation_ratios(self) -> List[Dict[str, Any]]:
        """Compute OOS sharpe ratio between consecutive windows."""
        sorted_windows = sorted(
            [w for w in self.windows if w.oos_sharpe is not None],
            key=lambda w: w.window_id
        )
        ratios = []
        for i in range(1, len(sorted_windows)):
            prev_sharpe = sorted_windows[i - 1].oos_sharpe
            curr_sharpe = sorted_windows[i].oos_sharpe
            ratio = curr_sharpe / prev_sharpe if prev_sharpe != 0 else None
            ratios.append({
                "from_window": sorted_windows[i - 1].window_id,
                "to_window": sorted_windows[i].window_id,
                "ratio": round(float(ratio), 3) if ratio is not None else None,
            })
        return ratios

    def _extract_oos_metrics(self, window: WFAWindow) -> Dict[str, Any]:
        """Extract key OOS metrics from window results."""
        if not window.oos_results:
            return {}
        return {
            "sharpe_ratio_annual": window.oos_results.get("sharpe_ratio_annual"),
            "total_return_pct": window.oos_results.get("total_return_pct"),
            "max_drawdown_pct": window.oos_results.get("max_drawdown_pct"),
            "total_trades": window.oos_results.get("total_trades"),
            "win_rate_pct": window.oos_results.get("win_rate_pct"),
        }
