from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Mapping

import numpy as np
import pandas as pd

from .config import BacktestConfig
from .portfolio import build_long_only_targets


@dataclass(frozen=True)
class ExecutionContext:
    execution_price: pd.DataFrame
    universe: pd.DataFrame
    benchmark_weight: pd.DataFrame
    position_unit_factor: pd.DataFrame | None = None
    valuation_price: pd.DataFrame | None = None
    observed: pd.DataFrame | None = None
    tradable: pd.DataFrame | None = None
    shortable: pd.DataFrame | None = None
    volume: pd.DataFrame | None = None
    asset_class: pd.Series | None = None
    lot_size: pd.Series | None = None


@dataclass(frozen=True)
class BacktestOutput:
    artifacts: Mapping[str, pd.DataFrame]
    metadata: Mapping[str, object]


def run_qlib_backtest(
    alpha: pd.DataFrame,
    config: BacktestConfig,
    context: ExecutionContext,
) -> BacktestOutput:
    from kwam_qlib_backend.backend import QlibClosedLoopBackend

    enhanced = config.enhanced_index
    if config.target_semantics == "enhanced_index":
        if enhanced is None:
            raise RuntimeError("enhanced_index config lost enhanced_index settings")
        constituent_like = pd.DataFrame(
            index=context.execution_price.index,
            columns=pd.Index(
                [str(name) for name in enhanced.lookthrough],
                name=context.benchmark_weight.columns.name,
            ),
        )
        normalized_alpha = _align_alpha(alpha, constituent_like)
    else:
        normalized_alpha = _align_alpha(alpha, context.execution_price)
    universe = _align_matrix(context.universe, context.execution_price, "universe").astype(bool)
    factor = (
        pd.DataFrame(
            1.0,
            index=context.execution_price.index,
            columns=context.execution_price.columns,
        )
        if context.position_unit_factor is None
        else _align_matrix(
            context.position_unit_factor,
            context.execution_price,
            "position_unit_factor",
        ).astype("float64")
    )
    benchmark = _align_matrix(
        context.benchmark_weight,
        normalized_alpha if config.target_semantics == "enhanced_index" else context.execution_price,
        "benchmark_weight",
    ).astype("float64")
    signed_alpha = normalized_alpha.shift(config.signal_lag, fill_value=0.0)
    if config.target_semantics == "long_only":
        targets = build_long_only_targets(
            normalized_alpha,
            universe,
            signal_lag=config.signal_lag,
            top_n=config.top_n,
            gross_exposure=config.gross_exposure,
        )
    elif config.target_semantics == "target_weight":
        targets = _validate_target_weights(signed_alpha.where(universe, 0.0))
    else:
        targets = pd.DataFrame(0.0, index=normalized_alpha.index, columns=normalized_alpha.columns)
        if config.target_semantics == "enhanced_index":
            targets = pd.DataFrame(
                0.0,
                index=context.execution_price.index,
                columns=context.execution_price.columns,
            )
    volume = (
        None
        if context.volume is None
        else _align_matrix(context.volume, context.execution_price, "volume").astype(
            "float64"
        )
    )
    tradable = (
        None
        if context.tradable is None
        else _align_matrix(
            context.tradable, context.execution_price, "tradable"
        ).astype(bool)
    )
    physical_index = pd.Index(context.execution_price.columns, name="instrument_id")
    asset_class = (
        pd.Series("stock", index=physical_index, dtype="object")
        if context.asset_class is None
        else context.asset_class.reindex(physical_index)
    )
    lot_size = (
        pd.Series(1, index=physical_index, dtype="int64")
        if context.lot_size is None
        else context.lot_size.reindex(physical_index)
    )
    scenario = SimpleNamespace(
        execution_price=context.execution_price.astype("float64"),
        valuation_price=(
            None
            if context.valuation_price is None
            else _align_matrix(
                context.valuation_price,
                context.execution_price,
                "valuation_price",
            ).astype("float64")
        ),
        universe=universe,
        booksize=config.initial_cash,
        active_booksize=(
            config.initial_cash
            if config.matched_capitalization is None
            or config.matched_capitalization.active_booksize is None
            else config.matched_capitalization.active_booksize
        ),
        position_unit_factor=factor,
        volume=volume,
        buyable=tradable,
        sellable=tradable,
        asset_class=asset_class,
        lot_size=lot_size,
        cost_policy=config.cost_policy,
        max_volume_participation=config.execution.max_volume_participation,
        suspended=None,
        upper_price_limit=None,
        lower_price_limit=None,
    )
    matched_inputs = None
    if config.target_semantics == "signed_weight":
        from kwam_qlib_backend.backend import MatchedCapitalizationInputs

        matched = config.matched_capitalization
        if matched is None:
            raise RuntimeError("signed_weight config lost matched_capitalization")
        if context.observed is None or context.shortable is None or tradable is None:
            raise RuntimeError("signed_weight execution context is incomplete")
        matched_inputs = MatchedCapitalizationInputs(
            signed_weights=signed_alpha,
            observed=_align_matrix(
                context.observed, context.execution_price, "observed"
            ).astype(bool),
            shortable=_align_matrix(
                context.shortable, context.execution_price, "shortable"
            ).astype(bool),
            per_name_short_cap=matched.per_name_short_cap,
            safety_multiplier=matched.safety_multiplier,
            inventory_retention=matched.inventory_retention,
        )
    enhanced_policy = None
    if config.target_semantics == "enhanced_index":
        from .enhanced import EnhancedIndexTargetPolicy

        if enhanced is None:
            raise RuntimeError("enhanced_index config lost enhanced_index settings")
        physical_tradable = universe if tradable is None else universe & tradable
        enhanced_policy = EnhancedIndexTargetPolicy(
            desired_active_exposure=signed_alpha,
            benchmark_weight=benchmark,
            physical_tradable=physical_tradable,
            config=enhanced,
        )
    result = QlibClosedLoopBackend().run_targets(
        scenario,
        targets,
        signals={"alpha": normalized_alpha},
        matched_capitalization=matched_inputs,
        target_policy=enhanced_policy,
    )
    account = result.account_daily().rename_axis("trade_date").reset_index()
    artifacts = {
        "account_daily": account,
        "orders": result.orders(),
        "fills": result.fills(),
        "positions": result.positions(),
        "target_weights": targets,
        "execution_price": context.execution_price,
        "valuation_price": (
            context.execution_price
            if context.valuation_price is None
            else scenario.valuation_price
        ),
        "position_unit_factor": factor,
        "universe": universe,
        "benchmark_weight": benchmark,
        "instrument_contract": pd.DataFrame(
            {
                "asset_class": asset_class.astype("object"),
                "lot_size": lot_size.astype("int64"),
            },
            index=physical_index,
        ),
    }
    if config.target_semantics == "signed_weight":
        artifacts["target_weights"] = signed_alpha.where(universe, 0.0)
        artifacts.update(result.extra_tables)
        artifacts.update(
            {
                "observed": matched_inputs.observed,
                "tradable": tradable,
                "shortable": matched_inputs.shortable,
            }
        )
    if config.target_semantics == "enhanced_index":
        if enhanced_policy is None:
            raise RuntimeError("enhanced-index target policy is missing")
        artifacts.update(
            {
                "target_weights": result.decision_weights,
                "desired_active_exposure": signed_alpha,
                "lookthrough_matrix": enhanced_policy.lookthrough,
                "optimizer_daily": pd.DataFrame(enhanced_policy.daily_rows),
                "optimizer_constituent_daily": pd.DataFrame(
                    enhanced_policy.constituent_rows
                ),
                "optimizer_physical_daily": pd.DataFrame(
                    enhanced_policy.physical_rows
                ),
            }
        )
    if volume is not None:
        artifacts["volume"] = volume
    evidence = result.backend_evidence()
    metadata = {
        "execution_backend": evidence["execution_backend"],
        "qlib_version": evidence["qlib_version"],
        "result_hash": evidence["result_hash"],
    }
    return BacktestOutput(artifacts=artifacts, metadata=metadata)


def _align_alpha(alpha: pd.DataFrame, like: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(alpha, pd.DataFrame):
        raise TypeError("strategy callable must return a pandas DataFrame")
    matrix = alpha.copy()
    if not isinstance(matrix.index, pd.DatetimeIndex):
        raise TypeError("alpha index must be a DatetimeIndex")
    matrix.columns = pd.Index(matrix.columns.astype(str), name=like.columns.name)
    if not matrix.index.equals(like.index) or set(matrix.columns) != set(like.columns):
        raise ValueError("alpha axes must match execution_price")
    return matrix.reindex(columns=like.columns).astype("float64")


def _validate_target_weights(target: pd.DataFrame) -> pd.DataFrame:
    values = target.to_numpy(dtype="float64")
    if not np.isfinite(values).all() or not (values >= -1e-10).all():
        raise ValueError("target_weight must contain finite non-negative weights")
    normalized = target.clip(lower=0.0).astype("float64")
    row_sum = normalized.sum(axis=1)
    if row_sum.gt(1.0 + 1e-8).any():
        raise ValueError(
            "target_weight rows must not exceed the fully-invested budget: "
            f"max_sum={float(row_sum.max())}"
        )
    return normalized


def _align_matrix(matrix: pd.DataFrame, like: pd.DataFrame, name: str) -> pd.DataFrame:
    normalized = matrix.copy()
    normalized.columns = pd.Index(normalized.columns.astype(str), name=like.columns.name)
    if not normalized.index.equals(like.index) or set(normalized.columns) != set(like.columns):
        raise ValueError(f"{name} axes must match execution_price")
    return normalized.reindex(columns=like.columns)
