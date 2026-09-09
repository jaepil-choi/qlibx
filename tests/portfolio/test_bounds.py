"""The box kit (design §7.1, record `208`): pure functions a strategy calls before `Rebalance`.

`no_short`, `single_name_cap` and `intersect` replaced the `project` member of the retired
`Constraint` extension point. What that member guaranteed -- both bounds for every name, a symmetric
cap lifted to the index weight, long-only emerging from the intersection rather than from either
rule alone -- is what these pin, on the same numbers.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from vqapr.portfolio.bounds import intersect, no_short, single_name_cap
from vqapr.portfolio.optimize import optimize

NAMES = ("A", "B", "C")


def test_no_short_gives_both_bounds_for_every_name() -> None:
    """A floor-only box is inexpressible: the neutral ceiling keeps `intersect` well defined."""
    lower, upper = no_short(NAMES)

    assert lower == {name: Decimal("0") for name in NAMES}
    assert upper == {name: Decimal("1") for name in NAMES}


def test_single_name_cap_lifts_the_ceiling_to_the_index_weight_and_mirrors_the_floor() -> None:
    """A name may always be held at its index weight; the cap governs the rest -- on SIZE."""
    benchmark = {"A": Decimal("0.25"), "B": Decimal("0.05")}

    lower, upper = single_name_cap(NAMES, benchmark, Decimal("0.10"))

    assert upper == {"A": Decimal("0.25"), "B": Decimal("0.10"), "C": Decimal("0.10")}, (
        "the index weight where heavier than the cap, the cap where lighter, the cap where absent"
    )
    assert lower == {name: -ceiling for name, ceiling in upper.items()}, (
        "the cap bounds size, so its floor mirrors its ceiling rather than flooring at zero"
    )


def test_long_only_emerges_from_intersecting_the_two() -> None:
    """Neither function alone is long-only-with-a-cap; the box inside both is."""
    benchmark = {"A": Decimal("0.25")}

    lower, upper = intersect(no_short(NAMES), single_name_cap(NAMES, benchmark, Decimal("0.10")))

    assert lower == {name: Decimal("0") for name in NAMES}, "the floor comes from no_short alone"
    assert upper == {"A": Decimal("0.25"), "B": Decimal("0.10"), "C": Decimal("0.10")}
    # And the box is what `optimize` takes, unchanged.
    result = optimize(
        desired={"A": Decimal("0.5"), "B": Decimal("-0.2"), "C": Decimal("0.1")},
        current={},
        lower=lower,
        upper=upper,
        cash_range=(Decimal("0"), Decimal("1")),
    )
    assert result.weights["A"] == Decimal("0.25") and result.weights["B"] == Decimal("0")


def test_intersect_refuses_a_box_that_misses_a_name() -> None:
    """A missing bound would silently widen the feasible set, so it is refused, not defaulted."""
    with pytest.raises(ValueError, match="same instruments"):
        intersect(no_short(NAMES), no_short(("A", "B")))
    with pytest.raises(ValueError, match="do not intersect"):
        intersect(
            ({"A": Decimal("0.5")}, {"A": Decimal("1")}), ({"A": Decimal("0")}, {"A": Decimal("0.2")})
        )


def test_the_kit_refuses_what_it_cannot_bound() -> None:
    with pytest.raises(ValueError, match="at least one instrument"):
        no_short(())
    with pytest.raises(ValueError, match="unique"):
        no_short(("A", "A"))
    with pytest.raises(ValueError, match="non-negative"):
        single_name_cap(NAMES, {}, Decimal("-0.1"))
    with pytest.raises(TypeError, match="finite Decimal"):
        single_name_cap(NAMES, {"A": 0.1}, Decimal("0.1"))  # type: ignore[dict-item]
