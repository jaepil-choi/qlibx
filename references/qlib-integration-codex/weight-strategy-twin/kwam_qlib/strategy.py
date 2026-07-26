from __future__ import annotations

import copy

import pandas as pd
from qlib.backtest.decision import TradeDecisionWO
from qlib.backtest.position import Position
from qlib.contrib.strategy.order_generator import OrderGenWInteract
from qlib.contrib.strategy.signal_strategy import WeightStrategyBase

from .feedback import QlibPortfolioFeedback, read_latest_portfolio_feedback
from .signals import build_long_only_target


class QlibPeerMomentumStrategy(WeightStrategyBase):
    """기존 peer-return alpha를 Qlib target-weight strategy로 구현한 twin."""

    def __init__(
        self,
        *,
        benchmark_weight: pd.DataFrame,
        universe_mask: pd.DataFrame,
        active_multiplier: float,
        top_fraction: float | None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        if not benchmark_weight.index.equals(universe_mask.index) or not (
            benchmark_weight.columns.equals(universe_mask.columns)
        ):
            raise ValueError("benchmark_weight and universe_mask axes must match.")
        self.benchmark_weight = benchmark_weight
        self.universe_mask = universe_mask.astype(bool)
        self.active_multiplier = active_multiplier
        self.top_fraction = top_fraction
        self.target_history: dict[pd.Timestamp, pd.Series] = {}
        self.active_history: dict[pd.Timestamp, pd.Series] = {}
        self.prediction_dates: dict[pd.Timestamp, pd.Timestamp] = {}

    def generate_target_weight_position(
        self,
        score,
        current,
        trade_start_time,
        trade_end_time,
    ) -> dict[str, float]:
        del current, trade_end_time
        trade_date = pd.Timestamp(trade_start_time).normalize()
        prediction_date = self._prediction_date_for(trade_date)
        score_row = _coerce_score(score).reindex(self.universe_mask.columns)
        target, active = build_long_only_target(
            score_row,
            self.benchmark_weight.loc[prediction_date],
            self.universe_mask.loc[trade_date],
            active_multiplier=self.active_multiplier,
            top_fraction=self.top_fraction,
        )
        self.target_history[trade_date] = target
        self.active_history[trade_date] = active
        self.prediction_dates[trade_date] = prediction_date
        return target[target.gt(0.0)].to_dict()

    def _prediction_date_for(self, trade_date: pd.Timestamp) -> pd.Timestamp:
        prior = self.benchmark_weight.index[self.benchmark_weight.index < trade_date]
        if prior.empty:
            raise ValueError(f"No prediction date precedes trade date {trade_date.date()}.")
        return pd.Timestamp(prior[-1])


class ConsecutiveLossStopPeerMomentumStrategy(QlibPeerMomentumStrategy):
    """Qlib portfolio가 연속 손실이면 전량 청산 후 cash를 유지하는 variant.

    손실 streak은 Qlib이 execution과 bar-end mark-to-market을 모두 끝낸 뒤 호출하는
    ``post_exe_step``에서 실제 Account net return으로 갱신합니다. Stop이 발동한 뒤에는
    signal 조회보다 먼저 빈 target을 주문으로 변환하므로 signal 유무와 무관하게 기존
    stock position을 청산합니다.
    """

    def __init__(
        self,
        *,
        consecutive_loss_days: int = 3,
        loss_tolerance: float = 1e-12,
        **kwargs,
    ) -> None:
        if consecutive_loss_days <= 0:
            raise ValueError("consecutive_loss_days must be greater than 0.")
        if loss_tolerance < 0.0:
            raise ValueError("loss_tolerance must be non-negative.")
        kwargs.setdefault("order_generator_cls_or_obj", OrderGenWInteract())
        super().__init__(**kwargs)
        self.consecutive_loss_days = consecutive_loss_days
        self.loss_tolerance = loss_tolerance
        self._reset_stop_state()

    def reset(self, *args, **kwargs) -> None:
        super().reset(*args, **kwargs)
        self._reset_stop_state()
        self.target_history.clear()
        self.active_history.clear()
        self.prediction_dates.clear()

    def generate_trade_decision(self, execute_result=None):
        if not self.stop_triggered:
            return super().generate_trade_decision(execute_result)

        trade_step = self.trade_calendar.get_trade_step()
        trade_start_time, trade_end_time = self.trade_calendar.get_step_time(trade_step)
        trade_date = pd.Timestamp(trade_start_time).normalize()
        current = copy.deepcopy(self.trade_position)
        if not isinstance(current, Position):
            raise TypeError("Consecutive-loss stop requires a finite Qlib Position.")

        order_list = self.order_generator.generate_order_list_from_target_weight_position(
            current=current,
            trade_exchange=self.trade_exchange,
            risk_degree=self.get_risk_degree(trade_step),
            target_weight_position={},
            pred_start_time=trade_start_time,
            pred_end_time=trade_end_time,
            trade_start_time=trade_start_time,
            trade_end_time=trade_end_time,
        )
        zero = pd.Series(0.0, index=self.universe_mask.columns, dtype="float64")
        self.target_history[trade_date] = zero.copy()
        self.active_history[trade_date] = zero.copy()
        self.stop_target_dates.append(trade_date)
        if self.liquidation_decision_date is None:
            self.liquidation_decision_date = trade_date
        return TradeDecisionWO(order_list, self)

    def post_exe_step(self, execute_result) -> None:
        super().post_exe_step(execute_result)
        trade_account = self.common_infra.get("trade_account")
        feedback = read_latest_portfolio_feedback(trade_account)
        if self.portfolio_feedback_history and (
            self.portfolio_feedback_history[-1].date == feedback.date
        ):
            raise RuntimeError(f"Duplicate Qlib portfolio feedback date: {feedback.date.date()}")

        self.portfolio_feedback_history.append(feedback)
        if feedback.net_return < -self.loss_tolerance:
            self.current_loss_streak += 1
        else:
            self.current_loss_streak = 0

        if not self.stop_triggered and self.current_loss_streak >= self.consecutive_loss_days:
            self.stop_triggered = True
            self.stop_trigger_date = feedback.date

    def _reset_stop_state(self) -> None:
        self.current_loss_streak = 0
        self.stop_triggered = False
        self.stop_trigger_date: pd.Timestamp | None = None
        self.liquidation_decision_date: pd.Timestamp | None = None
        self.stop_target_dates: list[pd.Timestamp] = []
        self.portfolio_feedback_history: list[QlibPortfolioFeedback] = []


def _coerce_score(score) -> pd.Series:
    if isinstance(score, pd.DataFrame):
        if score.shape[1] != 1:
            raise ValueError("Peer momentum score must contain exactly one column.")
        score = score.iloc[:, 0]
    if not isinstance(score, pd.Series):
        raise TypeError("Peer momentum score must be a pandas Series.")
    return pd.to_numeric(score, errors="coerce").astype("float64")
