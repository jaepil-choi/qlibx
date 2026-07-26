from __future__ import annotations

import copy
from typing import Any

import numpy as np
import pandas as pd
from qlib.backtest.decision import TradeDecisionWO
from qlib.backtest.position import Position
from qlib.contrib.strategy.order_generator import OrderGenWInteract
from qlib.strategy.base import BaseStrategy

from kwam_enhanced_index.portfolio.enhanced_index import (
    EnhancedIndexInputs,
    EnhancedIndexMethod,
    apply_execution_universe_to_enhanced_result,
)
from kwam_enhanced_index.portfolio.scale import SideExposureScaler, scale_alpha_weight
from peer_momentum_runtime.data import QlibPeerMomentumData
from peer_momentum_runtime.peer_return import compute_peer_return
from kwam_enhanced_index.strategies.transforms.signal_decay import (
    apply_linear_signal_decay,
)


# 역할: peer momentum의 전체 decision을 Qlib BaseStrategy lifecycle 안에서 수행합니다.
# 책임:
# - runner가 계산한 signal/target을 받지 않고 observation window에서 직접 alpha를 계산합니다.
# - enhanced-index optimizer 결과를 physical stock/ETF Qlib order decision으로 변환합니다.
# - Qlib execution/account feedback과 run-local signal state를 보존합니다.


class QlibPeerMomentumStrategy(BaseStrategy):
    """EW decay peer momentum을 online 계산하는 Qlib-native portfolio strategy."""

    def __init__(
        self,
        *,
        strategy_id: str,
        data: QlibPeerMomentumData,
        portfolio_method: EnhancedIndexMethod,
        alpha_multiplier: float,
        top_fraction: float,
        decay_window: int,
        decay_dense: bool,
        risk_degree: float,
        order_generator: OrderGenWInteract | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        if not strategy_id:
            raise ValueError("strategy_id must be non-empty.")
        if not 0.0 < top_fraction <= 1.0:
            raise ValueError("top_fraction must be in (0, 1].")
        if decay_window <= 0:
            raise ValueError("decay_window must be positive.")
        if not 0.0 < risk_degree <= 1.0:
            raise ValueError("risk_degree must be in (0, 1].")
        if not np.isfinite(alpha_multiplier) or alpha_multiplier < 0.0:
            raise ValueError("alpha_multiplier must be finite and non-negative.")
        self.strategy_id = strategy_id
        self.data = data
        self.portfolio_method = portfolio_method
        self.alpha_multiplier = float(alpha_multiplier)
        self.top_fraction = float(top_fraction)
        self.decay_window = int(decay_window)
        self.decay_dense = bool(decay_dense)
        self.risk_degree = float(risk_degree)
        self.order_generator = order_generator or OrderGenWInteract()
        self._reset_run_state()

    def reset(self, *args: Any, **kwargs: Any) -> None:
        super().reset(*args, **kwargs)
        self._reset_run_state()

    def generate_trade_decision(self, execute_result=None) -> TradeDecisionWO:
        del execute_result
        trade_step = self.trade_calendar.get_trade_step()
        trade_start_time, trade_end_time = self.trade_calendar.get_step_time(trade_step)
        trade_date = pd.Timestamp(trade_start_time).normalize()
        observation_date = self.data.previous_observation_date(trade_date)

        raw_signal = compute_peer_return(
            self.data.returns.loc[observation_date],
            self.data.peer_groups.loc[observation_date],
            self.data.universe_mask.loc[observation_date],
        )
        raw_signal.name = observation_date
        decayed_signal, updated_history = apply_linear_signal_decay(
            history=self._signal_decay_history,
            current_signal=raw_signal,
            decay_window=self.decay_window,
            dense=self.decay_dense,
        )
        self._signal_decay_history = updated_history
        selected_signal = _select_top_fraction(
            decayed_signal,
            self.data.universe_mask.loc[observation_date],
            self.top_fraction,
        )
        active_weight = _scale_signal(
            selected_signal,
            self.data.universe_mask.loc[observation_date],
            trade_date,
        )
        benchmark_weight = self.data.benchmark_weight.loc[trade_date]
        if benchmark_weight.isna().any():
            raise ValueError(
                f"Benchmark weight is unavailable for trade date {trade_date.date()}."
            )
        portfolio_result = self.portfolio_method.build(
            EnhancedIndexInputs(
                benchmark_weight=_one_row(benchmark_weight, trade_date),
                alpha_weight=_one_row(active_weight, trade_date),
                alpha_multiplier=self.alpha_multiplier,
            )
        )
        portfolio_result = apply_execution_universe_to_enhanced_result(
            portfolio_result,
            _one_row(self.data.universe_mask.loc[trade_date], trade_date).astype(bool),
        )
        direct_target = portfolio_result.direct_stock_weight.loc[trade_date]
        etf_target = float(portfolio_result.passive_sleeve_weight.loc[trade_date])
        physical_target = pd.Series(
            0.0,
            index=self.data.physical_columns,
            dtype="float64",
        )
        physical_target.loc[self.data.stock_columns] = direct_target
        physical_target.loc[self.data.etf_ticker] = etf_target
        _validate_physical_target(physical_target, trade_date)

        current = copy.deepcopy(self.trade_position)
        if not isinstance(current, Position):
            raise TypeError("Qlib peer momentum strategy requires a finite Position.")
        orders = self.order_generator.generate_order_list_from_target_weight_position(
            current=current,
            trade_exchange=self.trade_exchange,
            risk_degree=self.risk_degree,
            target_weight_position=physical_target[
                physical_target.gt(0.0)
            ].to_dict(),
            pred_start_time=observation_date,
            pred_end_time=observation_date,
            trade_start_time=trade_start_time,
            trade_end_time=trade_end_time,
        )
        self.raw_signal_history[trade_date] = raw_signal.copy()
        self.decayed_signal_history[trade_date] = decayed_signal.copy()
        self.selected_signal_history[trade_date] = selected_signal.copy()
        self.active_weight_history[trade_date] = active_weight.copy()
        self.physical_target_history[trade_date] = physical_target.copy()
        self.observation_dates[trade_date] = observation_date
        self.etf_weight_history[trade_date] = etf_target
        self.decision_count += 1
        return TradeDecisionWO(orders, self)

    def post_exe_step(self, execute_result) -> None:
        trade_account = self.common_infra.get("trade_account")
        report, _positions = trade_account.get_portfolio_metrics()
        if report.empty:
            raise RuntimeError("Qlib Account did not publish a completed portfolio bar.")
        required = {"return", "cost", "turnover", "cash", "account"}
        missing = sorted(required - set(report.columns))
        if missing:
            raise KeyError(f"Qlib portfolio metrics are missing fields: {missing}")
        date = pd.Timestamp(report.index[-1]).normalize()
        row = report.iloc[-1]
        feedback = {
            "trade_date": date,
            "gross_return": float(row["return"]),
            "cost": float(row["cost"]),
            "net_return": float(row["return"] - row["cost"]),
            "turnover": float(row["turnover"]),
            "cash": float(row["cash"]),
            "nav": float(row["account"]),
        }
        if self.feedback_history and self.feedback_history[-1]["trade_date"] == date:
            raise RuntimeError(f"Duplicate Qlib feedback date: {date.date()}")
        self.feedback_history.append(feedback)

        factor = self.data.position_unit_factor.loc[date]
        for instrument, adjusted_amount in self.trade_position.get_stock_amount_dict().items():
            self.position_history.append(
                {
                    "trade_date": date,
                    "instrument_id": str(instrument),
                    "held_quantity": float(adjusted_amount)
                    * float(factor.loc[instrument]),
                    "asset_class": str(self.data.asset_class.loc[instrument]),
                }
            )
        self.last_execute_result = tuple(execute_result or ())

    def _reset_run_state(self) -> None:
        self._signal_decay_history: list[pd.Series] = []
        self.raw_signal_history: dict[pd.Timestamp, pd.Series] = {}
        self.decayed_signal_history: dict[pd.Timestamp, pd.Series] = {}
        self.selected_signal_history: dict[pd.Timestamp, pd.Series] = {}
        self.active_weight_history: dict[pd.Timestamp, pd.Series] = {}
        self.physical_target_history: dict[pd.Timestamp, pd.Series] = {}
        self.observation_dates: dict[pd.Timestamp, pd.Timestamp] = {}
        self.etf_weight_history: dict[pd.Timestamp, float] = {}
        self.feedback_history: list[dict[str, object]] = []
        self.position_history: list[dict[str, object]] = []
        self.last_execute_result: tuple[object, ...] = ()
        self.decision_count = 0


def _select_top_fraction(
    signal: pd.Series,
    universe_mask: pd.Series,
    top_fraction: float,
) -> pd.Series:
    if not signal.index.equals(universe_mask.index):
        raise ValueError("signal and universe_mask index must match.")
    result = pd.Series(np.nan, index=signal.index, dtype="float64")
    eligible = signal.where(universe_mask.fillna(False).astype(bool)).dropna()
    if eligible.empty:
        return result
    keep_count = max(1, int(np.ceil(len(eligible) * top_fraction)))
    selected = eligible.abs().nlargest(keep_count, keep="all").index
    result.loc[selected] = signal.loc[selected]
    return result


def _scale_signal(
    signal: pd.Series,
    universe_mask: pd.Series,
    trade_date: pd.Timestamp,
) -> pd.Series:
    frame = _one_row(signal, trade_date)
    mask = _one_row(universe_mask, trade_date).astype(bool)
    result = scale_alpha_weight(
        frame,
        mask,
        scaler=SideExposureScaler(),
    ).iloc[0]
    result.name = trade_date
    return result.astype("float64")


def _one_row(series: pd.Series, date: pd.Timestamp) -> pd.DataFrame:
    return pd.DataFrame(
        [series.to_numpy()],
        index=pd.DatetimeIndex([date]),
        columns=series.index,
    )


def _validate_physical_target(
    target: pd.Series,
    trade_date: pd.Timestamp,
) -> None:
    if target.isna().any() or not np.isfinite(target.to_numpy()).all():
        raise ValueError(f"Physical target contains missing values: {trade_date.date()}")
    if target.lt(-1e-10).any():
        raise ValueError(f"Physical target contains short weights: {trade_date.date()}")
    total = float(target.sum())
    if not np.isclose(total, 1.0, atol=1e-8):
        raise ValueError(
            f"Physical stock/ETF target must sum to 1: {trade_date.date()}, total={total}"
        )
