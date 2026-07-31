"""Independent qlibx StrategyAgent expression of the reference peer momentum."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd

from qlibx.strategy import DecisionContext, DecisionResult, StrategyDefinition, run_decision

DEFINITION = StrategyDefinition(
    strategy_id="peer_momentum.ew_decay.top_kpct.long_short.qlibx",
    name="Peer momentum parity StrategyAgent",
    parameters={
        "decay_window": 5,
        "decay_dense": False,
        "top_fraction": 0.05,
        "long_exposure": 0.25,
        "short_exposure": 0.25,
        "max_abs_weight": 0.05,
    },
    data_requirements=("returns", "peer_groups", "universe"),
    output_kind="weight",
    version="1",
)


def build_qlibx_alpha(
    returns: pd.DataFrame,
    peer_groups: pd.DataFrame,
    universe: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run one qlibx decision per trade date without importing reference code."""

    _validate_axes(returns, peer_groups, universe)
    result = pd.DataFrame(0.0, index=returns.index, columns=returns.columns)
    memory: Mapping[str, Any] = {}
    audit_rows: list[dict[str, Any]] = []
    for position, trade_date in enumerate(returns.index):
        observation = returns.index[position - 1 : position]
        visible_dates = returns.index[max(0, position - 1) : position + 1]
        context = DecisionContext(
            decision_time=pd.Timestamp(trade_date),
            datasets={
                "returns": returns.loc[observation].copy(),
                "peer_groups": peer_groups.loc[observation].copy(),
                "universe": universe.loc[visible_dates].copy(),
            },
            memory=memory,
            dataset_ids={
                "returns": "reference-project-data/returns",
                "peer_groups": "reference-project-data/peer_groups",
                "universe": "reference-project-data/universe",
            },
        )
        decision = run_decision(DEFINITION, peer_momentum_program, context)
        weights = decision.payload.reindex(result.columns).fillna(0.0).astype("float64")
        result.loc[trade_date] = weights
        memory = decision.memory
        audit_rows.append(
            {
                "trade_date": pd.Timestamp(trade_date),
                "observation_date": (pd.NaT if position == 0 else pd.Timestamp(observation[-1])),
                "invocation_id": decision.invocation_id,
                "result_id": decision.result_id,
                **dict(decision.diagnostics),
            }
        )
    return result.astype("float64"), pd.DataFrame(audit_rows)


def peer_momentum_program(
    context: DecisionContext,
    parameters: Mapping[str, Any],
) -> DecisionResult:
    """Previous-bar leave-one-out peer return, sparse linear decay, and side scaling."""

    returns = context.datasets["returns"]
    peer_groups = context.datasets["peer_groups"]
    universe = context.datasets["universe"].astype(bool)
    if returns.empty:
        return DecisionResult(
            "weight",
            pd.Series(0.0, index=universe.columns, dtype="float64"),
            memory=context.memory,
            diagnostics={"eligible_count": 0, "selected_count": 0},
        )
    raw = _compute_peer_return(returns.iloc[-1], peer_groups.iloc[-1], universe.iloc[0])
    raw.name = returns.index[-1]
    history = list(context.memory.get("signal_history", []))
    decayed, history = _linear_decay(
        history,
        raw,
        window=int(parameters["decay_window"]),
        dense=bool(parameters["decay_dense"]),
    )
    eligible = universe.iloc[0] & universe.iloc[-1] & decayed.map(np.isfinite)
    selected = _select_top_fraction(decayed, eligible, float(parameters["top_fraction"]))
    weights = _scale_sides(
        selected,
        eligible,
        long_exposure=float(parameters["long_exposure"]),
        short_exposure=float(parameters["short_exposure"]),
        max_abs_weight=float(parameters["max_abs_weight"]),
    )
    return DecisionResult(
        "weight",
        weights,
        memory={"signal_history": history},
        diagnostics={
            "eligible_count": int(eligible.sum()),
            "selected_count": int(selected.notna().sum()),
            "long_count": int(weights.gt(0.0).sum()),
            "short_count": int(weights.lt(0.0).sum()),
        },
    )


def _compute_peer_return(
    returns: pd.Series,
    peer_groups: pd.Series,
    universe: pd.Series,
) -> pd.Series:
    numeric = pd.to_numeric(returns, errors="coerce").astype("float64")
    valid = universe.fillna(False).astype(bool) & numeric.notna() & peer_groups.notna()
    valid_returns = numeric.where(valid)
    group_sum = valid_returns.groupby(peer_groups, dropna=True).transform("sum")
    group_count = valid_returns.groupby(peer_groups, dropna=True).transform("count")
    peer_count = group_count - 1
    eligible = valid & peer_count.ge(1)
    result = pd.Series(np.nan, index=returns.index, dtype="float64")
    result.loc[eligible] = ((group_sum - numeric) / peer_count).loc[eligible]
    return result


def _linear_decay(
    history: list[pd.Series],
    current: pd.Series,
    *,
    window: int,
    dense: bool,
) -> tuple[pd.Series, list[pd.Series]]:
    updated = [*history, current][-window:]
    frame = pd.concat(updated, axis=1)
    weights = pd.Series(
        np.arange(1, frame.shape[1] + 1, dtype="float64"),
        index=frame.columns,
    )
    weighted = frame.mul(weights, axis=1).sum(axis=1, skipna=not dense)
    if not dense:
        weighted = frame.fillna(0.0).mul(weights, axis=1).sum(axis=1)
    decayed = (weighted / weights.sum()).astype("float64")
    decayed.name = current.name
    return decayed, updated


def _select_top_fraction(
    signal: pd.Series,
    eligible: pd.Series,
    fraction: float,
) -> pd.Series:
    result = pd.Series(np.nan, index=signal.index, dtype="float64")
    candidates = signal.where(eligible).dropna()
    if candidates.empty:
        return result
    keep_count = max(1, int(np.ceil(len(candidates) * fraction)))
    selected = candidates.abs().nlargest(keep_count, keep="all").index
    result.loc[selected] = candidates.loc[selected]
    return result


def _scale_sides(
    signal: pd.Series,
    eligible: pd.Series,
    *,
    long_exposure: float,
    short_exposure: float,
    max_abs_weight: float,
) -> pd.Series:
    values = pd.to_numeric(signal.where(eligible), errors="coerce")
    result = pd.Series(0.0, index=signal.index, dtype="float64")
    positive = values.gt(0.0)
    positive_sum = values.loc[positive].sum()
    if positive_sum > 0.0:
        result.loc[positive] = values.loc[positive] / positive_sum * long_exposure
    negative = values.lt(0.0)
    negative_sum = values.loc[negative].abs().sum()
    if negative_sum > 0.0:
        result.loc[negative] = values.loc[negative] / negative_sum * short_exposure
    return result.clip(lower=-max_abs_weight, upper=max_abs_weight).astype("float64")


def _validate_axes(*matrices: pd.DataFrame) -> None:
    first = matrices[0]
    for matrix in matrices[1:]:
        if not matrix.index.equals(first.index) or not matrix.columns.equals(first.columns):
            raise ValueError("peer momentum matrices must have identical axes")
