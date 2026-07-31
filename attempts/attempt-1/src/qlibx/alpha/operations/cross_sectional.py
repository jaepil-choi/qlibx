"""Operations that act across tickers within one date.

Each operation declares its own contract next to its implementation, so adding one
means editing this file only.
"""

from __future__ import annotations

import pandas as pd

from qlibx.errors import QlibxError

from ..contracts import NEUTRALITY_WARNING
from ..registry import OperationSpec, register_operation


def cross_sectional_rank(values: pd.DataFrame) -> pd.DataFrame:
    """Return centered percentile ranks in [-0.5, 0.5], preserving missing values."""
    return values.rank(axis=1, method="average", pct=True) - 0.5


def cross_sectional_demean(values: pd.DataFrame) -> pd.DataFrame:
    return values.sub(values.mean(axis=1), axis=0)


def cross_sectional_zscore(values: pd.DataFrame, *, minimum_count: int = 2) -> pd.DataFrame:
    count = values.count(axis=1)
    mean = values.mean(axis=1)
    scale = values.std(axis=1, ddof=0).replace(0.0, pd.NA)
    result = values.sub(mean, axis=0).div(scale, axis=0)
    return result.where(count.ge(minimum_count), pd.NA)


def winsorize(values: pd.DataFrame, *, lower: float = 0.01, upper: float = 0.99) -> pd.DataFrame:
    if not 0 <= lower <= upper <= 1:
        raise QlibxError(
            "ALPHA",
            "winsorize quantiles must satisfy 0 <= lower <= upper <= 1",
            expected="Winsorize bounds are quantiles, lower no greater than upper.",
        )
    floors = values.quantile(lower, axis=1)
    ceilings = values.quantile(upper, axis=1)
    return values.clip(lower=floors, upper=ceilings, axis=0)


def clip(
    values: pd.DataFrame,
    *,
    lower: float | None = None,
    upper: float | None = None,
) -> pd.DataFrame:
    """Clip to explicit absolute bounds; missing observations stay missing."""
    if lower is None and upper is None:
        raise QlibxError(
            "ALPHA",
            "clip requires an explicit lower or upper bound",
            expected="A clip states at least one bound; qlibx does not choose one.",
        )
    if lower is not None and upper is not None and lower > upper:
        raise QlibxError(
            "ALPHA",
            "clip requires lower <= upper",
            expected="Clip bounds are ordered.",
        )
    return values.clip(lower=lower, upper=upper)


register_operation(
    OperationSpec(
        name="cross_sectional_rank",
        operation_id="qlibx.alpha.cross_sectional_rank",
        version="1",
        axis="date_by_ticker",
        tie_behavior="average_percentile_rank",
        nan_behavior="preserve",
        minimum_observations=1,
        group_missing_behavior="not_applicable",
        dtype="float64",
        summary="Centered cross-sectional percentile rank in [-0.5, 0.5].",
        apply=cross_sectional_rank,
    )
)
register_operation(
    OperationSpec(
        name="cross_sectional_demean",
        operation_id="qlibx.alpha.cross_sectional_demean",
        version="1",
        axis="date_by_ticker",
        tie_behavior="not_applicable",
        nan_behavior="exclude_from_mean_and_preserve",
        minimum_observations=1,
        group_missing_behavior="not_applicable",
        dtype="float64",
        summary="Subtract each date's cross-sectional mean.",
        apply=cross_sectional_demean,
        neutrality_warning=NEUTRALITY_WARNING,
    )
)
register_operation(
    OperationSpec(
        name="cross_sectional_zscore",
        operation_id="qlibx.alpha.cross_sectional_zscore",
        version="1",
        axis="date_by_ticker",
        tie_behavior="not_applicable",
        nan_behavior="exclude_from_moments_and_preserve",
        minimum_observations=2,
        group_missing_behavior="not_applicable",
        dtype="float64",
        summary="Standardize each date by its population mean and standard deviation.",
        apply=cross_sectional_zscore,
        parameters={"minimum_count": "minimum valid observations per date; fewer produces missing"},
        resolve_minimum_observations=lambda parameters: int(parameters.get("minimum_count", 2)),
        neutrality_warning=NEUTRALITY_WARNING,
    )
)
register_operation(
    OperationSpec(
        name="winsorize",
        operation_id="qlibx.alpha.winsorize",
        version="1",
        axis="date_by_ticker",
        tie_behavior="not_applicable",
        nan_behavior="exclude_from_quantiles_and_preserve",
        minimum_observations=1,
        group_missing_behavior="not_applicable",
        dtype="float64",
        summary="Clip each date to its own lower/upper cross-sectional quantiles.",
        apply=winsorize,
        parameters={
            "lower": "lower quantile in [0, 1]",
            "upper": "upper quantile in [0, 1] and >= lower",
        },
    )
)
register_operation(
    OperationSpec(
        name="clip",
        operation_id="qlibx.alpha.clip",
        version="1",
        axis="date_by_ticker",
        tie_behavior="not_applicable",
        nan_behavior="preserve",
        minimum_observations=1,
        group_missing_behavior="not_applicable",
        dtype="float64",
        summary="Clip to explicit absolute bounds shared by every date and ticker.",
        apply=clip,
        parameters={
            "lower": "absolute lower bound or None",
            "upper": "absolute upper bound or None",
        },
    )
)

__all__ = [
    "clip",
    "cross_sectional_demean",
    "cross_sectional_rank",
    "cross_sectional_zscore",
    "winsorize",
]
