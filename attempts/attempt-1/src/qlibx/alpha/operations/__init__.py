"""Built-in signal operations, grouped by the axis they act on.

Importing this package registers every built-in. Each module owns both its
implementations and their ``OperationSpec`` declarations, so a new operation family is
a new file plus one import line here -- no central table to keep in sync.
"""

from __future__ import annotations

from .cross_sectional import (
    clip,
    cross_sectional_demean,
    cross_sectional_rank,
    cross_sectional_zscore,
    winsorize,
)
from .grouping import group_demean
from .selection import per_name_cap, top_bottom
from .time_series import hump, lag, linear_decay, rolling_mean, rolling_std

__all__ = [
    "clip",
    "cross_sectional_demean",
    "cross_sectional_rank",
    "cross_sectional_zscore",
    "group_demean",
    "hump",
    "lag",
    "linear_decay",
    "per_name_cap",
    "rolling_mean",
    "rolling_std",
    "top_bottom",
    "winsorize",
]
