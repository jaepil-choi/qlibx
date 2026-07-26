from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import numpy as np
import pandas as pd
from qlib.backtest.decision import Order
from qlib.backtest.exchange import Exchange


# 역할: 실제 pandas market data를 Qlib Exchange execution path에 공급합니다.
# 책임:
# - stock/ETF별 KRX 비용과 lot 정책을 Qlib deal_order에 적용합니다.
# - 주문 결과를 별도 체결 계산 없이 Qlib order 결과에서 기록합니다.


@dataclass(frozen=True)
class KrxCostPolicy:
    buy_rate: float
    sell_rate: float
    sell_tax: float

    def rate(self, direction: int) -> float:
        return self.buy_rate if direction == Order.BUY else self.sell_rate + self.sell_tax


class KrxPandasExchange(Exchange):
    """Qlib execution/accounting을 실제 project pandas quote와 연결합니다."""

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
        self._asset_class = {str(key): str(value) for key, value in asset_class.items()}
        self._cost_policy = _build_cost_policy(cost_policy)
        self._lot_size = {str(key): int(value) for key, value in lot_size.items()}
        self._active_instrument: str | None = None
        self.execution_history: list[dict[str, object]] = []
        _validate_instrument_policy(
            self._direct_quote_frame,
            self._asset_class,
            self._cost_policy,
            self._lot_size,
        )
        super().__init__(**kwargs)

    def get_quote_from_qlib(self) -> None:
        missing = sorted(set(self.all_fields) - set(self._direct_quote_frame.columns))
        if missing:
            raise KeyError(f"Direct quote frame is missing Qlib fields: {missing}")
        self.quote_df = self._direct_quote_frame.loc[:, self.all_fields].copy()
        self.trade_w_adj_price = False
        self._update_limit(self.limit_threshold)

    def is_stock_tradable(
        self,
        stock_id: str,
        start_time: pd.Timestamp,
        end_time: pd.Timestamp,
        direction: int | None = None,
    ) -> bool:
        if direction is not None:
            return super().is_stock_tradable(
                stock_id,
                start_time,
                end_time,
                direction,
            )
        if self.check_stock_suspended(stock_id, start_time, end_time):
            return False
        # Qlib OrderGenWInteract는 주문 방향을 정하기 전에 이 method를
        # 호출합니다. 한쪽만 제한된 경우까지 False로 반환하면 buy 제한이
        # universe-exit sell order 생성도 막으므로, 양방향이 모두 막힌
        # 경우에만 generic non-tradable로 판정합니다.
        buy_limited = self.check_stock_limit(
            stock_id,
            start_time,
            end_time,
            Order.BUY,
        )
        sell_limited = self.check_stock_limit(
            stock_id,
            start_time,
            end_time,
            Order.SELL,
        )
        return not (buy_limited and sell_limited)

    def deal_order(
        self,
        order,
        trade_account=None,
        position=None,
        dealt_order_amount=None,
    ):
        self._active_instrument = str(order.stock_id)
        requested_amount = float(order.amount)
        try:
            trade_value, trade_cost, trade_price = super().deal_order(
                order,
                trade_account=trade_account,
                position=position,
                dealt_order_amount=(
                    {} if dealt_order_amount is None else dealt_order_amount
                ),
            )
        finally:
            self._active_instrument = None
        asset_class = self._asset_class[str(order.stock_id)]
        factor = float(order.factor)
        if not np.isfinite(factor) or factor <= 0.0:
            raise RuntimeError(
                "Qlib completed an order without a finite positive position factor."
            )
        self.execution_history.append(
            {
                "trade_date": pd.Timestamp(order.start_time).normalize(),
                "instrument_id": str(order.stock_id),
                "direction": "buy" if order.direction == Order.BUY else "sell",
                "requested_adjusted_amount": requested_amount,
                "filled_adjusted_amount": float(order.deal_amount),
                "position_unit_factor": factor,
                "requested_quantity": requested_amount * factor,
                "filled_quantity": float(order.deal_amount) * factor,
                "trade_value": float(trade_value),
                "trade_cost": float(trade_cost),
                "trade_price": float(trade_price),
                "asset_class": asset_class,
                "effective_cost_rate": self._cost_policy[asset_class].rate(
                    order.direction
                ),
            }
        )
        return trade_value, trade_cost, trade_price

    def _calc_trade_info_by_order(self, order, position, dealt_order_amount):
        asset_class = self._asset_class[str(order.stock_id)]
        policy = self._cost_policy[asset_class]
        previous_open, previous_close = self.open_cost, self.close_cost
        self.open_cost = policy.buy_rate
        self.close_cost = policy.sell_rate + policy.sell_tax
        try:
            return super()._calc_trade_info_by_order(
                order,
                position,
                dealt_order_amount,
            )
        finally:
            self.open_cost, self.close_cost = previous_open, previous_close

    def round_amount_by_trade_unit(
        self,
        deal_amount: float,
        factor: float | None = None,
        stock_id: str | None = None,
        start_time: pd.Timestamp | None = None,
        end_time: pd.Timestamp | None = None,
    ) -> float:
        del start_time, end_time
        instrument = stock_id or self._active_instrument
        if instrument is None:
            return super().round_amount_by_trade_unit(deal_amount, factor)
        if factor is None or not np.isfinite(factor) or factor <= 0.0:
            raise ValueError("Qlib order factor must be finite and positive.")
        lot = self._lot_size[str(instrument)]
        physical_amount = float(deal_amount) * float(factor)
        rounded_physical = np.floor((physical_amount + 1e-10) / lot) * lot
        return float(rounded_physical / float(factor))


def build_quote_frame(
    execution_price: pd.DataFrame,
    position_unit_factor: pd.DataFrame,
    volume: pd.DataFrame,
    buyable: pd.DataFrame,
    sellable: pd.DataFrame,
    suspended: pd.DataFrame,
    *,
    max_volume_participation: float | None,
) -> pd.DataFrame:
    matrices = {
        "position_unit_factor": position_unit_factor,
        "volume": volume,
        "buyable": buyable,
        "sellable": sellable,
        "suspended": suspended,
    }
    for name, matrix in matrices.items():
        if not matrix.index.equals(execution_price.index) or not matrix.columns.equals(
            execution_price.columns
        ):
            raise ValueError(f"{name} axes must match execution_price.")
    if max_volume_participation is not None and not (
        0.0 < float(max_volume_participation) <= 1.0
    ):
        raise ValueError("max_volume_participation must be in (0, 1].")

    qlib_price = execution_price.astype("float64") * position_unit_factor.astype(
        "float64"
    )
    qlib_volume = volume.astype("float64") / position_unit_factor.astype("float64")
    volume_limit = (
        qlib_volume
        if max_volume_participation is None
        else qlib_volume * float(max_volume_participation)
    )
    # 거래정지로 universe에서 빠진 보유종목은 production holdings ledger처럼
    # 마지막 유효가격에서 전량 exit할 수 있어야 합니다. buyable=False가 신규
    # 매수를 차단하므로 이 예외는 sell order에만 영향을 줍니다.
    forced_exit = suspended.astype(bool) & sellable.astype(bool)
    volume_limit = volume_limit.mask(forced_exit, np.inf)
    fields = {
        "$close": qlib_price,
        "$change": qlib_price.pct_change(fill_method=None).fillna(0.0),
        "$factor": position_unit_factor.astype("float64"),
        "$volume": qlib_volume,
        "$volume_limit": volume_limit,
        "$limit_buy": ~buyable.astype(bool),
        "$limit_sell": ~sellable.astype(bool),
        "$suspended": suspended.astype(bool),
    }
    frame = pd.DataFrame({name: _stack(matrix) for name, matrix in fields.items()})
    return _validate_quote_frame(frame.swaplevel().sort_index())


def _stack(matrix: pd.DataFrame) -> pd.Series:
    named = matrix.copy()
    named.index = named.index.rename("datetime")
    named.columns = named.columns.rename("instrument")
    return named.stack(future_stack=True)


def _validate_quote_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(frame.index, pd.MultiIndex):
        raise TypeError("quote_frame index must be a MultiIndex.")
    if list(frame.index.names) != ["instrument", "datetime"]:
        raise ValueError("quote_frame index names must be instrument, datetime.")
    if frame.index.has_duplicates:
        raise ValueError("quote_frame index must be unique.")
    required = {
        "$close",
        "$change",
        "$factor",
        "$volume",
        "$volume_limit",
        "$limit_buy",
        "$limit_sell",
        "$suspended",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise KeyError(f"quote_frame is missing fields: {missing}")
    return frame.sort_index()


def _build_cost_policy(
    config: Mapping[str, Mapping[str, float]],
) -> dict[str, KrxCostPolicy]:
    result: dict[str, KrxCostPolicy] = {}
    for asset_class, values in config.items():
        missing = {"buy_rate", "sell_rate", "sell_tax"} - set(values)
        if missing:
            raise KeyError(
                f"Cost policy for {asset_class} is missing fields: {sorted(missing)}"
            )
        policy = KrxCostPolicy(
            buy_rate=float(values["buy_rate"]),
            sell_rate=float(values["sell_rate"]),
            sell_tax=float(values["sell_tax"]),
        )
        rates = np.asarray(
            [policy.buy_rate, policy.sell_rate, policy.sell_tax], dtype="float64"
        )
        if not np.isfinite(rates).all() or (rates < 0.0).any():
            raise ValueError(f"Cost policy rates must be finite and non-negative: {asset_class}")
        result[str(asset_class)] = policy
    return result


def _validate_instrument_policy(
    quote_frame: pd.DataFrame,
    asset_class: Mapping[str, str],
    cost_policy: Mapping[str, KrxCostPolicy],
    lot_size: Mapping[str, int],
) -> None:
    instruments = pd.Index(
        quote_frame.index.get_level_values("instrument").unique().astype(str)
    )
    missing_asset = instruments.difference(pd.Index(asset_class))
    missing_lot = instruments.difference(pd.Index(lot_size))
    if len(missing_asset):
        raise ValueError(f"asset_class is missing instruments: {missing_asset.tolist()}")
    if len(missing_lot):
        raise ValueError(f"lot_size is missing instruments: {missing_lot.tolist()}")
    unknown_classes = sorted(set(asset_class.values()) - set(cost_policy))
    if unknown_classes:
        raise ValueError(f"Missing cost policies for asset classes: {unknown_classes}")
    invalid_lot = {key: value for key, value in lot_size.items() if int(value) <= 0}
    if invalid_lot:
        raise ValueError(f"lot_size must contain positive integers: {invalid_lot}")
