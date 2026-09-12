"""`invested` says what it is bounded to, and what that bound costs.

`docs/issues/archive/018`. The docstring frames `invested` as GROSS exposure and points out that cash can
exceed 1 and is never `1 - invested` -- a fair reading of which is that it is not capped at 1. It
is, and the two sides split it evenly on top, so `invested=1` on a signed book is 0.5 long and 0.5
short. Every number in the reporting journey therefore carried a caveat: the factor return it
measured is exactly half a textbook $1-long/$1-short SMB+HML.

The question this branch had to settle was whether the ceiling is an accounting invariant or a
leftover. It is neither exactly: the representation supports `+1/-1` with cash 1 and every
downstream invariant accepts it, so the ceiling belongs to this constructor alone. That is now
stated rather than left to be discovered.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from vqapr.domain.intent import Budget
from vqapr.public import PortfolioDirection, Rebalance


def test_the_refusal_names_the_legal_range_and_the_halving() -> None:
    """The refusal used to state the bound and stop, leaving the halving to be discovered."""
    with pytest.raises(ValueError) as raised:
        Rebalance.of(long={"A": 1}, short={"B": 1}, invested="2")

    message = str(raised.value)

    assert "no greater than one" in message, "the legal range is no longer stated"
    assert "0.5 long and 0.5 short" in message, (
        "the refusal states the bound without saying that the even split halves it again, which "
        "is the part that makes a textbook long/short book unreachable"
    )
    assert "2" in message, "the refusal does not say what was actually passed"


def test_invested_one_on_a_signed_book_is_half_a_textbook_book() -> None:
    """The arithmetic the docstring now states, pinned so it cannot drift silently."""
    book = Rebalance.of(long={"A": 1}, short={"B": 1}, invested="1")

    assert book.target_weights["A"] == Decimal("0.500000000000")
    assert book.target_weights["B"] == Decimal("-0.500000000000")
    # Dollar-neutral, so the whole book is at work and cash is still 1 -- the property that makes
    # `1 - invested` the wrong model of cash.
    assert book.cash_weight == Decimal("1")


def test_the_ceiling_is_the_constructors_and_not_the_accounts() -> None:
    """The finding that settles issue 018's open question.

    If a `+1/-1` book violated an accounting invariant, the cap would be load-bearing and the
    docs would simply have to say so. It does not: the signed budget admits positions in `[-1, 1]`
    and cash in `[-1, 2]`, and a `Rebalance` built directly at that scale is valid. So the cap is
    a property of `Rebalance.of`, and an author who needs the standard scale has a way through.
    """
    textbook = Rebalance(
        target_weights={"A": Decimal("1"), "B": Decimal("-1")},
        cash_weight=Decimal("1"),
        budget=Budget(
            direction=PortfolioDirection.SIGNED,
            cash_lower=Decimal(-1),
            cash_upper=Decimal(2),
            target_lower=Decimal(-1),
            target_upper=Decimal(1),
        ),
    )

    assert textbook.target_weights["A"] == Decimal("1")
    assert textbook.target_weights["B"] == Decimal("-1")


def test_the_docstring_states_the_bound_the_halving_and_the_consequence() -> None:
    """The merge condition, asserted on the text an author actually reads.

    A reader who takes `invested="1"` for a long/short book and never learns about the halving
    publishes a number that is half of what they think it is. That cannot be left to the source.
    """
    doc = Rebalance.of.__doc__ or ""

    assert "GROSS" in doc
    assert "0 < invested <= 1" in doc, "the docstring does not state the bound"
    assert "invested / 2" in doc, "the docstring does not state the halving"
    assert "half" in doc, "the docstring does not state what the ceiling costs"
    assert "accounting invariant" in doc, (
        "the docstring does not say the ceiling belongs to this constructor rather than the "
        "account, which is the question a reader hitting the cap actually has"
    )
