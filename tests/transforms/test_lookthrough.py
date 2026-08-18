"""Look-through, checked against arithmetic that is known before the code runs."""

from __future__ import annotations

from decimal import Decimal

import pytest

from vqapr.transforms.lookthrough import InstrumentExposure, look_through


def test_the_canon_worked_example_reproduces_exactly() -> None:
    """Canon states this one in full, so it is the first thing that must hold.

    A vehicle holding A at 50%, B at 30% and C at 20%; five percent of A held outright and ten
    percent of the vehicle. The stated answer for A is `0.05 + 0.10 * 0.5 = 0.10`.
    """
    exposed = look_through(
        {"A": Decimal("0.05"), "X": Decimal("0.10")},
        composition={"X": {"A": Decimal("0.5"), "B": Decimal("0.3"), "C": Decimal("0.2")}},
    )

    assert exposed["A"].total == Decimal("0.10")
    assert exposed["A"].direct == Decimal("0.05")
    assert exposed["A"].indirect == Decimal("0.05")
    assert exposed["B"].total == Decimal("0.03")
    assert exposed["C"].total == Decimal("0.02")


def test_a_vehicle_is_a_means_and_not_an_exposure() -> None:
    """Canon: the matrix has a column for the vehicle and no row for it."""
    exposed = look_through(
        {"X": Decimal("1")}, composition={"X": {"A": Decimal("0.6"), "B": Decimal("0.4")}}
    )

    assert "X" not in exposed
    assert set(exposed) == {"A", "B"}


def test_direct_and_indirect_stay_separable() -> None:
    """The split is what a reader cannot recover afterwards, so it is not collapsed."""
    outright = look_through({"A": Decimal("0.10")}, composition={})
    through = look_through({"X": Decimal("0.10")}, composition={"X": {"A": Decimal(1)}})

    assert outright["A"].total == through["A"].total == Decimal("0.10")
    assert outright["A"].direct == Decimal("0.10") and outright["A"].indirect == 0
    assert through["A"].direct == 0 and through["A"].indirect == Decimal("0.10")


def test_exposure_through_several_vehicles_accumulates() -> None:
    exposed = look_through(
        {"X": Decimal("0.4"), "Y": Decimal("0.6")},
        composition={"X": {"A": Decimal("0.5")}, "Y": {"A": Decimal("0.5")}},
    )

    assert exposed["A"].indirect == Decimal("0.5")
    assert exposed["A"].total == Decimal("0.5")


def test_an_ordinary_book_with_no_vehicles_is_the_identity() -> None:
    holdings = {"A": Decimal("0.6"), "B": Decimal("0.4")}

    exposed = look_through(holdings, composition={})

    assert {name: value.total for name, value in exposed.items()} == holdings
    assert all(value.indirect == 0 for value in exposed.values())


def test_a_held_vehicle_with_no_constituents_is_refused_by_name() -> None:
    """Treating it as opaque would understate exposure exactly where look-through matters."""
    with pytest.raises(ValueError, match=r"non-empty mapping"):
        look_through({"X": Decimal(1)}, composition={"X": {}})


def test_the_package_never_expands_a_holding_on_its_own() -> None:
    """Canon: no auto-discovery. An undescribed instrument is held outright, never expanded."""
    exposed = look_through({"A069500": Decimal("0.2"), "A005930": Decimal("0.8")}, composition={})

    assert exposed["A069500"].direct == Decimal("0.2")
    assert exposed["A069500"].indirect == 0, "a ticker convention must not trigger expansion"


def test_a_negative_holding_carries_its_sign_through() -> None:
    exposed = look_through(
        {"X": Decimal("-0.5")}, composition={"X": {"A": Decimal("0.4"), "B": Decimal("0.6")}}
    )

    assert exposed["A"].total == Decimal("-0.20")
    assert exposed["B"].total == Decimal("-0.30")


def test_a_stub_returning_its_input_would_fail_these() -> None:
    """The criterion has to be able to kill a no-op, so state the case that does it."""
    holdings = {"X": Decimal("0.10")}
    exposed = look_through(holdings, composition={"X": {"A": Decimal("0.5"), "B": Decimal("0.5")}})

    assert set(exposed) != set(holdings)
    assert exposed["A"].total == Decimal("0.05")


def test_floats_and_infinities_are_refused_on_both_panels() -> None:
    with pytest.raises(TypeError, match="must be a Decimal"):
        look_through({"A": 0.5}, composition={})  # type: ignore[dict-item]

    with pytest.raises(TypeError, match="must be a Decimal"):
        look_through({"X": Decimal(1)}, composition={"X": {"A": 0.5}})  # type: ignore[dict-item]

    with pytest.raises(ValueError, match="must be finite"):
        look_through({"A": Decimal("Infinity")}, composition={})


def test_the_result_reports_provenance_rather_than_a_bare_weight() -> None:
    exposed = look_through({"A": Decimal("0.1")}, composition={})

    assert all(isinstance(value, InstrumentExposure) for value in exposed.values())
    assert not all(isinstance(value, Decimal) for value in exposed.values())
