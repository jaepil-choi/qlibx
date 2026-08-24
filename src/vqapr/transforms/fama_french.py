"""Named Fama-French breakpoint construction.

Fama-French sorts do not divide the portfolio universe into equal-count groups. They estimate
value thresholds from a reference market such as NYSE or KOSPI, then apply those thresholds to
every eligible name. The unequal bucket counts are the methodology, not an implementation detail.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Literal

__all__ = ["fama_french_assign", "fama_french_cut_points"]


def _values(values: Mapping[str, Decimal]) -> dict[str, Decimal]:
    if not isinstance(values, Mapping) or not values:
        raise ValueError("values must be a non-empty mapping of instrument to Decimal")
    checked: dict[str, Decimal] = {}
    for instrument, value in values.items():
        if not isinstance(instrument, str) or not instrument:
            raise ValueError("values has a non-string instrument identifier")
        if not isinstance(value, Decimal):
            raise TypeError(
                f"values[{instrument!r}] must be a Decimal; got {type(value).__name__}"
            )
        if not value.is_finite():
            raise ValueError(f"values[{instrument!r}] must be finite")
        checked[instrument] = value
    return checked


def fama_french_cut_points(
    values: Mapping[str, Decimal],
    *,
    reference: set[str],
    fractions: tuple[Decimal, ...],
    interpolation: Literal["linear", "nearest"] = "linear",
) -> tuple[Decimal, ...]:
    """Return quantile thresholds estimated from the reference subset only.

    ``fractions=(Decimal("0.3"), Decimal("0.7"))`` produces the low and high signal
    breakpoints used by a Fama-French 2x3 sort. ``linear`` matches the pandas/numpy default used by
    the validated Korean replication. ``nearest`` is explicit because changing interpolation can
    change portfolio membership.
    """
    checked = _values(values)
    if not isinstance(reference, set) or not reference:
        raise ValueError("reference must be a non-empty set of instrument identifiers")
    if any(not isinstance(instrument, str) or not instrument for instrument in reference):
        raise ValueError("reference instruments must be non-empty strings")
    if not isinstance(fractions, tuple) or not fractions:
        raise ValueError("fractions must be a non-empty tuple of Decimal")
    previous = Decimal(0)
    for index, fraction in enumerate(fractions):
        if not isinstance(fraction, Decimal):
            raise TypeError(
                f"fractions[{index}] must be a Decimal; got {type(fraction).__name__}"
            )
        if not fraction.is_finite() or fraction <= 0 or fraction >= 1:
            raise ValueError("fractions must be finite and strictly between zero and one")
        if fraction <= previous:
            raise ValueError("fractions must be strictly increasing")
        previous = fraction
    if interpolation not in {"linear", "nearest"}:
        raise ValueError("interpolation must be 'linear' or 'nearest'")

    sample = sorted(checked[instrument] for instrument in reference if instrument in checked)
    if not sample:
        raise ValueError("the Fama-French reference sample is empty")
    if len(sample) == 1:
        return tuple(sample[0] for _ in fractions)

    thresholds: list[Decimal] = []
    for fraction in fractions:
        position = Decimal(len(sample) - 1) * fraction
        if interpolation == "nearest":
            thresholds.append(sample[int(position.to_integral_value(rounding=ROUND_HALF_EVEN))])
            continue
        lower = int(position)
        upper = min(lower + 1, len(sample) - 1)
        weight = position - Decimal(lower)
        thresholds.append(sample[lower] + (sample[upper] - sample[lower]) * weight)
    return tuple(thresholds)


def fama_french_assign(
    values: Mapping[str, Decimal],
    *,
    thresholds: tuple[Decimal, ...],
    labels: tuple[str, ...],
) -> dict[str, str]:
    """Assign every name by value threshold, including names outside the reference subset.

    A value equal to a threshold remains in the lower bucket. Repeated thresholds are accepted:
    tied reference values can legitimately leave a middle bucket empty.
    """
    checked = _values(values)
    if not isinstance(thresholds, tuple) or not thresholds:
        raise ValueError("thresholds must be a non-empty tuple of Decimal")
    previous: Decimal | None = None
    for index, threshold in enumerate(thresholds):
        if not isinstance(threshold, Decimal):
            raise TypeError(
                f"thresholds[{index}] must be a Decimal; got {type(threshold).__name__}"
            )
        if not threshold.is_finite():
            raise ValueError("thresholds must be finite")
        if previous is not None and threshold < previous:
            raise ValueError("thresholds must be non-decreasing")
        previous = threshold
    if not isinstance(labels, tuple) or len(labels) != len(thresholds) + 1:
        raise ValueError("labels must contain exactly one more entry than thresholds")
    if any(not isinstance(label, str) or not label for label in labels):
        raise ValueError("labels must be non-empty strings")
    if len(set(labels)) != len(labels):
        raise ValueError("labels must be unique")

    assigned: dict[str, str] = {}
    for instrument, value in checked.items():
        index = 0
        while index < len(thresholds) and value > thresholds[index]:
            index += 1
        assigned[instrument] = labels[index]
    return assigned
