from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd

from kwam_enhanced_index.portfolio.scale import SideExposureScaler, scale_alpha_weight
from kwam_enhanced_index.strategies.transforms.signal_decay import (
    apply_linear_signal_decay,
)
from peer_momentum_runtime.peer_return import compute_peer_return


def build_signed_peer_momentum_alpha(
    datasets: Mapping[str, pd.DataFrame],
    *,
    decay_window: int = 5,
    decay_dense: bool = False,
    top_fraction: float = 0.05,
    long_exposure: float = 0.25,
    short_exposure: float = 0.25,
    max_abs_weight: float = 0.05,
) -> pd.DataFrame:
    """전일 peer return만 사용해 실행 가능한 signed weight matrix를 만듭니다."""

    required = {"returns", "peer_groups", "universe"}
    missing = sorted(required.difference(datasets))
    if missing:
        raise KeyError(f"peer momentum datasets are missing: {missing}")
    returns = datasets["returns"].copy()
    peer_groups = datasets["peer_groups"].copy()
    universe = datasets["universe"].copy().astype(bool)
    _validate_axes(returns, peer_groups, universe)
    if decay_window <= 0:
        raise ValueError("decay_window must be positive")
    if not 0 < top_fraction <= 1:
        raise ValueError("top_fraction must be in (0, 1]")

    result = pd.DataFrame(0.0, index=returns.index, columns=returns.columns)
    history: list[pd.Series] = []
    scaler = SideExposureScaler(
        long_exposure=float(long_exposure),
        short_exposure=float(short_exposure),
        max_abs_weight=float(max_abs_weight),
    )
    for position, trade_date in enumerate(returns.index):
        if position == 0:
            continue
        observation_date = pd.Timestamp(returns.index[position - 1])
        raw = compute_peer_return(
            returns.loc[observation_date],
            peer_groups.loc[observation_date],
            universe.loc[observation_date],
        )
        decayed, history = apply_linear_signal_decay(
            history=history,
            current_signal=raw,
            decay_window=decay_window,
            dense=decay_dense,
        )
        eligible = (
            universe.loc[observation_date]
            & universe.loc[trade_date]
            & decayed.map(np.isfinite)
        )
        selected = _select_top_fraction(decayed, eligible, top_fraction)
        one_row = pd.DataFrame(
            [selected.to_numpy()],
            index=pd.DatetimeIndex([trade_date]),
            columns=selected.index,
        )
        mask = pd.DataFrame(
            [eligible.to_numpy()],
            index=one_row.index,
            columns=eligible.index,
        )
        result.loc[trade_date] = scale_alpha_weight(
            one_row,
            mask,
            scaler=scaler,
        ).iloc[0]
    return result.astype("float64")


def _select_top_fraction(
    signal: pd.Series,
    eligible: pd.Series,
    top_fraction: float,
) -> pd.Series:
    result = pd.Series(np.nan, index=signal.index, dtype="float64")
    candidates = signal.where(eligible).dropna()
    if candidates.empty:
        return result
    keep_count = max(1, int(np.ceil(len(candidates) * top_fraction)))
    selected = candidates.abs().nlargest(keep_count, keep="all").index
    result.loc[selected] = candidates.loc[selected]
    return result


def _validate_axes(*matrices: pd.DataFrame) -> None:
    first = matrices[0]
    for matrix in matrices[1:]:
        if not matrix.index.equals(first.index) or not matrix.columns.equals(
            first.columns
        ):
            raise ValueError("peer momentum dataset axes must match exactly")
