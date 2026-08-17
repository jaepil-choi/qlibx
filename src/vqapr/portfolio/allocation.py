"""The allocation input contract.

An allocation input is defined by **declared invariants, not by provenance**. Registered
point-in-time data and a published run output are the same kind of input whenever the invariants
hold, so a benchmark needs no synthetic run and an alpha result needs no special reader. Both are
consumed through the ordinary ``DataRequirement`` path.

Two decisions are load-bearing:

* **Validation happens at consumption time**, not at registration and not at preflight. That is the
  only point where point-in-time semantics are available, so an index constituent change is absorbed
  naturally instead of invalidating a registration, and a slice is judged on exactly the rows a
  consumer can actually see.
* **The weight-sum invariant is coverage-scoped.** A real four-name slice of a two-hundred-name
  index sums to roughly ``0.549``. Requiring one would reject genuine vendor data; renormalising it
  would silently restate the vendor's numbers as something they are not. The uncovered remainder is
  not missing, it is cash.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class AllocationSign(StrEnum):
    """Which directions an allocation input is allowed to express."""

    LONG_ONLY = "long_only"
    SIGNED = "signed"


class AllocationViolation(ValueError):
    """A typed refusal raised before any mutation, naming the invariant and the offender."""


@dataclass(frozen=True, slots=True)
class AllocationInvariants:
    """What an allocation input promises, declared by its consumer.

    ``weight_sum_upper`` is an upper bound rather than an equality precisely because coverage is
    partial. ``tolerance`` is supplied by the caller from the fixture manifest rather than restated
    as a package constant, so regenerating source data over a finer-published window tightens the
    allowance instead of leaving a stale one that would admit a real error.
    """

    sign: AllocationSign
    weight_sum_upper: Decimal
    tolerance: Decimal
    required_coverage: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not isinstance(self.sign, AllocationSign):
            raise TypeError("sign must be an AllocationSign")
        for name, value in (
            ("weight_sum_upper", self.weight_sum_upper),
            ("tolerance", self.tolerance),
        ):
            if not isinstance(value, Decimal):
                raise TypeError(f"{name} must be a Decimal")
            if not value.is_finite() or value < 0:
                raise ValueError(f"{name} must be finite and non-negative")
        if not isinstance(self.required_coverage, frozenset):
            raise TypeError("required_coverage must be a frozenset")
        if any(not isinstance(name, str) or not name for name in self.required_coverage):
            raise ValueError("required_coverage must contain non-empty instrument identifiers")

    @classmethod
    def of(
        cls,
        *,
        sign: AllocationSign = AllocationSign.LONG_ONLY,
        weight_sum_upper: Decimal = Decimal(1),
        tolerance: Decimal,
        required_coverage: Sequence[str] = (),
    ) -> AllocationInvariants:
        return cls(sign, weight_sum_upper, tolerance, frozenset(required_coverage))


@dataclass(frozen=True, slots=True)
class ValidatedAllocation:
    """One allocation input that satisfied its declared invariants."""

    weights: Mapping[str, Decimal]
    total: Decimal
    uncovered: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(self, "weights", dict(self.weights))


def validate_allocation(
    weights: Mapping[str, Decimal],
    invariants: AllocationInvariants,
    *,
    label: str = "allocation input",
) -> ValidatedAllocation:
    """Check one allocation slice against its declared invariants, or refuse.

    Nothing is repaired here. A violation is a typed refusal raised before any mutation, because a
    silently renormalised or clipped input would make every downstream number describe a portfolio
    the source data never expressed.
    """
    if not isinstance(weights, Mapping) or not weights:
        raise AllocationViolation(f"{label} must be a non-empty mapping of instrument to weight")

    total = Decimal(0)
    for instrument in sorted(weights):
        weight = weights[instrument]
        if not isinstance(instrument, str) or not instrument:
            raise AllocationViolation(f"{label} has a non-string instrument identifier")
        if not isinstance(weight, Decimal):
            raise AllocationViolation(
                f"{label} weight for {instrument!r} must be a Decimal; got {type(weight).__name__}"
            )
        if not weight.is_finite():
            raise AllocationViolation(f"{label} weight for {instrument!r} must be finite")
        if invariants.sign is AllocationSign.LONG_ONLY and weight < 0:
            raise AllocationViolation(
                f"{label} declares {AllocationSign.LONG_ONLY.value} but "
                f"{instrument!r} carries {weight}"
            )
        total += weight

    missing = sorted(invariants.required_coverage - set(weights))
    if missing:
        raise AllocationViolation(f"{label} does not cover required instruments: {missing}")

    ceiling = invariants.weight_sum_upper + invariants.tolerance
    if total > ceiling:
        raise AllocationViolation(
            f"{label} weights sum to {total}, above the declared "
            f"{invariants.weight_sum_upper} by more than the {invariants.tolerance} tolerance"
        )

    # A shortfall is legal and meaningful: it is the uncovered part of the universe, and it becomes
    # cash rather than being spread across the covered names.
    return ValidatedAllocation(
        weights=weights, total=total, uncovered=invariants.weight_sum_upper - total
    )
