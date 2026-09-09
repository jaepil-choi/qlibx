"""The box a strategy builds inside: pure functions over instrument names and weights.

Design §7.1 (`docs/design/two-clocks-and-the-wiring-table.md`): **a constraint is not an extension
point.** Construction is best effort, best effort is discretion, and discretion is the strategy's,
so there is nothing for the framework to guarantee about it. What the framework ships is a kit --
functions a callback calls before `Rebalance`, each returning the lower and upper weight bound for
every name it was given:

    lo, hi = intersect(no_short(names), single_name_cap(names, benchmark, cap))
    return Rebalance(**optimize(desired=..., lower=lo, upper=hi, ...))

Everything here is a pure function of its arguments. A rule that needs data -- the cap needs the
benchmark's weight per name -- is handed it by the strategy, which subscribes to that dataset
itself, so the dependency is visible on the strategy where it belongs rather than hidden inside a
component's own `inputs()`. Observing whether the committed book actually respected a limit is a
different question with a different clock, and `vqapr.compliance` answers it (design §7.2).

Record `208`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from decimal import Decimal

__all__ = ["WeightBox", "intersect", "no_short", "single_name_cap"]

WeightBox = tuple[dict[str, Decimal], dict[str, Decimal]]
"""`(lower, upper)`: a weight bound per instrument on each side, covering the same names.

The two mappings are what `optimize` takes as `lower=` and `upper=`; nothing here is a type an
author has to construct.
"""

FLOOR = Decimal("0")
CEILING = Decimal("1")


def _names(instruments: Iterable[str]) -> tuple[str, ...]:
    names = tuple(instruments)
    if not names:
        raise ValueError("a box needs at least one instrument")
    if any(not isinstance(name, str) or not name for name in names):
        raise TypeError("instruments must be non-empty strings")
    if len(set(names)) != len(names):
        raise ValueError("instruments must be unique")
    return names


def _finite(value: object, *, name: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, Decimal) or not value.is_finite():
        raise TypeError(f"{name} must be a finite Decimal; got {value!r}")
    return value


def no_short(instruments: Iterable[str]) -> WeightBox:
    """`0 <= w_i <= 1` for every name: no negative weight.

    This is the function that makes long-only an emergent property of the box rather than a
    precondition on an input: a signed alpha enters construction unchanged, and it is this floor,
    intersected with whatever else the strategy declares, that removes the short leg. The ceiling
    is not padding -- a box covers every name on both sides, so a floor-only rule is
    inexpressible and the neutral upper bound keeps `intersect` well defined.
    """
    names = _names(instruments)
    return {name: FLOOR for name in names}, {name: CEILING for name in names}


def single_name_cap(
    instruments: Iterable[str], benchmark: Mapping[str, Decimal], cap: Decimal
) -> WeightBox:
    """`|w_i| <= max(cap, benchmark_i)`: no name larger than the cap, unless the index holds it
    larger, in which case the index weight is the ceiling.

    A cap on SIZE, symmetric: the floor mirrors the ceiling rather than sitting at zero, so a
    signed book with a cap is expressible and forbidding the short leg stays `no_short`'s job.
    Intersecting the two gives `(0, ceiling)` exactly. A name absent from `benchmark` is
    **confirmed** outside the index and takes the cap; a benchmark the strategy could not read
    at all never reaches here, because the strategy's own subscription fails first.

    `benchmark` is the strategy's to supply -- read through its declared inputs, validated as it
    sees fit (`validate_allocation` is the shipped check) -- which is what puts that dependency
    on the strategy's requirements where a reader of the run can see it.
    """
    names = _names(instruments)
    limit = _finite(cap, name="cap")
    if limit < 0:
        raise ValueError(f"cap must be non-negative; got {limit}")
    ceilings: dict[str, Decimal] = {}
    for name in names:
        weight = benchmark.get(name, FLOOR)
        ceilings[name] = max(limit, _finite(weight, name=f"benchmark[{name!r}]"))
    return {name: -ceiling for name, ceiling in ceilings.items()}, ceilings


def intersect(*boxes: WeightBox) -> WeightBox:
    """The box inside every given box: lower bounds take the max, upper bounds the min, name by
    name. Every box must cover the same names -- a missing bound would silently widen the
    feasible set, so it is refused rather than defaulted.
    """
    if not boxes:
        raise ValueError("intersect needs at least one box")
    first_lower, first_upper = boxes[0]
    names = _names(first_lower)
    if set(first_upper) != set(names):
        raise ValueError("a box's lower and upper bounds must cover the same instruments")
    lower = {name: _finite(first_lower[name], name=f"lower[{name!r}]") for name in names}
    upper = {name: _finite(first_upper[name], name=f"upper[{name!r}]") for name in names}
    for other_lower, other_upper in boxes[1:]:
        for side, other in (("lower", other_lower), ("upper", other_upper)):
            if set(other) != set(names):
                raise ValueError(
                    f"boxes must cover the same instruments: {side} differs on "
                    f"{sorted(set(other) ^ set(names))!r}"
                )
        for name in names:
            lower[name] = max(lower[name], _finite(other_lower[name], name=f"lower[{name!r}]"))
            upper[name] = min(upper[name], _finite(other_upper[name], name=f"upper[{name!r}]"))
    for name in names:
        if lower[name] > upper[name]:
            raise ValueError(
                f"the boxes do not intersect on {name!r}: lower {lower[name]} exceeds upper "
                f"{upper[name]}"
            )
    return lower, upper
