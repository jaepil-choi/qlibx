"""Operations that need an explicit point-in-time group label per ticker.

These are the operations with a data requirement beyond the signal matrix itself: the
caller must supply group labels that were knowable at the decision time.
"""

from __future__ import annotations

import pandas as pd

from ..contracts import NEUTRALITY_WARNING
from ..registry import OperationSpec, register_operation


def group_demean(values: pd.DataFrame, groups: pd.DataFrame) -> pd.DataFrame:
    """Demean each date within explicit ticker groups; missing groups stay missing."""
    values, groups = values.align(groups, join="left")
    result = pd.DataFrame(index=values.index, columns=values.columns, dtype="float64")
    for date in values.index:
        row = values.loc[date]
        labels = groups.loc[date]
        valid = row.notna() & labels.notna()
        result.loc[date, valid] = row[valid] - row[valid].groupby(labels[valid]).transform("mean")
    return result


register_operation(
    OperationSpec(
        name="group_demean",
        operation_id="qlibx.alpha.group_demean",
        version="1",
        axis="date_by_ticker_with_group",
        tie_behavior="not_applicable",
        nan_behavior="exclude_from_group_mean_and_preserve",
        minimum_observations=1,
        group_missing_behavior="missing_group_produces_missing_output",
        dtype="float64",
        summary="Subtract each date's group mean using explicit point-in-time labels.",
        apply=group_demean,
        requires_groups=True,
        neutrality_warning=NEUTRALITY_WARNING,
    )
)

__all__ = ["group_demean"]
