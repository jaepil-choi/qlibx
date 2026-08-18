"""Signal to signal, across one cross-section at a time.

Every function here takes one date's values and returns one date's values. There is no panel, no
date axis and no history — a cross-sectional operation that could see another date would be able to
see a later one, and this module is the layer that must not be able to.

The operations are the ones a researcher reaches for before deciding anything: put names in order,
put them on a common scale, take the average out, pull the extremes in, cut them into buckets. None
of them decide a weight. Turning a score into a position is `portfolio/weighting.py`'s job, and the
split exists so that "weighting does not handle missing data" stays a boundary rather than becoming
a convention inside one file.

Missing values are never invented. A name with no value is absent from the result rather than
present with a zero, because zero is a claim about the name and absence is the truth about the
data. `missing.py` is where that choice is made explicit.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal

__all__ = [
    "demean",
    "quantile_buckets",
    "rank",
    "winsorize",
    "zscore",
]


def _checked(values: Mapping[str, Decimal], name: str) -> dict[str, Decimal]:
    if not isinstance(values, Mapping):
        raise TypeError(f"{name} takes a mapping of instrument to Decimal")
    if not values:
        raise ValueError(f"{name} needs a non-empty cross-section")
    checked: dict[str, Decimal] = {}
    for instrument, value in values.items():
        if not isinstance(instrument, str) or not instrument:
            raise ValueError(f"{name} received a non-string instrument identifier")
        if not isinstance(value, Decimal):
            raise TypeError(f"{name}[{instrument!r}] must be a Decimal; got {type(value).__name__}")
        if not value.is_finite():
            raise ValueError(f"{name}[{instrument!r}] must be finite")
        checked[instrument] = value
    return checked


def rank(values: Mapping[str, Decimal], *, ascending: bool = True) -> dict[str, Decimal]:
    """Order the cross-section, sharing a rank between ties.

    Ties take the average of the positions they span, so a group of equal values cannot be broken
    by whatever order the mapping happened to arrive in. Ranks start at one.
    """
    checked = _checked(values, "rank")
    ordered = sorted(checked.items(), key=lambda item: (item[1], item[0]), reverse=not ascending)

    ranked: dict[str, Decimal] = {}
    position = 0
    while position < len(ordered):
        stop = position
        while stop + 1 < len(ordered) and ordered[stop + 1][1] == ordered[position][1]:
            stop += 1
        shared = Decimal(position + stop + 2) / 2
        for index in range(position, stop + 1):
            ranked[ordered[index][0]] = shared
        position = stop + 1
    return {instrument: ranked[instrument] for instrument in checked}


def demean(values: Mapping[str, Decimal]) -> dict[str, Decimal]:
    """Subtract the cross-sectional average.

    This is the market-neutral move in its simplest form: what survives is how a name compares to
    its peers on this date, not how the whole cross-section moved.
    """
    checked = _checked(values, "demean")
    centre = sum(checked.values(), Decimal(0)) / len(checked)
    return {instrument: value - centre for instrument, value in checked.items()}


def zscore(values: Mapping[str, Decimal]) -> dict[str, Decimal]:
    """Centre the cross-section and divide by its spread.

    Refuses a flat cross-section rather than returning zeros: with no spread there is no scale to
    divide by, and zeros would claim every name sits exactly at the average by measurement rather
    than by accident.
    """
    checked = _checked(values, "zscore")
    if len(checked) < 2:
        raise ValueError("zscore needs at least two instruments")
    centre = sum(checked.values(), Decimal(0)) / len(checked)
    variance = sum(((value - centre) ** 2 for value in checked.values()), Decimal(0)) / (
        len(checked) - 1
    )
    if variance == 0:
        raise ValueError("zscore is undefined on a cross-section with no spread")
    spread = variance.sqrt()
    return {instrument: (value - centre) / spread for instrument, value in checked.items()}


def winsorize(values: Mapping[str, Decimal], *, proportion: Decimal) -> dict[str, Decimal]:
    """Pull the extremes in to the surviving boundary values, keeping every name.

    Clipping rather than dropping, because an outlier is still a position: the name stays in the
    cross-section at the boundary value instead of vanishing from it. `proportion` is the share
    trimmed from each tail.
    """
    checked = _checked(values, "winsorize")
    if not isinstance(proportion, Decimal):
        raise TypeError("proportion must be a Decimal")
    if not proportion.is_finite() or proportion < 0 or proportion >= Decimal("0.5"):
        raise ValueError("proportion must be at least 0 and below 0.5")

    ordered = sorted(checked.values())
    cut = int(len(ordered) * proportion)
    if cut == 0:
        return dict(checked)
    low, high = ordered[cut], ordered[len(ordered) - 1 - cut]
    return {
        instrument: low if value < low else high if value > high else value
        for instrument, value in checked.items()
    }


def quantile_buckets(values: Mapping[str, Decimal], *, buckets: int) -> dict[str, int]:
    """Cut the cross-section into equally counted groups, numbered from one.

    Assignment follows the shared rank, so tied names cannot land in different buckets because of
    mapping order. Boundaries are recorded implicitly by the rank rather than by a value threshold,
    which is what keeps a double sort reproducible when the same value appears many times.
    """
    checked = _checked(values, "quantile_buckets")
    if isinstance(buckets, bool) or not isinstance(buckets, int) or buckets < 2:
        raise ValueError("buckets must be an integer of at least 2")
    if buckets > len(checked):
        raise ValueError(
            f"cannot cut {len(checked)} instruments into {buckets} buckets; a bucket would be empty"
        )

    ranked = rank(checked)
    ordered = sorted(ranked.items(), key=lambda item: (item[1], item[0]))
    assigned: dict[str, int] = {}
    for position, (instrument, _) in enumerate(ordered):
        assigned[instrument] = min(buckets, position * buckets // len(ordered) + 1)

    # Ties share a rank, so they must share a bucket even when the count boundary falls between
    # them. The later assignment wins, keeping groups whole at the cost of unequal counts.
    by_rank: dict[Decimal, int] = {}
    for instrument, bucket in assigned.items():
        by_rank.setdefault(ranked[instrument], bucket)
    return {instrument: by_rank[ranked[instrument]] for instrument in checked}
