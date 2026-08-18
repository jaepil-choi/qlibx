"""Netting is a measurement, so every property is checkable from the numbers alone."""

from __future__ import annotations

from decimal import Decimal

import pytest

from vqapr.portfolio.diagnostics import TickerNetting, net_members


def test_the_offset_recovers_what_the_net_hides() -> None:
    """This is why the measurement exists at all.

    A net of zero has two completely different meanings and the final weight cannot tell them
    apart: either nobody held the name, or two members wanted opposite sides and cancelled exactly.
    UC-ENSEMBLE-001 requires the offsetting quantity to be confirmable precisely because of this.
    """
    cancelled = net_members([{"X": Decimal("0.3")}, {"X": Decimal("-0.3")}])["X"]
    absent = net_members([{"X": Decimal("0")}, {"X": Decimal("0")}])["X"]

    assert cancelled.net_weight == absent.net_weight == 0
    assert cancelled.offset_weight == Decimal("0.3")
    assert absent.offset_weight == 0


def test_each_side_is_summed_and_the_offset_is_the_smaller_one() -> None:
    members = [
        {"X": Decimal("0.5"), "Y": Decimal("-0.3")},
        {"X": Decimal("-0.2"), "Y": Decimal("-0.1")},
    ]

    measured = net_members(members)

    assert measured["X"].long_weight == Decimal("0.5")
    assert measured["X"].short_weight == Decimal("-0.2")
    assert measured["X"].offset_weight == Decimal("0.2"), "the smaller side is what cancelled"
    assert measured["X"].net_weight == Decimal("0.3")

    assert measured["Y"].offset_weight == 0, "agreeing members offset nothing"
    assert measured["Y"].net_weight == Decimal("-0.4")


def test_the_net_always_equals_the_two_sides() -> None:
    members = [
        {"A": Decimal("0.4"), "B": Decimal("-0.6"), "C": Decimal("0.1")},
        {"A": Decimal("-0.9"), "B": Decimal("0.2")},
        {"A": Decimal("0.25"), "C": Decimal("-0.05")},
    ]

    for measured in net_members(members).values():
        assert measured.net_weight == measured.long_weight + measured.short_weight
        assert measured.offset_weight >= 0
        assert measured.offset_weight == min(measured.long_weight, -measured.short_weight)


def test_a_member_that_omits_an_instrument_holds_nothing_there() -> None:
    """Absence in a published panel means no position, not an unknown."""
    measured = net_members([{"X": Decimal("0.5")}, {"Y": Decimal("-0.5")}])

    assert set(measured) == {"X", "Y"}
    assert measured["X"].short_weight == 0
    assert measured["Y"].long_weight == 0


def test_the_universe_can_be_declared_so_a_missing_name_stays_visible() -> None:
    measured = net_members(
        [{"X": Decimal("0.5")}, {"X": Decimal("-0.5")}], instruments=("X", "UNHELD")
    )

    assert set(measured) == {"X", "UNHELD"}
    assert measured["UNHELD"].net_weight == 0
    assert measured["UNHELD"].offset_weight == 0


def test_netting_needs_at_least_two_members() -> None:
    with pytest.raises(ValueError, match="at least two members"):
        net_members([{"X": Decimal("1")}])


def test_a_float_weight_is_refused() -> None:
    with pytest.raises(TypeError, match="must be a Decimal"):
        net_members([{"X": 0.5}, {"X": Decimal("-0.5")}])  # type: ignore[list-item]


def test_measurement_is_order_independent() -> None:
    a = {"X": Decimal("0.5"), "Y": Decimal("-0.2")}
    b = {"X": Decimal("-0.3"), "Y": Decimal("0.1")}
    c = {"X": Decimal("0.1")}

    assert net_members([a, b, c]) == net_members([c, b, a])


def test_the_result_is_a_measurement_not_an_allocation() -> None:
    """A guard against this quietly becoming the combination helper record 010 prohibits.

    The return type is per-ticker evidence, not a weight mapping, so it cannot be handed to
    `plan_orders` or published as an allocation without the Strategy deciding what to do with it.
    """
    measured = net_members([{"X": Decimal("0.5")}, {"X": Decimal("-0.2")}])

    assert all(isinstance(value, TickerNetting) for value in measured.values())
    assert not all(isinstance(value, Decimal) for value in measured.values())
