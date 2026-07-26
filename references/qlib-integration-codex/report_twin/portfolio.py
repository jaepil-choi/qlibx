from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .common import BUY_RATE, SELL_RATE, SELL_TAX, alpha_returns
from .contract import TOLERANCE


ETF_TICKER = "K200_ETF"


@dataclass(frozen=True)
class PhysicalPortfolio:
    alpha: pd.DataFrame
    direct_stock_weight: pd.DataFrame
    etf_weight: pd.Series
    physical_target_weight: pd.DataFrame
    final_lookthrough_weight: pd.DataFrame
    daily: pd.DataFrame


def build_etf_residual_portfolio(
    alpha: pd.DataFrame,
    benchmark: pd.DataFrame,
    realized_return: pd.DataFrame,
    universe: pd.DataFrame,
    *,
    alpha_multiplier: float,
) -> PhysicalPortfolio:
    applied_alpha = (alpha * float(alpha_multiplier)).astype("float64")
    desired_direct = benchmark.astype("float64") * 0.70 + applied_alpha
    upper = benchmark.astype("float64").clip(lower=0.10)
    direct = desired_direct.clip(lower=0.0).where(
        desired_direct.clip(lower=0.0).le(upper), upper
    )
    direct = direct.mask(direct.abs().le(TOLERANCE), 0.0).astype("float64")
    execution_universe = universe.astype(bool) & realized_return.notna()
    direct = direct.where(execution_universe, 0.0).astype("float64")
    etf = (1.0 - direct.sum(axis=1)).rename(ETF_TICKER).astype("float64")
    if etf.lt(-TOLERANCE).any() or etf.gt(1.0 + TOLERANCE).any():
        raise RuntimeError("ETF residual leaves physical [0, 1] bounds")
    etf = etf.clip(lower=0.0, upper=1.0)
    physical = direct.copy()
    physical[ETF_TICKER] = etf
    if not np.allclose(physical.sum(axis=1), 1.0, atol=TOLERANCE):
        raise RuntimeError("physical target is not fully invested")
    lookthrough = direct + benchmark.mul(etf, axis=0)
    benchmark_return = alpha_returns(benchmark, realized_return)
    gross_return = alpha_returns(lookthrough, realized_return)
    stock_cost = _drift_turnover_and_cost(
        direct,
        realized_return,
        gross_return,
        nav_delta=False,
        sell_tax=SELL_TAX,
    )
    etf_cost = _drift_turnover_and_cost(
        benchmark.mul(etf, axis=0),
        realized_return,
        gross_return,
        nav_delta=True,
        sell_tax=0.0,
    )
    cost = stock_cost["trade_cost"] + etf_cost["trade_cost"]
    daily = pd.DataFrame(
        {
            "benchmark_return": benchmark_return,
            "gross_portfolio_return": gross_return,
            "net_portfolio_return": gross_return - cost,
            "gross_active_return": gross_return - benchmark_return,
            "net_active_return": gross_return - cost - benchmark_return,
            "trade_cost": cost,
            "gross_turnover": (
                stock_cost["gross_turnover"] + etf_cost["gross_turnover"]
            ),
            "stock_trade_cost": stock_cost["trade_cost"],
            "etf_trade_cost": etf_cost["trade_cost"],
        },
        index=alpha.index,
    ).astype("float64")
    return PhysicalPortfolio(
        alpha=applied_alpha,
        direct_stock_weight=direct,
        etf_weight=etf,
        physical_target_weight=physical,
        final_lookthrough_weight=lookthrough,
        daily=daily,
    )


def _drift_turnover_and_cost(
    execution_weight: pd.DataFrame,
    realized_return: pd.DataFrame,
    gross_portfolio_return: pd.Series,
    *,
    nav_delta: bool,
    sell_tax: float,
) -> pd.DataFrame:
    post_return = execution_weight.mul(1.0 + realized_return.fillna(0.0)).div(
        1.0 + gross_portfolio_return,
        axis=0,
    )
    pre_trade = post_return.shift(1).fillna(0.0)
    if nav_delta:
        trade = execution_weight.sum(axis=1) - pre_trade.sum(axis=1)
        buy = trade.clip(lower=0.0)
        sell = trade.clip(upper=0.0).abs()
    else:
        trade = execution_weight - pre_trade
        buy = trade.clip(lower=0.0).sum(axis=1)
        sell = trade.clip(upper=0.0).abs().sum(axis=1)
    return pd.DataFrame(
        {
            "buy_turnover": buy,
            "sell_turnover": sell,
            "gross_turnover": buy + sell,
            "trade_cost": buy * BUY_RATE + sell * (SELL_RATE + sell_tax),
        },
        index=execution_weight.index,
    ).astype("float64")


def build_physical_tape(
    realized_return: pd.DataFrame,
    benchmark_weight: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    stock_return = realized_return.fillna(0.0).astype("float64")
    etf_return = (benchmark_weight * stock_return).sum(axis=1)
    physical_return = stock_return.copy()
    physical_return[ETF_TICKER] = etf_return
    execution = pd.DataFrame(
        index=physical_return.index,
        columns=physical_return.columns,
        dtype="float64",
    )
    valuation = execution.copy()
    previous = pd.Series(100.0, index=physical_return.columns, dtype="float64")
    for date in physical_return.index:
        execution.loc[date] = previous
        current = previous * (1.0 + physical_return.loc[date])
        if not np.isfinite(current.to_numpy()).all() or current.le(0.0).any():
            raise RuntimeError(f"synthetic Qlib price became invalid: {date}")
        valuation.loc[date] = current
        previous = current
    return execution, valuation


def compare_frozen_daily(
    method: str,
    twin: pd.DataFrame,
    frozen: pd.DataFrame,
    *,
    alpha_multiplier: float,
) -> dict[str, float]:
    prefix = f"{method}__m{alpha_multiplier:.3f}"
    mapping = {
        "gross_active_return": f"{prefix}__gross_active",
        "net_active_return": f"{prefix}__net_active",
        "trade_cost": f"{prefix}__trade_cost",
        "gross_turnover": f"{prefix}__gross_turnover",
    }
    missing = sorted(set(mapping.values()).difference(frozen.columns))
    if missing:
        raise ValueError(f"frozen enhanced daily columns are missing: {missing}")
    return {
        name: float(twin[name].sub(frozen[column]).abs().max())
        for name, column in mapping.items()
    }
