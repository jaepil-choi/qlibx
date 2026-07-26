from __future__ import annotations

import numpy as np
import pandas as pd
from qlib.backtest.exchange import Exchange


class DataFrameExchange(Exchange):
    """Qlib execution/accounting을 plain pandas quote와 연결하는 실험용 Exchange."""

    def __init__(self, *, quote_frame: pd.DataFrame, **kwargs) -> None:
        self._direct_quote_frame = _validate_quote_frame(quote_frame)
        super().__init__(**kwargs)

    def get_quote_from_qlib(self) -> None:
        """Feature provider 조회만 대체하고 Qlib의 fill/cost/accounting은 그대로 씁니다."""

        missing = sorted(set(self.all_fields) - set(self._direct_quote_frame.columns))
        if missing:
            raise KeyError(f"Direct quote frame is missing Qlib fields: {missing}")
        self.quote_df = self._direct_quote_frame.loc[:, self.all_fields].copy()
        for price_field in {self.buy_price, self.sell_price, "$close"}:
            if self.quote_df[price_field].notna().sum() == 0:
                raise ValueError(f"Quote field has no usable values: {price_field}")

        has_missing_factor = self.quote_df["$factor"].isna() & self.quote_df[
            "$close"
        ].notna()
        self.trade_w_adj_price = bool(has_missing_factor.any())
        self._update_limit(self.limit_threshold)


def build_quote_frame(
    adjusted_close: pd.DataFrame,
    returns: pd.DataFrame,
    trade_volume: pd.DataFrame,
) -> pd.DataFrame:
    """date x ticker matrix를 Qlib Exchange quote MultiIndex frame으로 바꿉니다."""

    for name, matrix in {
        "returns": returns,
        "trade_volume": trade_volume,
    }.items():
        if not matrix.index.equals(adjusted_close.index) or not matrix.columns.equals(
            adjusted_close.columns
        ):
            raise ValueError(f"{name} axes must match adjusted_close.")

    frame = pd.DataFrame(
        {
            "$close": _stack_complete(adjusted_close),
            "$change": _stack_complete(returns),
            "$volume": _stack_complete(trade_volume),
        }
    )
    frame["$factor"] = np.where(frame["$close"].notna(), 1.0, np.nan)
    frame = frame.swaplevel("datetime", "instrument").sort_index()
    return _validate_quote_frame(frame)


def _stack_complete(matrix: pd.DataFrame) -> pd.Series:
    named = matrix.copy()
    named.index = named.index.rename("datetime")
    named.columns = named.columns.rename("instrument")
    return named.stack(future_stack=True)


def _validate_quote_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(frame.index, pd.MultiIndex):
        raise TypeError("quote_frame index must be a MultiIndex.")
    if list(frame.index.names) != ["instrument", "datetime"]:
        raise ValueError(
            "quote_frame index names must be ['instrument', 'datetime']."
        )
    if frame.index.has_duplicates:
        raise ValueError("quote_frame index must not contain duplicates.")
    required = {"$close", "$change", "$factor", "$volume"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise KeyError(f"quote_frame is missing required fields: {missing}")
    return frame.sort_index()
