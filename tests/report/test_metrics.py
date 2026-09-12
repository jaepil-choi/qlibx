"""Performance statistics, and the type refusal that keeps a second return out of the system."""

from __future__ import annotations

from decimal import Decimal

import pytest

from vqapr.public import Mark, MarkBatch
from vqapr.report.metrics import drawdown, nav_series, returns


def _batch(**pairs: str) -> MarkBatch:
    marks = tuple(
        Mark(
            instrument_id=name,
            quantity=Decimal(1),
            price=Decimal(value),
            value=Decimal(value),
        )
        for name, value in pairs.items()
    )
    return MarkBatch(marks, sum((mark.value for mark in marks), Decimal(0)))


def test_nav_is_the_marked_value_plus_the_cash_beside_it() -> None:
    marks = [_batch(A="60", B="40"), _batch(A="70", B="40")]

    produced = nav_series(marks, cash=[Decimal(10), Decimal(5)])

    assert produced == (Decimal(110), Decimal(115))


def test_a_price_panel_is_refused_by_name() -> None:
    """The one mistake that would let an unreconciled performance number into the system."""
    panel = [{"A": Decimal(100), "B": Decimal(50)}]

    with pytest.raises(TypeError, match="must be a MarkBatch produced by the valuation spine"):
        nav_series(panel, cash=[Decimal(0)])  # type: ignore[arg-type]


def test_the_refusal_names_what_actually_arrived() -> None:
    with pytest.raises(TypeError, match="got str"):
        nav_series(["not a mark"], cash=[Decimal(0)])  # type: ignore[list-item]

    with pytest.raises(TypeError, match="got dict"):
        nav_series([{}], cash=[Decimal(0)])  # type: ignore[list-item]


def test_cash_must_correspond_to_the_marks() -> None:
    marks = [_batch(A="100"), _batch(A="110")]

    with pytest.raises(ValueError, match="they must correspond"):
        nav_series(marks, cash=[Decimal(0)])


def test_returns_are_one_shorter_than_the_nav_series() -> None:
    produced = returns([Decimal(100), Decimal(110), Decimal(99)])

    assert produced == (Decimal("0.1"), Decimal("-0.1"))
    assert len(produced) == 2


def test_a_flat_nav_series_returns_zeros() -> None:
    assert returns([Decimal(100), Decimal(100), Decimal(100)]) == (Decimal(0), Decimal(0))


def test_a_non_positive_starting_value_is_refused_rather_than_skipped() -> None:
    """Skipping would silently shorten a series the caller is about to align against dates."""
    with pytest.raises(ValueError, match="must be positive to define a return"):
        returns([Decimal(0), Decimal(10)])


def test_drawdown_measures_from_the_running_peak() -> None:
    """What an investor was living through, not what it looks like after the recovery."""
    produced = drawdown([Decimal(100), Decimal(120), Decimal(90), Decimal(150)])

    assert produced[0] == 0
    assert produced[1] == 0
    assert produced[2] == Decimal("-0.25"), "measured against 120, the peak at the time"
    assert produced[3] == 0


def test_drawdown_is_never_positive() -> None:
    produced = drawdown([Decimal(100), Decimal(150), Decimal(120), Decimal(200)])

    assert all(value <= 0 for value in produced)


def test_a_monotonic_series_never_draws_down() -> None:
    assert drawdown([Decimal(100), Decimal(110), Decimal(120)]) == (
        Decimal(0),
        Decimal(0),
        Decimal(0),
    )


def test_the_metrics_manufacture_no_return_of_their_own() -> None:
    """Canon's line: everything reported comes from the marking and Account spine.

    The module surface is the check. Nothing here accepts a price series: position value enters
    only as the type the valuation produces, and the fill summary reads the fill rows the run
    stored (record `275` folded the execution summary in beside the NAV series).
    """
    import vqapr.report.metrics as module

    assert set(module.__all__) == {"drawdown", "fill_summary", "nav_series", "returns"}
    for forbidden in ("from_prices", "compute_returns_from_prices", "price_return"):
        assert not hasattr(module, forbidden)
