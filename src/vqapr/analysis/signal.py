"""Did the signal predict anything — measured on what a run actually stored.

These are tools for judging a strategy, not part of one. Nothing here decides a weight, and nothing
here manufactures a return: every number is computed from values a run already recorded, which is
what keeps the execution spine the sole source of performance.

The information coefficient is the cross-sectional correlation between a signal and the return that
followed it. Its rank form uses the ordering instead of the values, which is what a researcher
usually wants, because a single extreme name can otherwise carry the whole number.

The sums run in exact rationals so a perfect correlation is recognised as such rather than reported
as a rounded near-one; where the answer needs a square root, it carries the ambient ``Decimal``
context's precision like any other Decimal arithmetic. These functions take realised values as
arguments and never open a store, so a caller cannot accidentally measure against data the strategy
could not have seen.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from fractions import Fraction

__all__ = [
    "decay",
    "hit_rate",
    "information_coefficient",
    "rank_information_coefficient",
]


def _paired(
    signal: Mapping[str, Decimal], realized: Mapping[str, Decimal], name: str
) -> tuple[list[Decimal], list[Decimal]]:
    if not isinstance(signal, Mapping) or not isinstance(realized, Mapping):
        raise TypeError(f"{name} takes two mappings of instrument to Decimal")
    shared = sorted(set(signal) & set(realized))
    if len(shared) < 2:
        raise ValueError(
            f"{name} needs at least two instruments present in both the signal and the outcome"
        )
    left: list[Decimal] = []
    right: list[Decimal] = []
    for instrument in shared:
        for source, values in ((signal, left), (realized, right)):
            value = source[instrument]
            if not isinstance(value, Decimal):
                raise TypeError(
                    f"{name}[{instrument!r}] must be a Decimal; got {type(value).__name__}"
                )
            if not value.is_finite():
                raise ValueError(f"{name}[{instrument!r}] must be finite")
            values.append(value)
    return left, right


def _correlation(left: Sequence[Decimal], right: Sequence[Decimal], name: str) -> Decimal:
    # Sums run in exact rationals so the perfect-correlation case can be recognised as such.
    # A correctly-rounded square root would return 0.9999999999999999999999999998 for a signal
    # correlated with itself, and an anchor that has to be compared with a tolerance is a weaker
    # anchor than one that is simply true.
    count = len(left)
    a_values = [Fraction(value) for value in left]
    b_values = [Fraction(value) for value in right]
    a_centre = sum(a_values, Fraction(0)) / count
    b_centre = sum(b_values, Fraction(0)) / count
    covariance = sum(
        ((a - a_centre) * (b - b_centre) for a, b in zip(a_values, b_values, strict=True)),
        Fraction(0),
    )
    left_spread = sum(((a - a_centre) ** 2 for a in a_values), Fraction(0))
    right_spread = sum(((b - b_centre) ** 2 for b in b_values), Fraction(0))
    if left_spread == 0 or right_spread == 0:
        raise ValueError(
            f"{name} is undefined when either side has no spread; "
            "a flat signal predicts nothing and a flat outcome cannot be predicted"
        )

    product = left_spread * right_spread
    if covariance * covariance == product:
        # Perfect correlation, exactly. The sign is the covariance's.
        return Decimal(1) if covariance > 0 else Decimal(-1)

    denominator = Decimal(product.numerator).sqrt() / Decimal(product.denominator).sqrt()
    return Decimal(covariance.numerator) / Decimal(covariance.denominator) / denominator


def _ranks(values: Sequence[Decimal]) -> list[Decimal]:
    ordered = sorted(range(len(values)), key=lambda index: values[index])
    ranked = [Decimal(0)] * len(values)
    position = 0
    while position < len(ordered):
        stop = position
        while stop + 1 < len(ordered) and values[ordered[stop + 1]] == values[ordered[position]]:
            stop += 1
        shared = Decimal(position + stop + 2) / 2
        for index in range(position, stop + 1):
            ranked[ordered[index]] = shared
        position = stop + 1
    return ranked


def information_coefficient(
    signal: Mapping[str, Decimal], realized: Mapping[str, Decimal]
) -> Decimal:
    """Cross-sectional correlation between the signal and what followed it.

    Only instruments present on both sides are used, because a name with a signal and no outcome
    contributes nothing measurable and a zero would be an invention.
    """
    left, right = _paired(signal, realized, "information_coefficient")
    return _correlation(left, right, "information_coefficient")


def rank_information_coefficient(
    signal: Mapping[str, Decimal], realized: Mapping[str, Decimal]
) -> Decimal:
    """The same measure on orderings rather than values, so one extreme name cannot carry it."""
    left, right = _paired(signal, realized, "rank_information_coefficient")
    return _correlation(_ranks(left), _ranks(right), "rank_information_coefficient")


def hit_rate(signal: Mapping[str, Decimal], realized: Mapping[str, Decimal]) -> Decimal:
    """Share of instruments where the signal's direction matched the outcome's.

    Names where either side is exactly zero are excluded rather than counted as agreement, because
    a zero expresses no direction and counting it either way would decide the answer.
    """
    left, right = _paired(signal, realized, "hit_rate")
    directional = [(a, b) for a, b in zip(left, right, strict=True) if a != 0 and b != 0]
    if not directional:
        raise ValueError("hit_rate needs at least one instrument with a direction on both sides")
    agreed = sum(1 for a, b in directional if (a > 0) == (b > 0))
    return Decimal(agreed) / Decimal(len(directional))


def decay(
    signal: Mapping[str, Decimal], horizons: Sequence[Mapping[str, Decimal]]
) -> tuple[Decimal, ...]:
    """How the information coefficient changes as the outcome moves further from the signal.

    One value per horizon in the order given. A signal whose coefficient falls quickly is telling
    the researcher its edge is short-lived, which is a fact about holding period rather than about
    predictive power.
    """
    if not isinstance(horizons, Sequence) or isinstance(horizons, (str, bytes)) or not horizons:
        raise ValueError("decay needs a non-empty sequence of outcome mappings")
    return tuple(information_coefficient(signal, outcome) for outcome in horizons)
