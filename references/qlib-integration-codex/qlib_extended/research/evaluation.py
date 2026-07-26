from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from qlib_extended.research.config import read_yaml_mapping, require_mapping
from qlib_extended.research.manifest import MetricValue


TRADING_DAYS = 252


@dataclass(frozen=True)
class WalkForwardFold:
    validation_year: int
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    validation_start: pd.Timestamp
    validation_end: pd.Timestamp
    embargo_end: pd.Timestamp

    @property
    def segment(self) -> str:
        return f"walk_forward_{self.validation_year}"


@dataclass(frozen=True)
class WalkForwardScheme:
    start: pd.Timestamp
    end: pd.Timestamp
    first_validation_year: int
    minimum_train_years: int
    purge_days: int
    embargo_days: int
    worst_weight: float
    mean_weight: float
    minimum_positive_fraction: float

    @classmethod
    def from_yaml(cls, path: Path) -> WalkForwardScheme:
        payload = read_yaml_mapping(path)
        if payload.get("schema_version") != 1:
            raise ValueError("splits.yaml schema_version must be 1.")
        historical = require_mapping(
            payload.get("historical_research"), "historical_research"
        )
        selection = require_mapping(payload.get("selection"), "selection")
        scheme = cls(
            start=pd.Timestamp(historical["start"]),
            end=pd.Timestamp(historical["end"]),
            first_validation_year=int(historical["first_validation_year"]),
            minimum_train_years=int(historical["minimum_train_years"]),
            purge_days=int(historical["purge_days"]),
            embargo_days=int(historical["embargo_days"]),
            worst_weight=float(selection["worst_weight"]),
            mean_weight=float(selection["mean_weight"]),
            minimum_positive_fraction=float(
                selection["minimum_positive_fraction"]
            ),
        )
        scheme.validate()
        return scheme

    def validate(self) -> None:
        if self.start >= self.end:
            raise ValueError("Walk-forward start must precede end.")
        if self.minimum_train_years < 1:
            raise ValueError("minimum_train_years must be positive.")
        if self.purge_days < 0 or self.embargo_days < 0:
            raise ValueError("purge_days and embargo_days must be non-negative.")
        if not np.isclose(self.worst_weight + self.mean_weight, 1.0):
            raise ValueError("walk-forward selection weights must sum to one.")
        if not 0.0 <= self.minimum_positive_fraction <= 1.0:
            raise ValueError("minimum_positive_fraction must be in [0, 1].")

    def folds(self, calendar: pd.DatetimeIndex) -> tuple[WalkForwardFold, ...]:
        dates = pd.DatetimeIndex(calendar).drop_duplicates().sort_values()
        dates = dates[(dates >= self.start) & (dates <= self.end)]
        if dates.empty:
            raise ValueError("Walk-forward calendar has no date in configured range.")
        folds: list[WalkForwardFold] = []
        for year in range(self.first_validation_year, self.end.year + 1):
            validation = dates[dates.year == year]
            if validation.empty:
                continue
            before = dates[dates < validation.min()]
            if len(before) <= self.purge_days:
                continue
            train_end_position = len(before) - self.purge_days - 1
            train_end = before[train_end_position]
            train = dates[(dates >= self.start) & (dates <= train_end)]
            if len(set(train.year)) < self.minimum_train_years:
                continue
            after = dates[dates > validation.max()]
            if after.empty or self.embargo_days == 0:
                embargo_end = validation.max()
            else:
                embargo_end = after[min(self.embargo_days - 1, len(after) - 1)]
            folds.append(
                WalkForwardFold(
                    validation_year=year,
                    train_start=train.min(),
                    train_end=train_end,
                    validation_start=validation.min(),
                    validation_end=validation.max(),
                    embargo_end=embargo_end,
                )
            )
        if not folds:
            raise ValueError("Walk-forward scheme produced no validation fold.")
        return tuple(folds)


@dataclass(frozen=True)
class ForwardFreeze:
    definition_frozen: bool
    data_config_frozen: bool
    family_membership_frozen: bool
    sizing_frozen: bool
    forward_eligible_from: pd.Timestamp

    @property
    def is_complete(self) -> bool:
        return all(
            (
                self.definition_frozen,
                self.data_config_frozen,
                self.family_membership_frozen,
                self.sizing_frozen,
            )
        )

    def segment_for(self, date: pd.Timestamp) -> str:
        if self.is_complete and pd.Timestamp(date) >= self.forward_eligible_from:
            return "forward_oos"
        return "historical_research"


def evaluate_walk_forward_returns(
    returns: pd.Series,
    scheme: WalkForwardScheme,
    *,
    metric_prefix: str,
) -> list[MetricValue]:
    values = returns.sort_index().astype("float64")
    if not isinstance(values.index, pd.DatetimeIndex):
        raise TypeError("returns index must be a DatetimeIndex.")
    metrics: list[MetricValue] = []
    for fold in scheme.folds(values.index):
        validation = values.loc[fold.validation_start : fold.validation_end].dropna()
        if validation.empty:
            raise ValueError(f"No returns for {fold.segment}.")
        stats = annualized_return_metrics(validation)
        for name, value in stats.items():
            metrics.append(
                MetricValue(fold.segment, f"{metric_prefix}_{name}", value)
            )
    full = values.loc[scheme.start : scheme.end].dropna()
    for name, value in annualized_return_metrics(full).items():
        metrics.append(
            MetricValue("historical_full", f"{metric_prefix}_{name}", value)
        )
    return metrics


def rank_walk_forward_candidates(
    metrics: pd.DataFrame,
    scheme: WalkForwardScheme,
    *,
    metric: str,
) -> pd.DataFrame:
    required = {"candidate", "segment", "metric", "value"}
    missing = sorted(required - set(metrics.columns))
    if missing:
        raise KeyError(f"Walk-forward metrics are missing columns: {missing}")
    selected = metrics.loc[
        metrics["segment"].astype(str).str.startswith("walk_forward_")
        & metrics["metric"].eq(metric)
    ].copy()
    if selected.empty:
        raise ValueError(f"No walk-forward metric available for selection: {metric}")
    pivot = selected.pivot(index="candidate", columns="segment", values="value")
    if pivot.isna().any().any():
        missing_candidates = pivot.index[pivot.isna().any(axis=1)].tolist()
        raise ValueError(f"Candidate is missing walk-forward folds: {missing_candidates}")
    output = pd.DataFrame(index=pivot.index)
    output["worst_fold"] = pivot.min(axis=1)
    output["mean_fold"] = pivot.mean(axis=1)
    output["positive_fraction"] = pivot.gt(0.0).mean(axis=1)
    output["selection_score"] = (
        scheme.worst_weight * output["worst_fold"]
        + scheme.mean_weight * output["mean_fold"]
    )
    output["eligible"] = output["positive_fraction"].ge(
        scheme.minimum_positive_fraction
    )
    return output.reset_index().sort_values(
        ["eligible", "selection_score", "candidate"],
        ascending=[False, False, True],
        ignore_index=True,
    )


def annualized_return_metrics(returns: pd.Series) -> dict[str, float]:
    if returns.empty:
        raise ValueError("Cannot evaluate an empty return series.")
    mean = float(returns.mean())
    volatility = float(returns.std(ddof=1))
    annual_return = mean * TRADING_DAYS
    annual_volatility = volatility * np.sqrt(TRADING_DAYS)
    sharpe = annual_return / annual_volatility if annual_volatility > 0 else 0.0
    return {
        "annual_return": annual_return,
        "annual_volatility": annual_volatility,
        "sharpe": sharpe,
        "cumulative_sum": float(returns.sum()),
    }
