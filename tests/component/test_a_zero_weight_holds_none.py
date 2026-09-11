"""`Rebalance.of` takes a zero weight as "hold none of this name", as `Rebalance.signed` does.

Report 2026-09-11 (`docs/issues/report-2026-09-11-rebalance-of-refuses-a-zero-weight-that-
rebalance-signed-keeps.md`): an enhanced index that underweights a name by 0.5%p, floored at zero,
returned `Rebalance.of(long={..., "A000100": 0})` and the run stopped with a refusal about how
sides are chosen. The owner ruled (2026-09-11) that `of` accepts the zero (record `260`).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from vqapr.authoring import Rebalance
from vqapr.domain.intent import PortfolioDirection


def test_a_zero_is_kept_as_a_flat_position() -> None:
    book = Rebalance.of(long={"A": 1, "B": 0})

    assert book.target_weights["A"] == Decimal(1)
    assert book.target_weights["B"] == Decimal(0)
    assert book.cash_weight == Decimal(0)


def test_the_two_constructors_agree_on_a_zero() -> None:
    assert dict(Rebalance.of(long={"A": 3, "B": 0, "C": 1}).target_weights) == dict(
        Rebalance.signed({"A": 3, "B": 0, "C": 1}).target_weights
    )


def test_a_side_of_zeros_is_no_side() -> None:
    """A short mapping of zeros neither halves the long side nor makes the book signed."""
    book = Rebalance.of(long={"A": 1}, short={"B": 0})

    assert book.target_weights["A"] == Decimal(1)
    assert book.target_weights["B"] == Decimal(0)
    assert book.budget.direction is PortfolioDirection.LONG_ONLY


def test_a_book_of_only_zeros_is_refused() -> None:
    with pytest.raises(ValueError, match="at least one non-zero weight"):
        Rebalance.of(long={"A": 0, "B": 0})


def test_a_negative_is_still_refused_with_the_side_rule() -> None:
    with pytest.raises(ValueError, match="must not be negative: a side is chosen"):
        Rebalance.of(long={"A": 1, "B": -1})
