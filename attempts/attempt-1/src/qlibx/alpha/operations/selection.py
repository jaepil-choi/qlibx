"""Operations that select or bound names rather than rescale a whole cross-section."""

from __future__ import annotations

import pandas as pd

from qlibx.errors import QlibxError

from ..registry import OperationSpec, register_operation


def top_bottom(values: pd.DataFrame, *, count: int) -> pd.DataFrame:
    """Select the ``count`` highest as +1 and the ``count`` lowest as -1.

    A date with fewer than ``2 * count`` valid observations cannot produce a disjoint
    selection, so it fails explicitly instead of silently assigning one name to both
    sides (where the short assignment would have won).
    """
    if count < 1:
        raise QlibxError(
            "ALPHA",
            "count must be positive",
            expected="A top/bottom selection takes at least one name.",
        )
    valid = values.notna().sum(axis=1)
    insufficient = valid.lt(2 * count)
    if insufficient.any():
        offending = [str(label) for label in values.index[insufficient][:5]]
        raise QlibxError(
            "ALPHA",
            f"top_bottom requires at least {2 * count} valid observations per date; "
            f"insufficient on {int(insufficient.sum())} date(s), for example {offending}",
            expected=(
                "Each date has enough valid values to fill both sides; qlibx does not "
                "assign one name to the long and the short leg."
            ),
            context={"insufficient_dates": int(insufficient.sum()), "examples": offending},
        )
    ranks_ascending = values.rank(axis=1, method="first", ascending=True)
    ranks_descending = values.rank(axis=1, method="first", ascending=False)
    selected = pd.DataFrame(0.0, index=values.index, columns=values.columns)
    selected = selected.mask(ranks_descending.le(count), 1.0)
    selected = selected.mask(ranks_ascending.le(count), -1.0)
    return selected.where(values.notna(), pd.NA)


def per_name_cap(values: pd.DataFrame, *, maximum_weight: float) -> pd.DataFrame:
    """Bound each name's absolute weight without changing its sign or missingness."""
    if maximum_weight <= 0:
        raise QlibxError(
            "ALPHA",
            "maximum_weight must be positive",
            expected="A weight cap is a positive fraction.",
        )
    return values.clip(lower=-maximum_weight, upper=maximum_weight)


register_operation(
    OperationSpec(
        name="top_bottom",
        operation_id="qlibx.alpha.top_bottom",
        version="1",
        axis="date_by_ticker",
        tie_behavior="first_by_column_order",
        nan_behavior="preserve",
        minimum_observations=2,
        group_missing_behavior="not_applicable",
        dtype="float64",
        summary="Select the highest names as +1 and the lowest as -1; others are 0.",
        apply=top_bottom,
        parameters={"count": "positive number of names selected on each side"},
        required_parameters=("count",),
        selection_behavior="disjoint_sides_required; fewer than 2*count valid names fails",
        resolve_minimum_observations=lambda parameters: 2 * int(parameters["count"]),
    )
)
register_operation(
    OperationSpec(
        name="per_name_cap",
        operation_id="qlibx.alpha.per_name_cap",
        version="1",
        axis="date_by_ticker",
        tie_behavior="not_applicable",
        nan_behavior="preserve",
        minimum_observations=1,
        group_missing_behavior="not_applicable",
        dtype="float64",
        summary="Bound each name's absolute weight without changing sign or missingness.",
        apply=per_name_cap,
        parameters={"maximum_weight": "positive maximum absolute per-name weight"},
        required_parameters=("maximum_weight",),
    )
)

__all__ = ["per_name_cap", "top_bottom"]
