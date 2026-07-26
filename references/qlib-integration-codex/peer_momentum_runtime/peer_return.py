from __future__ import annotations

import numpy as np
import pandas as pd


# 역할: Qlib peer-momentum twin이 소유하는 독립 peer return 계산입니다.
# 책임:
# - production src 구현을 import하지 않고 leave-one-out EW/VW peer return을 계산합니다.
# - twin 입력의 축과 universe contract를 명시적으로 검증합니다.


def compute_peer_return(
    returns: pd.Series,
    peer_groups: pd.Series,
    universe_mask: pd.Series,
    *,
    market_cap: pd.Series | None = None,
) -> pd.Series:
    """한 cross-section의 leave-one-out peer return을 계산합니다."""

    _validate_same_index(returns, peer_groups, "returns", "peer_groups")
    _validate_same_index(returns, universe_mask, "returns", "universe_mask")
    numeric_returns = pd.to_numeric(returns, errors="coerce").astype("float64")
    valid = universe_mask.fillna(False).astype(bool)
    valid &= numeric_returns.notna() & peer_groups.notna()
    if market_cap is None:
        return _compute_equal_weight_peer_return(
            numeric_returns,
            peer_groups,
            valid,
        )
    _validate_same_index(returns, market_cap, "returns", "market_cap")
    return _compute_value_weight_peer_return(
        numeric_returns,
        peer_groups,
        pd.to_numeric(market_cap, errors="coerce").astype("float64"),
        valid,
    )


def _compute_equal_weight_peer_return(
    returns: pd.Series,
    peer_groups: pd.Series,
    valid: pd.Series,
) -> pd.Series:
    result = pd.Series(np.nan, index=returns.index, dtype="float64")
    valid_returns = returns.where(valid)
    group_sum = valid_returns.groupby(peer_groups, dropna=True).transform("sum")
    group_count = valid_returns.groupby(peer_groups, dropna=True).transform("count")
    peer_count = group_count - 1
    eligible = valid & peer_count.ge(1)
    result.loc[eligible] = ((group_sum - returns) / peer_count).loc[eligible]
    return result


def _compute_value_weight_peer_return(
    returns: pd.Series,
    peer_groups: pd.Series,
    market_cap: pd.Series,
    valid: pd.Series,
) -> pd.Series:
    result = pd.Series(np.nan, index=returns.index, dtype="float64")
    weight_eligible = valid & market_cap.gt(0.0) & market_cap.notna()
    weighted_return = (returns * market_cap).where(weight_eligible)
    valid_weight = market_cap.where(weight_eligible)
    group_weighted_sum = weighted_return.groupby(
        peer_groups, dropna=True
    ).transform("sum")
    group_weight_sum = valid_weight.groupby(peer_groups, dropna=True).transform("sum")
    group_count = valid_weight.groupby(peer_groups, dropna=True).transform("count")

    own_weight = market_cap.where(weight_eligible, 0.0)
    own_weighted_return = (returns * market_cap).where(weight_eligible, 0.0)
    peer_weight_sum = group_weight_sum - own_weight
    peer_weighted_sum = group_weighted_sum - own_weighted_return
    peer_count = group_count - weight_eligible.astype(int)
    eligible = valid & peer_count.ge(1) & peer_weight_sum.gt(0.0)
    result.loc[eligible] = (peer_weighted_sum / peer_weight_sum).loc[eligible]
    return result


def _validate_same_index(
    left: pd.Series,
    right: pd.Series,
    left_name: str,
    right_name: str,
) -> None:
    if not left.index.equals(right.index):
        raise ValueError(f"{left_name} and {right_name} must have identical index.")
