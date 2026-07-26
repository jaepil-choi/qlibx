from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import numpy as np
import pandas as pd

from qlib_extended.research.config import read_yaml_mapping, require_mapping


@dataclass(frozen=True)
class AsymmetricCostContract:
    stock_buy_rate: float
    stock_sell_rate: float
    etf_buy_rate: float
    etf_sell_rate: float

    @classmethod
    def from_yaml(cls, path: Path) -> AsymmetricCostContract:
        payload = read_yaml_mapping(path)
        if payload.get("schema_version") != 1:
            raise ValueError("costs.yaml schema_version must be 1.")
        stock = require_mapping(payload.get("stock"), "stock")
        etf = require_mapping(payload.get("etf"), "etf")
        contract = cls(
            stock_buy_rate=float(stock["buy_bps"]) / 10_000.0,
            stock_sell_rate=float(stock["sell_bps"]) / 10_000.0,
            etf_buy_rate=float(etf["buy_bps"]) / 10_000.0,
            etf_sell_rate=float(etf["sell_bps"]) / 10_000.0,
        )
        if min(
            contract.stock_buy_rate,
            contract.stock_sell_rate,
            contract.etf_buy_rate,
            contract.etf_sell_rate,
        ) < 0:
            raise ValueError("Cost rates must be non-negative.")
        return contract

    def evaluate_netted_orders(
        self,
        *,
        stock_target: pd.DataFrame,
        stock_pretrade: pd.DataFrame,
        etf_target: pd.Series,
        etf_pretrade: pd.Series,
        financed_notional: pd.Series | None = None,
        expected_unwind_fraction: float = 0.0,
    ) -> pd.DataFrame:
        _require_same_axes(stock_target, stock_pretrade, "stock target/pretrade")
        _require_same_index(etf_target, etf_pretrade, "ETF target/pretrade")
        if not stock_target.index.equals(etf_target.index):
            raise ValueError("Stock and ETF order calendars must be identical.")
        if not 0.0 <= expected_unwind_fraction <= 1.0:
            raise ValueError("expected_unwind_fraction must be in [0, 1].")

        stock_delta = stock_target - stock_pretrade
        etf_delta = etf_target - etf_pretrade
        stock_buy = stock_delta.clip(lower=0.0).sum(axis=1)
        stock_sell = -stock_delta.clip(upper=0.0).sum(axis=1)
        etf_buy = etf_delta.clip(lower=0.0)
        etf_sell = -etf_delta.clip(upper=0.0)
        if financed_notional is None:
            financed = pd.Series(0.0, index=stock_target.index)
        else:
            _require_same_index(financed_notional, etf_target, "financing/ETF")
            financed = financed_notional.astype("float64")
            if financed.lt(-1e-12).any():
                raise ValueError("financed_notional must be non-negative.")
            capacity = pd.concat([stock_buy, etf_sell], axis=1).min(axis=1)
            if financed.gt(capacity + 1e-12).any():
                raise ValueError(
                    "financed_notional exceeds same-day ETF-sell/stock-buy capacity."
                )

        stock_cost = (
            stock_buy * self.stock_buy_rate + stock_sell * self.stock_sell_rate
        )
        etf_cost = etf_buy * self.etf_buy_rate + etf_sell * self.etf_sell_rate
        expected_unwind_cost = financed * expected_unwind_fraction * (
            self.stock_sell_rate + self.etf_buy_rate
        )
        return pd.DataFrame(
            {
                "stock_buy_turnover": stock_buy,
                "stock_sell_turnover": stock_sell,
                "etf_buy_turnover": etf_buy,
                "etf_sell_turnover": etf_sell,
                "financed_notional": financed,
                "stock_trade_cost": stock_cost,
                "etf_trade_cost": etf_cost,
                "expected_unwind_cost": expected_unwind_cost,
                "total_trade_cost": stock_cost + etf_cost + expected_unwind_cost,
            },
            index=stock_target.index,
        )

    def expected_inventory_unwind_cost(
        self,
        financed_inventory: pd.Series,
        *,
        unwind_horizon_days: int,
    ) -> pd.Series:
        if unwind_horizon_days < 1:
            raise ValueError("unwind_horizon_days must be positive.")
        inventory = financed_inventory.astype("float64")
        if inventory.lt(-1e-12).any():
            raise ValueError("financed_inventory must be non-negative.")
        return inventory.clip(lower=0.0) * (
            self.stock_sell_rate + self.etf_buy_rate
        ) / float(unwind_horizon_days)


def cross_member_targets(
    targets: Mapping[str, pd.DataFrame],
    weights: Mapping[str, float],
) -> pd.DataFrame:
    if not targets:
        raise ValueError("At least one member target is required.")
    if set(targets) != set(weights):
        raise KeyError("Target and member-weight keys must match exactly.")
    first_name = next(iter(targets))
    reference = targets[first_name]
    if not np.isfinite(list(weights.values())).all():
        raise ValueError("Member weights must be finite.")
    output = pd.DataFrame(0.0, index=reference.index, columns=reference.columns)
    for name, target in targets.items():
        _require_same_axes(reference, target, f"member target {name}")
        output = output.add(target * float(weights[name]))
    return output


def _require_same_axes(left: pd.DataFrame, right: pd.DataFrame, label: str) -> None:
    if not left.index.equals(right.index) or not left.columns.equals(right.columns):
        raise ValueError(f"Axis mismatch: {label}")


def _require_same_index(left: pd.Series, right: pd.Series, label: str) -> None:
    if not left.index.equals(right.index):
        raise ValueError(f"Index mismatch: {label}")
