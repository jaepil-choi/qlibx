"""Portfolio constructor pipeline."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from echolon.panel import PanelView

from .models import (
    BookRiskSnapshot,
    BookState,
    InstrumentRebalance,
    RebalanceRecord,
    TargetBook,
)

# Average-correlation vol-targeting controls. The scaling is a fixed-point
# iteration: at most this many rescale rounds, stopping early once the global
# scale is within tolerance of 1.0. Both are mechanism constants, not calibration.
_AVG_CORR_MAX_ROUNDS = 5
_AVG_CORR_REL_TOL = 1e-6


class ConstructorConfig(BaseModel):
    """Capital-relative constructor configuration.

    Percent fields use 0-100 units. No RMB capital constants belong here.
    """

    model_config = ConfigDict(extra="forbid")

    vol_target_ann_pct: float
    sector_caps_pct: dict[str, float]
    max_margin_utilization_pct: float
    min_abs_score_for_position: float
    sizing_mode: Literal["implementation", "research"] = "implementation"
    rebalance_band_lots: float = Field(default=0.0, ge=0.0)
    long_only: bool = False
    max_weight_per_name_pct: float | None = None
    implementation_min_lots: float | None = Field(default=None, gt=0.0)
    # Portfolio-vol targeting model. "perfect_correlation" is the historical
    # sizing (sum_i w_i*sigma_i == target; the true portfolio vol only when every
    # held name is perfectly correlated) and is the DEFAULT so unset callers keep
    # byte-identical books. "avg_correlation" instead rescales the book so the
    # estimated portfolio vol under an average-pairwise-correlation approximation
    # meets the target, with the risk caps engaging each round.
    vol_model: Literal["perfect_correlation", "avg_correlation"] = "perfect_correlation"
    avg_correlation_lookback_days: int = Field(default=120, gt=1)


class Constructor:
    """Convert blended scores into integer target lots."""

    def __init__(self, config: ConstructorConfig) -> None:
        self.config = config

    def construct(
        self,
        *,
        view: PanelView,
        book: BookState,
        blended_scores: Mapping[str, float],
        raw_scores: Mapping[str, Mapping[str, float | None]],
    ) -> tuple[TargetBook, RebalanceRecord]:
        rows: dict[str, InstrumentRebalance] = {}
        lots_float: dict[str, float] = {}
        effective_scores = {
            instrument: max(float(score), 0.0)
            if self.config.long_only
            else float(score)
            for instrument, score in blended_scores.items()
        }
        denom = sum(abs(score) for score in effective_scores.values())
        for instrument, blended in effective_scores.items():
            bars = view.bars(instrument, 64)
            meta = view.meta(instrument)
            if bars.empty:
                vol_ann = 0.0
                pre_round = 0.0
            else:
                price = _raw_price(bars.iloc[-1], "settle")
                vol_ann = _annualized_vol(bars["settle"])
            if bars.empty or denom <= 1e-12 or vol_ann <= 0.0:
                pre_round = 0.0
            else:
                notional = (
                    book.equity_rmb
                    * self.config.vol_target_ann_pct
                    / 100.0
                    * float(blended)
                    / (vol_ann * denom)
                )
                pre_round = notional / (price * float(meta.multiplier))
            if abs(float(blended)) < self.config.min_abs_score_for_position:
                pre_round = 0.0
            lots_float[instrument] = pre_round
            rows[instrument] = InstrumentRebalance(
                raw_scores=dict(raw_scores.get(instrument, {})),
                blended=float(blended),
                vol_ann=vol_ann,
                pre_round_lots=pre_round,
                post_round_lots=0,
                caps_applied=[],
            )

        self._pin_suspended_positions(view, book, lots_float, rows)
        if self.config.vol_model == "avg_correlation":
            self._apply_avg_correlation_targeting(view, book, lots_float, rows)
        else:
            self._apply_sector_caps(view, book, lots_float, rows)
            self._apply_per_name_cap(view, book, lots_float, rows)
            self._apply_margin_cap(view, book, lots_float, rows)

        if self.config.sizing_mode == "research":
            final_targets = {
                instrument: float(lots) for instrument, lots in lots_float.items()
            }
        else:
            if self.config.implementation_min_lots is not None:
                self._concentrate_min_lots(
                    view=view,
                    book=book,
                    effective_scores=effective_scores,
                    lots_float=lots_float,
                    rows=rows,
                )
            final_targets = {
                instrument: round_toward_zero_lot(
                    lots, float(view.meta(instrument).min_order_size)
                )
                for instrument, lots in lots_float.items()
            }
        final_targets = self._apply_rebalance_band(view, book, final_targets, rows)
        for instrument, lots in final_targets.items():
            rows[instrument].post_round_lots = lots
        return (
            TargetBook(date=view.date, targets=final_targets),
            RebalanceRecord(date=view.date, instruments=rows),
        )

    def _concentrate_min_lots(
        self,
        *,
        view: PanelView,
        book: BookState,
        effective_scores: Mapping[str, float],
        lots_float: dict[str, float],
        rows: dict[str, InstrumentRebalance],
    ) -> None:
        """Drop undersized positions and resize survivors at unchanged target volatility.

        ``implementation_min_lots`` is measured in exchange lots. For example, a value
        of 1.0 requires 100 shares when an instrument's minimum order size is 100 shares.
        The method mutates ``lots_float`` in instrument units and records every drop.
        """
        minimum_lots = self.config.implementation_min_lots
        if minimum_lots is None:
            return
        active = {
            instrument for instrument, lots in lots_float.items() if abs(lots) > 0.0
        }
        for _ in range(len(active)):
            tentative = {
                instrument: round_toward_zero_lot(
                    lots_float[instrument], float(view.meta(instrument).min_order_size)
                )
                for instrument in active
            }
            undersized = [
                instrument
                for instrument in active
                if abs(tentative[instrument])
                < minimum_lots * float(view.meta(instrument).min_order_size)
            ]
            if not undersized:
                return
            drop = min(
                undersized,
                key=lambda instrument: (abs(effective_scores[instrument]), instrument),
            )
            before = lots_float[drop]
            lots_float[drop] = 0.0
            rows[drop].caps_applied.append(
                {"cap": "min_lot_drop", "before": before, "after": 0.0}
            )
            active.remove(drop)
            if not active:
                return

            resized = self._resize_active(view, book, effective_scores, active, rows)
            self._apply_sector_caps(view, book, resized, rows)
            self._apply_per_name_cap(view, book, resized, rows)
            self._apply_margin_cap(view, book, resized, rows)
            lots_float.update(resized)

    def _resize_active(
        self,
        view: PanelView,
        book: BookState,
        effective_scores: Mapping[str, float],
        active: set[str],
        rows: Mapping[str, InstrumentRebalance],
    ) -> dict[str, float]:
        """Re-run SPECS S7 volatility sizing for active instruments, returning lots."""
        denominator = sum(
            abs(effective_scores[instrument]) for instrument in sorted(active)
        )
        resized: dict[str, float] = {}
        for instrument in sorted(active):
            bars = view.bars(instrument, 1)
            vol_ann = rows[instrument].vol_ann
            if bars.empty or denominator <= 1e-12 or vol_ann <= 0.0:
                resized[instrument] = 0.0
                continue
            price = _raw_price(bars.iloc[-1], "settle")
            meta = view.meta(instrument)
            notional = (
                book.equity_rmb
                * self.config.vol_target_ann_pct
                / 100.0
                * effective_scores[instrument]
                / (vol_ann * denominator)
            )
            resized[instrument] = notional / (price * float(meta.multiplier))
        return resized

    def _apply_rebalance_band(
        self,
        view: PanelView,
        book: BookState,
        targets: dict[str, float],
        rows: dict[str, InstrumentRebalance],
    ) -> dict[str, float]:
        """Hold small same-direction target changes to reduce churn.

        The band deliberately does not block exits, sign flips, or cap-driven
        de-risking. A proposed banded book must still pass current sector and
        margin caps, so stale positions cannot be preserved by accident.
        """
        band = float(self.config.rebalance_band_lots)
        if band <= 0.0:
            return targets
        banded = dict(targets)
        for instrument, target in targets.items():
            position = book.positions.get(instrument)
            current = 0.0 if position is None else float(position.lots)
            if current == 0.0 or target == 0.0:
                continue
            if _sign(current) != _sign(target):
                continue
            if abs(target) < abs(current):
                continue
            if abs(float(target) - current) > band:
                continue
            banded[instrument] = current
        if banded == targets or not self._targets_within_caps(view, book, banded):
            return targets
        for instrument, target in targets.items():
            after = banded[instrument]
            if after == target:
                continue
            rows[instrument].caps_applied.append(
                {
                    "cap": "rebalance_band_lots",
                    "before": float(target),
                    "after": float(after),
                }
            )
        return banded

    def _targets_within_caps(
        self,
        view: PanelView,
        book: BookState,
        targets: Mapping[str, float],
    ) -> bool:
        risk = self.book_risk(view, book, targets)
        if risk.margin_utilization_pct > self.config.max_margin_utilization_pct + 1e-9:
            return False
        for sector, exposure in risk.sector_gross_notional_pct.items():
            cap = self.config.sector_caps_pct.get(sector)
            if cap is not None and exposure > cap + 1e-9:
                return False
        return True

    def book_risk(
        self,
        view: PanelView,
        book: BookState,
        targets: Mapping[str, float],
    ) -> BookRiskSnapshot:
        gross_by_sector: dict[str, float] = defaultdict(float)
        margin = 0.0
        gross = 0.0
        net = 0.0
        for instrument, lots in targets.items():
            if lots == 0:
                continue
            bars = view.bars(instrument, 1)
            if bars.empty:
                continue
            bar = bars.iloc[-1]
            price = _raw_price(bar, "settle")
            meta = view.meta(instrument)
            notional = lots * price * float(meta.multiplier)
            margin += abs(notional) * float(meta.margin_rate)
            gross += abs(notional)
            net += notional
            gross_by_sector[meta.sector] += abs(notional)
        equity = book.equity_rmb
        return BookRiskSnapshot(
            margin_used_rmb=margin,
            margin_utilization_pct=margin / equity * 100.0 if equity else math.inf,
            gross_exposure_pct=gross / equity * 100.0 if equity else math.inf,
            net_exposure_pct=net / equity * 100.0 if equity else math.inf,
            sector_gross_notional_pct={
                sector: value / equity * 100.0 if equity else math.inf
                for sector, value in gross_by_sector.items()
            },
        )

    def _apply_sector_caps(
        self,
        view: PanelView,
        book: BookState,
        lots_float: dict[str, float],
        rows: dict[str, InstrumentRebalance],
    ) -> None:
        sector_to_instruments: dict[str, list[str]] = defaultdict(list)
        sector_gross: dict[str, float] = defaultdict(float)
        for instrument, lots in lots_float.items():
            meta = view.meta(instrument)
            bars = view.bars(instrument, 1)
            if bars.empty:
                continue
            price = _raw_price(bars.iloc[-1], "settle")
            notional = abs(lots) * price * float(meta.multiplier)
            sector_to_instruments[meta.sector].append(instrument)
            sector_gross[meta.sector] += notional
        for sector, gross in sector_gross.items():
            cap_pct = self.config.sector_caps_pct.get(sector)
            if cap_pct is None:
                continue
            cap_rmb = book.equity_rmb * cap_pct / 100.0
            if gross <= cap_rmb or gross == 0.0:
                continue
            scale = cap_rmb / gross
            for instrument in sector_to_instruments[sector]:
                before = lots_float[instrument]
                lots_float[instrument] *= scale
                rows[instrument].caps_applied.append(
                    {
                        "cap": f"sector:{sector}",
                        "before": before,
                        "after": lots_float[instrument],
                    }
                )

    def _apply_margin_cap(
        self,
        view: PanelView,
        book: BookState,
        lots_float: dict[str, float],
        rows: dict[str, InstrumentRebalance],
    ) -> None:
        margin = 0.0
        for instrument, lots in lots_float.items():
            meta = view.meta(instrument)
            bars = view.bars(instrument, 1)
            if bars.empty:
                continue
            price = _raw_price(bars.iloc[-1], "settle")
            margin += (
                abs(lots) * price * float(meta.multiplier) * float(meta.margin_rate)
            )
        cap_rmb = book.equity_rmb * self.config.max_margin_utilization_pct / 100.0
        if margin <= cap_rmb or margin == 0.0:
            return
        scale = cap_rmb / margin
        for instrument in lots_float:
            before = lots_float[instrument]
            lots_float[instrument] *= scale
            rows[instrument].caps_applied.append(
                {"cap": "margin", "before": before, "after": lots_float[instrument]}
            )

    def _apply_per_name_cap(
        self,
        view: PanelView,
        book: BookState,
        lots_float: dict[str, float],
        rows: dict[str, InstrumentRebalance],
    ) -> None:
        cap_pct = self.config.max_weight_per_name_pct
        if cap_pct is None:
            return
        cap_rmb = book.equity_rmb * cap_pct / 100.0
        for instrument, lots in lots_float.items():
            bars = view.bars(instrument, 1)
            if bars.empty:
                continue
            meta = view.meta(instrument)
            price = _raw_price(bars.iloc[-1], "settle")
            notional = abs(lots) * price * float(meta.multiplier)
            if notional <= cap_rmb or notional == 0.0:
                continue
            before = lots_float[instrument]
            lots_float[instrument] *= cap_rmb / notional
            rows[instrument].caps_applied.append(
                {
                    "cap": "per_name_weight",
                    "before": before,
                    "after": lots_float[instrument],
                }
            )

    def _apply_avg_correlation_targeting(
        self,
        view: PanelView,
        book: BookState,
        lots_float: dict[str, float],
        rows: dict[str, InstrumentRebalance],
    ) -> None:
        """Rescale the book so estimated portfolio vol meets target under average
        pairwise correlation, re-applying every risk cap each round.

        The perfect-correlation model sizes so ``sum_i w_i*sigma_i`` equals the
        target, which is the true portfolio vol only when every held name moves
        together. This mode estimates portfolio vol with the average-correlation
        approximation and rescales toward the target across at most
        :data:`_AVG_CORR_MAX_ROUNDS` fixed-point rounds. Caps take priority: a
        name pinned at a cap is re-clipped after every rescale while uncapped
        names absorb the remaining risk budget, so the caps ENGAGE when binding.
        Reduces to the perfect-correlation sizing exactly when the average
        correlation is 1.0 (the rescale factor is then 1.0 and nothing moves).
        """
        target_vol = self.config.vol_target_ann_pct / 100.0
        for _ in range(_AVG_CORR_MAX_ROUNDS):
            self._apply_sector_caps(view, book, lots_float, rows)
            self._apply_per_name_cap(view, book, lots_float, rows)
            self._apply_margin_cap(view, book, lots_float, rows)
            sigma_p = self._estimate_portfolio_vol(view, book, lots_float, rows)
            if sigma_p <= 0.0:
                return
            scale = target_vol / sigma_p
            if abs(scale - 1.0) <= _AVG_CORR_REL_TOL:
                return
            for instrument in lots_float:
                lots_float[instrument] *= scale
        # Enforce caps once more so they still hold after the final rescale.
        self._apply_sector_caps(view, book, lots_float, rows)
        self._apply_per_name_cap(view, book, lots_float, rows)
        self._apply_margin_cap(view, book, lots_float, rows)

    def _estimate_portfolio_vol(
        self,
        view: PanelView,
        book: BookState,
        lots_float: Mapping[str, float],
        rows: Mapping[str, InstrumentRebalance],
    ) -> float:
        """Annualized portfolio vol under the average-correlation approximation.

        ``sigma_p^2 = (1 - rho_bar) * sum_i (w_i*sigma_i)^2
                      + rho_bar * (sum_i w_i*sigma_i)^2`` where ``w_i`` is the
        signed notional weight, ``sigma_i`` reuses the sizing vol recorded in
        ``rows`` (so the perfect-correlation limit is exact), and ``rho_bar`` is
        the average trailing pairwise correlation of the held names.
        """
        equity = book.equity_rmb
        if equity <= 0.0:
            return 0.0
        contributions: dict[str, float] = {}
        for instrument, lots in lots_float.items():
            if lots == 0.0:
                continue
            bars = view.bars(instrument, 1)
            if bars.empty:
                continue
            sigma_i = float(rows[instrument].vol_ann)
            if sigma_i <= 0.0:
                continue
            price = _raw_price(bars.iloc[-1], "settle")
            meta = view.meta(instrument)
            weight = lots * price * float(meta.multiplier) / equity
            contributions[instrument] = weight * sigma_i
        if not contributions:
            return 0.0
        held = sorted(contributions)
        sum_squared = sum(value * value for value in contributions.values())
        sum_linear = sum(contributions.values())
        rho_bar = _average_pairwise_correlation(
            view, held, self.config.avg_correlation_lookback_days
        )
        variance = (1.0 - rho_bar) * sum_squared + rho_bar * (sum_linear * sum_linear)
        return math.sqrt(variance) if variance > 0.0 else 0.0

    def _pin_suspended_positions(
        self,
        view: PanelView,
        book: BookState,
        targets: dict[str, float],
        rows: dict[str, InstrumentRebalance],
    ) -> None:
        for instrument, target in list(targets.items()):
            bars = view.bars(instrument, 1)
            if bars.empty or float(bars.iloc[-1].get("suspended", 0.0)) != 1.0:
                continue
            position = book.positions.get(instrument)
            held = 0.0 if position is None else float(position.lots)
            targets[instrument] = held
            rows[instrument].caps_applied.append(
                {"cap": "suspended_hold", "before": float(target), "after": held}
            )


def _average_pairwise_correlation(
    view: PanelView, instruments: list[str], lookback_days: int
) -> float:
    """Average Pearson correlation of trailing ``lookback_days`` daily returns.

    Only names with a full, finite return window (complete-case) enter the
    estimate; a name short of history still contributes to portfolio variance
    through its own vol, but not to the shared correlation. The average is the
    exact off-diagonal mean of the correlation matrix, computed in O(n*T) from
    unit-normalized return vectors, and is clipped to ``[-1.0, 1.0]``. Fewer than
    two qualifying names returns 0.0 (independence): with one held name there are
    no cross terms, so the correlation is irrelevant to the variance.
    """
    if len(instruments) < 2:
        return 0.0
    unit_vectors: list[np.ndarray] = []
    for instrument in instruments:
        bars = view.bars(instrument, lookback_days + 1)
        settles = pd.to_numeric(bars["settle"], errors="coerce")
        returns = settles.pct_change().to_numpy(dtype=float)[1:]
        if returns.size < lookback_days or not np.all(np.isfinite(returns)):
            continue
        window = returns[-lookback_days:]
        centered = window - window.mean()
        norm = math.sqrt(float(centered @ centered))
        if norm <= 0.0:
            continue
        unit_vectors.append(centered / norm)
    if len(unit_vectors) < 2:
        return 0.0
    standardized = np.vstack(unit_vectors)
    count = standardized.shape[0]
    total = standardized.sum(axis=0)
    off_diagonal_sum = float(total @ total) - float(count)
    rho_bar = off_diagonal_sum / (count * (count - 1))
    return max(-1.0, min(1.0, rho_bar))


def _annualized_vol(settles: pd.Series) -> float:
    returns = pd.to_numeric(settles, errors="coerce").pct_change().dropna()
    if len(returns) < 2:
        return 0.0
    return float(returns.std(ddof=1) * math.sqrt(252.0))


def _toward_zero(value: float) -> int:
    return math.ceil(value) if value < 0 else math.floor(value)


def round_toward_zero_lot(value: float, min_order_size: float) -> int:
    """Round an exposure toward zero in exact exchange-order increments."""
    if min_order_size <= 0:
        raise ValueError("min_order_size must be positive")
    lots = _toward_zero(value / min_order_size)
    return int(lots * min_order_size)


# Compatibility for callers that historically imported the private helper.
_toward_zero_lot = round_toward_zero_lot


def _sign(value: float) -> int:
    return 1 if value > 0 else -1


def _raw_price(row: pd.Series, column: str) -> float:
    raw_column = f"{column}_raw"
    if raw_column in row:
        return float(row[raw_column])
    return float(row[column])
