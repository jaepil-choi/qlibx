"""Remove an exposure from a signal, so what is left is what the exposure does not explain.

A signal that looks predictive can simply be riding something: the market, an industry, a size
tilt. Regressing the signal on those exposures and keeping the residual leaves the part that is not
explained by them. Canon calls this file the origin that a project-local neutralisation is written
against, so its shape matters as much as its arithmetic.

**This is a transform, not a constraint.** A constraint has a declared identity, three consumers, a
projection to per-instrument bounds and a measurement returning findings. Neutralisation has none of
that: it takes values and returns values, and the researcher decides whether to use it. Nothing here
should ever grow a `constraint_id`.

Arithmetic is exact. The solve runs in `Fraction`, matching the shipped optimizer, and only crosses
back to `Decimal` at the boundary. That is not fastidiousness — it is what makes the refusal honest.
Under floating point a rank deficient exposure matrix is a small pivot and the code has to guess a
threshold; under exact rational arithmetic it is a zero pivot, so deficiency is a structural fact
that can be detected and named rather than a tunable number.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from fractions import Fraction

__all__ = ["NeutralizationRefusal", "neutralize"]

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
