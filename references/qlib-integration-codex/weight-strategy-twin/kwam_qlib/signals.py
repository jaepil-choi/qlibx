from __future__ import annotations

import math

import numpy as np
import pandas as pd


def compute_equal_weight_peer_momentum(
    returns: pd.DataFrame,
    peer_groups: pd.DataFrame,
    universe_mask: pd.DataFrame,
) -> pd.DataFrame:
    """각 종목을 제외한 동일 industry의 당일 평균수익률을 계산합니다.

    기존 ``PeerMomentumSignalStrategy``의 EW raw signal과 같은 계약입니다. Peer가
    한 종목도 없거나 return/group가 결측이면 signal은 NaN으로 남깁니다.
    """

    _validate_same_axes(returns, peer_groups, "returns", "peer_groups")
    _validate_same_axes(returns, universe_mask, "returns", "universe_mask")
    rows = [
        _compute_equal_weight_peer_row(
            pd.to_numeric(returns.loc[date], errors="coerce"),
            peer_groups.loc[date],
            universe_mask.loc[date].astype(bool),
        )
        for date in returns.index
    ]
    return pd.DataFrame(rows, index=returns.index, columns=returns.columns).astype(
        "float64"
    )


def scale_peer_signal(
    signal: pd.Series,
    universe_mask: pd.Series,
    *,
    top_fraction: float | None = None,
) -> pd.Series:
    """기존 full-budget policy처럼 양/음 side를 각각 gross 1로 정규화합니다."""

    if not signal.index.equals(universe_mask.index):
        raise ValueError("signal and universe_mask indices must match.")
    if top_fraction is not None and not 0.0 < top_fraction <= 1.0:
        raise ValueError("top_fraction must be in (0, 1].")

    selected = pd.to_numeric(signal, errors="coerce").where(
        universe_mask.astype(bool)
    )
    if top_fraction is not None:
        valid = selected.dropna()
        if not valid.empty:
            keep_count = max(1, math.ceil(len(valid) * top_fraction))
            keep = valid.abs().nlargest(keep_count, keep="all").index
            selected = selected.where(selected.index.isin(keep))

    weight = pd.Series(0.0, index=signal.index, dtype="float64")
    positive = selected[selected.gt(0.0)]
    if not positive.empty and positive.sum() > 0.0:
        weight.loc[positive.index] = positive / positive.sum()
    negative = selected[selected.lt(0.0)]
    if not negative.empty and negative.abs().sum() > 0.0:
        weight.loc[negative.index] = negative / negative.abs().sum()
    return weight


def build_long_only_target(
    signal: pd.Series,
    benchmark_weight: pd.Series,
    universe_mask: pd.Series,
    *,
    active_multiplier: float,
    top_fraction: float | None = None,
) -> tuple[pd.Series, pd.Series]:
    """BM + scaled peer alpha를 Qlib 현물 장부용 long-only target으로 바꿉니다.

    Qlib ``Position``은 현물 long-only이므로 signed active book을 직접 보유하지 않습니다.
    기존 full-budget peer alpha를 ``active_multiplier``만큼 benchmark에 더한 뒤 음수를
    0으로 자르고 investable universe 안에서 다시 100%로 정규화합니다.
    """

    if not np.isfinite(active_multiplier) or active_multiplier < 0.0:
        raise ValueError("active_multiplier must be a non-negative finite number.")
    if not (
        signal.index.equals(benchmark_weight.index)
        and signal.index.equals(universe_mask.index)
    ):
        raise ValueError("signal, benchmark_weight, and universe_mask indices must match.")

    investable = universe_mask.astype(bool)
    benchmark = (
        pd.to_numeric(benchmark_weight, errors="coerce")
        .fillna(0.0)
        .clip(lower=0.0)
        .where(investable, 0.0)
    )
    benchmark_total = float(benchmark.sum())
    if benchmark_total <= 0.0:
        raise ValueError("benchmark_weight must have positive mass in the universe.")
    benchmark = benchmark / benchmark_total

    active = scale_peer_signal(
        signal,
        investable,
        top_fraction=top_fraction,
    )
    target = (benchmark + active_multiplier * active).clip(lower=0.0)
    target = target.where(investable, 0.0)
    target_total = float(target.sum())
    if target_total <= 0.0:
        raise ValueError("long-only target has no positive mass.")
    return (target / target_total).astype("float64"), active.astype("float64")


def _compute_equal_weight_peer_row(
    returns: pd.Series,
    peer_groups: pd.Series,
    universe_mask: pd.Series,
) -> pd.Series:
    result = pd.Series(np.nan, index=returns.index, dtype="float64")
    valid = universe_mask & returns.notna() & peer_groups.notna()
    valid_returns = returns.where(valid)
    group_sum = valid_returns.groupby(peer_groups, dropna=True).transform("sum")
    group_count = valid_returns.groupby(peer_groups, dropna=True).transform("count")
    peer_count = group_count - 1
    peer_sum = group_sum - returns
    eligible = valid & peer_count.ge(1)
    result.loc[eligible] = (peer_sum / peer_count).loc[eligible]
    return result


def _validate_same_axes(
    left: pd.DataFrame,
    right: pd.DataFrame,
    left_name: str,
    right_name: str,
) -> None:
    if not left.index.equals(right.index) or not left.columns.equals(right.columns):
        raise ValueError(f"{left_name} and {right_name} axes must match.")
