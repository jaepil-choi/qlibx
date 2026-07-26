from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import numpy as np
import pandas as pd
from qlib.backtest.decision import Order
from qlib.backtest.exchange import Exchange


@dataclass(frozen=True)
class KrxExecutionPolicy:
    asset_class: str
    buy_rate: float
    sell_rate: float
    sell_tax: float
    allow_short: bool = False

    @property
    def policy_id(self) -> str:
        return f"krx_{self.asset_class}_v1"

    def effective_cost_rate(self, direction: int) -> float:
        if direction == Order.BUY:
            return self.buy_rate
        return self.sell_rate + self.sell_tax


@dataclass(frozen=True)
class ExecutionDiagnostic:
    reason_code: str
    blocked_by: str | None
    requested_amount: float
    amount_after_tradability: float
    amount_after_volume: float
    amount_after_position: float
    amount_after_cash: float
    amount_after_lot: float
    filled_amount: float
    asset_class: str
    execution_policy: str
    effective_cost_rate: float
    short_enabled: bool


@dataclass
class _DiagnosticBuilder:
    instrument_id: str
    direction: int
    requested_amount: float
    asset_class: str
    execution_policy: str
    effective_cost_rate: float
    short_enabled: bool
    tradability_reason: str | None = None
    amount_after_tradability: float | None = None
    amount_after_volume: float | None = None
    amount_after_position: float | None = None
    amount_after_cash: float | None = None
    amount_after_lot: float | None = None


class ScenarioExchange(Exchange):
    """Qlib deal-order path를 계측하는 KRX policy adapter입니다."""

    def __init__(
        self,
        *,
        quote_frame: pd.DataFrame,
        asset_class: Mapping[str, str],
        cost_policy: Mapping[str, Mapping[str, float]],
        lot_size: Mapping[str, int],
        **kwargs,
    ) -> None:
        self._direct_quote_frame = _validate_quote_frame(quote_frame)
        self._asset_class = dict(asset_class)
        self._policies = _build_policies(cost_policy)
        self._lot_size = {str(key): int(value) for key, value in lot_size.items()}
        self._active_diagnostic: _DiagnosticBuilder | None = None
        self._last_diagnostic: ExecutionDiagnostic | None = None
        super().__init__(**kwargs)

    def get_quote_from_qlib(self) -> None:
        missing = sorted(set(self.all_fields) - set(self._direct_quote_frame.columns))
        if missing:
            raise KeyError(f"Direct quote frame is missing Qlib fields: {missing}")
        self.quote_df = self._direct_quote_frame.loc[:, self.all_fields].copy()
        self.trade_w_adj_price = False
        self._update_limit(self.limit_threshold)

    def deal_order(
        self,
        order,
        trade_account=None,
        position=None,
        dealt_order_amount=None,
    ):
        asset_class = self._asset_class[order.stock_id]
        policy = self._policies[asset_class]
        builder = _DiagnosticBuilder(
            instrument_id=str(order.stock_id),
            direction=int(order.direction),
            requested_amount=float(order.amount),
            asset_class=asset_class,
            execution_policy=policy.policy_id,
            effective_cost_rate=policy.effective_cost_rate(order.direction),
            short_enabled=policy.allow_short,
            tradability_reason=self._tradability_reason(order),
        )
        self._active_diagnostic = builder
        self._last_diagnostic = None
        try:
            result = super().deal_order(
                order,
                trade_account=trade_account,
                position=position,
                dealt_order_amount={} if dealt_order_amount is None else dealt_order_amount,
            )
            self._last_diagnostic = _finalize_diagnostic(
                builder, float(order.deal_amount)
            )
            return result
        finally:
            self._active_diagnostic = None

    def consume_last_diagnostic(self) -> ExecutionDiagnostic:
        diagnostic = self._last_diagnostic
        self._last_diagnostic = None
        if diagnostic is None:
            raise RuntimeError("Qlib order did not produce an execution diagnostic")
        return diagnostic

    def _calc_trade_info_by_order(self, order, position, dealt_order_amount):
        asset_class = self._asset_class[order.stock_id]
        policy = self._policies[asset_class]
        old_open, old_close = self.open_cost, self.close_cost
        self.open_cost = policy.buy_rate
        self.close_cost = policy.sell_rate + policy.sell_tax
        try:
            result = super()._calc_trade_info_by_order(
                order, position, dealt_order_amount
            )
            builder = self._active_diagnostic
            if builder is not None:
                after_volume = (
                    builder.requested_amount
                    if builder.amount_after_volume is None
                    else builder.amount_after_volume
                )
                if order.direction == Order.BUY:
                    if builder.amount_after_position is None:
                        builder.amount_after_position = float(after_volume)
                    if builder.amount_after_cash is None:
                        builder.amount_after_cash = float(
                            order.deal_amount
                            if builder.amount_after_lot is None
                            and _less(float(order.deal_amount), after_volume)
                            else after_volume
                        )
                else:
                    current_amount = 0.0
                    if position is not None and position.check_stock(order.stock_id):
                        current_amount = float(
                            position.get_stock_amount(order.stock_id)
                        )
                    if builder.amount_after_position is None:
                        builder.amount_after_position = min(
                            float(after_volume), current_amount
                        )
                    planned_after_lot = (
                        builder.amount_after_position
                        if builder.amount_after_lot is None
                        else builder.amount_after_lot
                    )
                    if _less(float(order.deal_amount), float(planned_after_lot)):
                        builder.amount_after_cash = float(order.deal_amount)
                        builder.amount_after_lot = float(order.deal_amount)
                    elif builder.amount_after_cash is None:
                        builder.amount_after_cash = float(
                            builder.amount_after_position
                        )
            return result
        finally:
            self.open_cost, self.close_cost = old_open, old_close

    def _clip_amount_by_volume(self, order, dealt_order_amount):
        result = super()._clip_amount_by_volume(order, dealt_order_amount)
        if self._active_diagnostic is not None:
            self._active_diagnostic.amount_after_volume = float(order.deal_amount)
        return result

    def round_amount_by_trade_unit(
        self,
        deal_amount: float,
        factor: float | None = None,
        stock_id: str | None = None,
        start_time: pd.Timestamp | None = None,
        end_time: pd.Timestamp | None = None,
    ) -> float:
        del stock_id, start_time, end_time
        builder = self._active_diagnostic
        if builder is None:
            return super().round_amount_by_trade_unit(deal_amount, factor)
        if factor is None or factor <= 0:
            raise ValueError("Qlib order factor must be positive for KRX lot rounding")
        lot = self._lot_size[builder.instrument_id]
        physical_amount = float(deal_amount) * float(factor)
        rounded_physical = (
            np.floor((physical_amount + 1e-10) / lot) * lot
        )
        rounded = float(rounded_physical / float(factor))
        if builder.direction == Order.BUY:
            builder.amount_after_position = float(
                builder.amount_after_volume
                if builder.amount_after_volume is not None
                else deal_amount
            )
        else:
            builder.amount_after_position = float(deal_amount)
        if builder.amount_after_cash is None:
            builder.amount_after_cash = float(deal_amount)
        builder.amount_after_lot = rounded
        return rounded

    def _tradability_reason(self, order) -> str | None:
        close = self._quote_value(order, "$close")
        if not np.isfinite(close) or close <= 0:
            return "invalid_price"
        if self._quote_bool(order, "$suspended"):
            return "suspended"
        if order.direction == Order.BUY and self._quote_bool(
            order, "$upper_price_limit"
        ):
            return "upper_price_limit"
        if order.direction == Order.SELL and self._quote_bool(
            order, "$lower_price_limit"
        ):
            return "lower_price_limit"
        if order.direction == Order.BUY and self._quote_bool(order, "$limit_buy"):
            return "buy_blocked"
        if order.direction == Order.SELL and self._quote_bool(order, "$limit_sell"):
            return "sell_blocked"
        return None

    def _quote_bool(self, order, field: str) -> bool:
        return bool(self._quote_value(order, field))

    def _quote_value(self, order, field: str) -> float:
        value = self.quote.get_data(
            order.stock_id,
            order.start_time,
            order.end_time,
            field=field,
            method="ts_data_last",
        )
        return float(value)


def build_quote_frame(
    execution_price: pd.DataFrame,
    position_unit_factor: pd.DataFrame,
    volume: pd.DataFrame,
    buyable: pd.DataFrame,
    sellable: pd.DataFrame,
    suspended: pd.DataFrame,
    upper_price_limit: pd.DataFrame,
    lower_price_limit: pd.DataFrame,
    *,
    max_volume_participation: float | None,
    valuation_price: pd.DataFrame | None = None,
) -> pd.DataFrame:
    qlib_deal_price = (
        execution_price.astype("float64") * position_unit_factor.astype("float64")
    )
    close_price = execution_price if valuation_price is None else valuation_price
    qlib_close_price = (
        close_price.astype("float64") * position_unit_factor.astype("float64")
    )
    qlib_volume = volume.astype("float64") / position_unit_factor.astype("float64")
    if max_volume_participation is None:
        volume_limit = qlib_volume
    else:
        volume_limit = qlib_volume * float(max_volume_participation)
    change = qlib_close_price.pct_change(fill_method=None).fillna(0.0)
    matrices = {
        "$close": qlib_close_price,
        "$deal_price": qlib_deal_price,
        "$change": change,
        "$factor": position_unit_factor.astype("float64"),
        "$volume": qlib_volume,
        "$volume_limit": volume_limit,
        "$limit_buy": ~buyable.astype(bool),
        "$limit_sell": ~sellable.astype(bool),
        "$suspended": suspended.astype(bool),
        "$upper_price_limit": upper_price_limit.astype(bool),
        "$lower_price_limit": lower_price_limit.astype(bool),
    }
    series = {name: _stack(matrix) for name, matrix in matrices.items()}
    return _validate_quote_frame(pd.DataFrame(series).swaplevel().sort_index())


def _stack(matrix: pd.DataFrame) -> pd.Series:
    named = matrix.copy()
    named.index = named.index.rename("datetime")
    named.columns = named.columns.rename("instrument")
    return named.stack(future_stack=True)


def _validate_quote_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(frame.index, pd.MultiIndex):
        raise TypeError("quote_frame index must be a MultiIndex")
    if list(frame.index.names) != ["instrument", "datetime"]:
        raise ValueError("quote_frame index names must be instrument, datetime")
    if frame.index.has_duplicates:
        raise ValueError("quote_frame index must be unique")
    required = {
        "$close",
        "$change",
        "$factor",
        "$volume",
        "$volume_limit",
        "$limit_buy",
        "$limit_sell",
        "$suspended",
        "$upper_price_limit",
        "$lower_price_limit",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise KeyError(f"quote_frame is missing fields: {missing}")
    return frame.sort_index()


def _build_policies(
    cost_policy: Mapping[str, Mapping[str, float]],
) -> dict[str, KrxExecutionPolicy]:
    policies: dict[str, KrxExecutionPolicy] = {}
    for asset_class, values in cost_policy.items():
        rates = {
            name: float(values[name])
            for name in ("buy_rate", "sell_rate", "sell_tax")
        }
        if not np.isfinite(np.asarray(list(rates.values()))).all() or any(
            value < 0 for value in rates.values()
        ):
            raise ValueError(
                f"execution cost rates must be finite and non-negative: {asset_class}"
            )
        policies[str(asset_class)] = KrxExecutionPolicy(
            asset_class=str(asset_class),
            **rates,
            allow_short=False,
        )
    return policies


def _finalize_diagnostic(
    builder: _DiagnosticBuilder, filled_amount: float
) -> ExecutionDiagnostic:
    requested = builder.requested_amount
    if not np.isfinite(filled_amount) or filled_amount < -1e-10:
        raise RuntimeError("Qlib returned an invalid filled amount")
    filled_amount = max(float(filled_amount), 0.0)
    if builder.tradability_reason is not None:
        if filled_amount > 1e-10:
            raise RuntimeError("Qlib filled an order marked non-tradable")
        after_tradability = 0.0
        after_volume = 0.0
        after_position = 0.0
        after_cash = 0.0
        after_lot = 0.0
        reason_code = builder.tradability_reason
        blocked_by = "tradability"
    else:
        after_tradability = requested
        after_volume = _bounded_stage(
            builder.amount_after_volume, after_tradability, "volume"
        )
        after_position = _bounded_stage(
            builder.amount_after_position, after_volume, "position"
        )
        after_cash = _bounded_stage(
            builder.amount_after_cash, after_position, "cash"
        )
        planned_after_lot = _bounded_stage(
            builder.amount_after_lot, after_cash, "lot"
        )
        if filled_amount > planned_after_lot + 1e-10:
            raise RuntimeError(
                "Qlib filled amount exceeds the instrumented execution stages"
            )
        execution_limited = _less(filled_amount, planned_after_lot)
        after_lot = filled_amount
        if execution_limited:
            reason_code, blocked_by = "execution_limited", "qlib_execution"
        elif _less(after_cash, after_position):
            reason_code, blocked_by = "cash_limited", "cash"
        elif _less(after_position, after_volume):
            reason_code, blocked_by = "position_limited", "position"
        elif _less(after_volume, after_tradability):
            reason_code, blocked_by = "volume_limited", "volume"
        elif _less(after_lot, after_cash):
            reason_code, blocked_by = "lot_rounded", "lot"
        else:
            reason_code, blocked_by = "filled", None
    return ExecutionDiagnostic(
        reason_code=reason_code,
        blocked_by=blocked_by,
        requested_amount=requested,
        amount_after_tradability=after_tradability,
        amount_after_volume=after_volume,
        amount_after_position=after_position,
        amount_after_cash=after_cash,
        amount_after_lot=after_lot,
        filled_amount=filled_amount,
        asset_class=builder.asset_class,
        execution_policy=builder.execution_policy,
        effective_cost_rate=builder.effective_cost_rate,
        short_enabled=builder.short_enabled,
    )


def _less(left: float, right: float) -> bool:
    return left < right - 1e-10


def _bounded_stage(value: float | None, upper: float, stage: str) -> float:
    amount = float(upper if value is None else value)
    if not np.isfinite(amount) or amount < -1e-10 or amount > upper + 1e-10:
        raise RuntimeError(f"Qlib {stage} diagnostic is not monotone")
    return min(max(amount, 0.0), float(upper))
