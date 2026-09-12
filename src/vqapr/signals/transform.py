"""Transforms from values to values: the signal side of what a strategy or a DataModel computes.

A transform is built in only where the implementation is hard or the methodology easy to get wrong:

- `rank` -- tie-aware `Decimal` ranking of a cross-section. Demeaning, z-scoring and clipping are
  clearer as ordinary arithmetic in the model that chooses them.
- `fama_french_cut_points` / `fama_french_assign` -- Fama-French sorts do not divide the universe
  into equal-count groups: they estimate value thresholds from a reference market (NYSE, KOSPI) and
  apply them to every eligible name. The unequal bucket counts are the methodology.
- `neutralize` -- regress a signal on exposures (the market, an industry, a size tilt) and keep the
  residual, the part the exposures do not explain. It is the file a project-local neutralisation is
  written against, so its shape matters as much as its arithmetic.

**These are transforms, not constraints.** A constraint has an identity, a projection to
per-instrument bounds and a measurement that returns findings; a transform takes values and returns
values, and the researcher decides whether to use it. Every function here is pure: no data, no
account, no clock -- what it needs arrives as arguments.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import ROUND_HALF_EVEN, Decimal
from fractions import Fraction
from typing import Literal

__all__ = [
    "NeutralizationRefusal",
    "fama_french_assign",
    "fama_french_cut_points",
    "neutralize",
    "rank",
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


_SCALE = Decimal(1).scaleb(-12)


class NeutralizationRefusal(ValueError):
    """Raised when a residual cannot be computed honestly.

    Carries the reason in the message, and for a rank deficient exposure the name of the column
    whose pivot vanished, because "the matrix is singular" tells a researcher nothing they can act
    on. With several mutually dependent columns the named one is whichever eliminated last, so it
    points at the dependency rather than identifying a unique culprit.
    """


def _fraction(value: Decimal, where: str) -> Fraction:
    if not isinstance(value, Decimal):
        raise TypeError(f"{where} must be a Decimal; got {type(value).__name__}")
    if not value.is_finite():
        raise ValueError(f"{where} must be finite")
    return Fraction(value)


def neutralize(
    signal: Mapping[str, Decimal],
    *,
    exposures: Mapping[str, Mapping[str, Decimal]],
    weights: Mapping[str, Decimal] | None = None,
) -> dict[str, Decimal]:
    """Return the part of ``signal`` that the given exposures do not explain.

    ``exposures`` maps an exposure name to its loading per instrument — a market column of ones, a
    set of industry dummies, a size column, or any combination. ``weights`` optionally weights the
    regression per instrument, which is how a market-capitalisation-weighted neutralisation is
    expressed; absent, every instrument counts equally.

    The result is the weighted least squares residual. The solve is exact, so the residual is
    orthogonal to every exposure column under the weights **exactly, before the return value is
    quantised** to twelve places; the returned Decimals carry that rounding, so a caller re-checking
    orthogonality on them sees agreement at that scale rather than a bare zero. Orthogonality on
    the rational residual is still the property worth testing, because it fails immediately for an
    identity transform, which is what makes it a real check rather than a restatement.

    Instruments missing from an exposure column are refused rather than treated as zero loading,
    because a zero loading is a claim that the instrument genuinely has none.
    """
    if not isinstance(signal, Mapping) or not signal:
        raise ValueError("signal must be a non-empty mapping of instrument to Decimal")
    if not isinstance(exposures, Mapping) or not exposures:
        raise ValueError("exposures must be a non-empty mapping of name to loadings")

    names = sorted(signal)
    y = [_fraction(signal[name], f"signal[{name!r}]") for name in names]

    columns: list[str] = sorted(exposures)
    matrix: list[list[Fraction]] = []
    for column in columns:
        loadings = exposures[column]
        if not isinstance(loadings, Mapping):
            raise TypeError(f"exposures[{column!r}] must be a mapping of instrument to Decimal")
        absent = sorted(set(names) - set(loadings))
        if absent:
            raise NeutralizationRefusal(
                f"exposure {column!r} has no loading for {absent}; "
                "a missing loading is not a zero loading"
            )
        matrix.append(
            [_fraction(loadings[name], f"exposures[{column!r}][{name!r}]") for name in names]
        )

    if weights is None:
        w = [Fraction(1)] * len(names)
    else:
        if not isinstance(weights, Mapping):
            raise TypeError("weights must be a mapping of instrument to Decimal")
        absent = sorted(set(names) - set(weights))
        if absent:
            raise NeutralizationRefusal(f"weights have no entry for {absent}")
        w = [_fraction(weights[name], f"weights[{name!r}]") for name in names]
        if any(value < 0 for value in w):
            raise NeutralizationRefusal("weights must not be negative")
        if sum(w) == 0:
            raise NeutralizationRefusal("weights must not all be zero")

    if len(names) <= len(columns):
        raise NeutralizationRefusal(
            f"{len(names)} instruments cannot support {len(columns)} exposures; "
            "the residual would be zero by construction"
        )

    # Normal equations in exact rationals: (B'WB) c = B'Wy, solved by Gaussian elimination.
    size = len(columns)
    augmented: list[list[Fraction]] = []
    for i in range(size):
        row = [
            sum((w[k] * matrix[i][k] * matrix[j][k] for k in range(len(names))), Fraction(0))
            for j in range(size)
        ]
        row.append(sum((w[k] * matrix[i][k] * y[k] for k in range(len(names))), Fraction(0)))
        augmented.append(row)

    for pivot in range(size):
        candidate = next(
            (r for r in range(pivot, size) if augmented[r][pivot] != 0),
            None,
        )
        if candidate is None:
            # Exact zero, not a small number. Under Fraction this is a structural fact about the
            # exposures rather than a threshold the caller has to tune, so it can be named.
            raise NeutralizationRefusal(
                f"exposure {columns[pivot]!r} is linearly dependent on the others; "
                "the residual is undefined"
            )
        augmented[pivot], augmented[candidate] = augmented[candidate], augmented[pivot]
        head = augmented[pivot][pivot]
        augmented[pivot] = [value / head for value in augmented[pivot]]
        for r in range(size):
            if r == pivot or augmented[r][pivot] == 0:
                continue
            factor = augmented[r][pivot]
            augmented[r] = [
                value - factor * augmented[pivot][index] for index, value in enumerate(augmented[r])
            ]

    coefficients = [augmented[i][size] for i in range(size)]
    residual = [
        y[k] - sum((coefficients[i] * matrix[i][k] for i in range(size)), Fraction(0))
        for k in range(len(names))
    ]
    return {
        name: (Decimal(value.numerator) / Decimal(value.denominator)).quantize(_SCALE)
        for name, value in zip(names, residual, strict=True)
    }
