from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from kwam_enhanced_index.config import load_config
from kwam_enhanced_index.data.loader import ConfigDrivenDataLoader
from kwam_enhanced_index.data.matrix import pivot_long_to_matrix
from kwam_enhanced_index.universe.masks import build_universe_mask


@dataclass(frozen=True)
class PeerMomentumInputs:
    """비교용 Qlib twin의 실제 project data를 date x ticker 축으로 보관합니다."""

    universe_mask: pd.DataFrame
    returns: pd.DataFrame
    adjusted_close: pd.DataFrame
    adjusted_open: pd.DataFrame
    benchmark_weight: pd.DataFrame
    industry_code: pd.DataFrame
    trade_volume: pd.DataFrame

    @property
    def calendar(self) -> pd.DatetimeIndex:
        return self.universe_mask.index

    @property
    def tickers(self) -> pd.Index:
        return self.universe_mask.columns


def load_peer_momentum_inputs() -> PeerMomentumInputs:
    """기존 config-driven loader를 read-only로 재사용해 Qlib 입력을 만듭니다."""

    config = load_config()
    loader = ConfigDrivenDataLoader.from_project_config(config)
    panel = loader.load_table("base_universe_inputs")
    universe_mask = build_universe_mask(panel).sort_index().sort_index(axis=1)
    trade_volume = pivot_long_to_matrix(panel, "trade_volume")

    matrices = {
        "returns": loader.load_matrix("returns"),
        "adjusted_close": loader.load_matrix("adjusted_close"),
        "adjusted_open": loader.load_matrix("adjusted_open"),
        "benchmark_weight": loader.load_matrix("index_weight"),
        "industry_code": loader.load_matrix("industry_code"),
        "trade_volume": trade_volume,
    }
    aligned = {
        name: _align_like_universe(matrix, universe_mask, name)
        for name, matrix in matrices.items()
    }
    return PeerMomentumInputs(
        universe_mask=universe_mask,
        returns=aligned["returns"].astype("float64"),
        adjusted_close=aligned["adjusted_close"].astype("float64"),
        adjusted_open=aligned["adjusted_open"].astype("float64"),
        benchmark_weight=aligned["benchmark_weight"].astype("float64"),
        industry_code=aligned["industry_code"],
        trade_volume=aligned["trade_volume"].astype("float64"),
    )


def _align_like_universe(
    matrix: pd.DataFrame,
    universe_mask: pd.DataFrame,
    name: str,
) -> pd.DataFrame:
    if not isinstance(matrix.index, pd.DatetimeIndex):
        raise TypeError(f"{name} index must be a DatetimeIndex.")
    if matrix.index.has_duplicates or not matrix.index.is_monotonic_increasing:
        raise ValueError(f"{name} index must be unique and sorted ascending.")
    aligned = matrix.reindex(
        index=universe_mask.index,
        columns=universe_mask.columns,
    )
    if not aligned.index.equals(universe_mask.index) or not aligned.columns.equals(
        universe_mask.columns
    ):
        raise ValueError(f"Failed to align {name} to universe_mask axes.")
    return aligned
