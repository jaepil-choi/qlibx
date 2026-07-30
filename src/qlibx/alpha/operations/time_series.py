"""Operations that act along the time axis within one ticker."""

from __future__ import annotations

import pandas as pd

from qlibx.errors import QlibxError

from ..registry import OperationSpec, register_operation


def lag(values: pd.DataFrame, *, periods: int = 1) -> pd.DataFrame:
    """Shift each ticker forward in time; the first ``periods`` rows become missing."""
    if periods < 1:
        raise QlibxError(
            "ALPHA",
            "periods must be positive",
            expected="A lag shifts by at least one period.",
        )
    return values.shift(periods)


def rolling_mean(values: pd.DataFrame, *, window: int) -> pd.DataFrame:
    if window < 1:
        raise QlibxError(
            "ALPHA",
            "window must be positive",
            expected="A rolling window spans at least one period.",
        )
    return values.rolling(window, min_periods=window).mean()


def rolling_std(values: pd.DataFrame, *, window: int, ddof: int = 1) -> pd.DataFrame:
    if window < 1:
        raise QlibxError(
            "ALPHA",
            "window must be positive",
            expected="A rolling window spans at least one period.",
        )
    if ddof < 0 or ddof >= window:
        raise QlibxError(
            "ALPHA",
            "ddof must satisfy 0 <= ddof < window",
            expected="Degrees of freedom leave at least one observation in the window.",
        )
    return values.rolling(window, min_periods=window).std(ddof=ddof)


def linear_decay(values: pd.DataFrame, *, window: int) -> pd.DataFrame:
    if window < 1:
        raise QlibxError(
            "ALPHA",
            "window must be positive",
            expected="A rolling window spans at least one period.",
        )
    weights = pd.Series(range(1, window + 1), dtype="float64")
    denominator = float(weights.sum())
    return values.rolling(window, min_periods=window).apply(
        lambda series: float(series.reset_index(drop=True).mul(weights).sum()) / denominator,
        raw=False,
    )


def hump(values: pd.DataFrame, *, maximum_change: float) -> pd.DataFrame:
    """Limit each ticker's step change without filling missing observations.

    A missing observation is preserved and breaks the chain: the next observed value
    restarts the limiter instead of propagating missingness for the rest of the series.
    """
    if maximum_change < 0:
        raise QlibxError(
            "ALPHA",
            "maximum_change must be non-negative",
            expected="A hump limit is a non-negative change per period.",
        )
    result = values.copy().astype("float64")
    for offset in range(1, len(result.index)):
        previous = result.iloc[offset - 1]
        current = result.iloc[offset]
        delta = current.sub(previous).clip(-maximum_change, maximum_change)
        limited = previous.add(delta)
        # Where the previous value is missing there is nothing to limit against, so the
        # current observation passes through unchanged rather than becoming missing.
        result.iloc[offset] = limited.where(previous.notna(), current).where(current.notna(), pd.NA)
    return result


register_operation(
    OperationSpec(
        name="lag",
        operation_id="qlibx.alpha.lag",
        version="1",
        axis="time_by_ticker",
        tie_behavior="not_applicable",
        nan_behavior="leading_rows_become_missing",
        minimum_observations=2,
        group_missing_behavior="not_applicable",
        dtype="float64",
        summary="Shift each ticker forward by whole index positions.",
        apply=lag,
        parameters={"periods": "positive number of index positions to shift"},
        resolve_minimum_observations=lambda parameters: int(parameters.get("periods", 1)) + 1,
    )
)
register_operation(
    OperationSpec(
        name="rolling_mean",
        operation_id="qlibx.alpha.rolling_mean",
        version="1",
        axis="time_by_ticker",
        tie_behavior="not_applicable",
        nan_behavior="full_window_required",
        minimum_observations=None,
        group_missing_behavior="not_applicable",
        dtype="float64",
        summary="Trailing mean over a full window of consecutive index positions.",
        apply=rolling_mean,
        parameters={"window": "positive number of trailing index positions"},
        required_parameters=("window",),
        resolve_minimum_observations=lambda parameters: int(parameters["window"]),
    )
)
register_operation(
    OperationSpec(
        name="rolling_std",
        operation_id="qlibx.alpha.rolling_std",
        version="1",
        axis="time_by_ticker",
        tie_behavior="not_applicable",
        nan_behavior="full_window_required",
        minimum_observations=None,
        group_missing_behavior="not_applicable",
        dtype="float64",
        summary="Trailing standard deviation over a full window of index positions.",
        apply=rolling_std,
        parameters={
            "window": "positive number of trailing index positions",
            "ddof": "delta degrees of freedom in [0, window)",
        },
        required_parameters=("window",),
        resolve_minimum_observations=lambda parameters: int(parameters["window"]),
    )
)
register_operation(
    OperationSpec(
        name="linear_decay",
        operation_id="qlibx.alpha.linear_decay",
        version="1",
        axis="time_by_ticker",
        tie_behavior="not_applicable",
        nan_behavior="full_window_required",
        minimum_observations=None,
        group_missing_behavior="not_applicable",
        dtype="float64",
        summary="Linearly weighted trailing average with the newest observation heaviest.",
        apply=linear_decay,
        parameters={"window": "positive number of trailing index positions"},
        required_parameters=("window",),
        resolve_minimum_observations=lambda parameters: int(parameters["window"]),
    )
)
register_operation(
    OperationSpec(
        name="hump",
        operation_id="qlibx.alpha.hump",
        version="1",
        axis="time_by_ticker",
        tie_behavior="not_applicable",
        nan_behavior="preserve_without_fill_and_restart_after_gap",
        minimum_observations=1,
        group_missing_behavior="not_applicable",
        dtype="float64",
        summary="Bound each ticker's step change; a gap restarts the limiter.",
        apply=hump,
        parameters={"maximum_change": "non-negative maximum absolute step change"},
        required_parameters=("maximum_change",),
    )
)

__all__ = ["hump", "lag", "linear_decay", "rolling_mean", "rolling_std"]
