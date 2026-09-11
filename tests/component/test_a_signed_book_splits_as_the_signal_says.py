"""`Rebalance.signed`, and the exactness `Rebalance.of` gained by delegating to `rescale`.

`docs/issues/archive/075`. The specification was ordinary for a market-neutral residual strategy: signed
weights whose absolute values sum to one, the long/short split being whatever the signal produced,
cash the net residual. `of` structurally cannot say it -- it takes two mappings and splits
`invested` EVENLY between them -- and its docstring pointed at the direct constructor, which the
author then had to fill by assembling three docstrings: what a valid `Budget` is, where the
canonical grid lives, and that quantising has to be settled afterwards.

Two things are tested here.

**`signed` exists and the ratio is the signal's.** Seven longs against eleven shorts comes out
0.389 long and -0.611 short, not 0.5/-0.5.

**`of` is now exact in gross.** It used to quantise and settle a second copy of `rescale`'s
arithmetic, with one book-wide residual placed on the single largest position. A crumb from the
SHORT side could therefore land on a LONG name: `of(long={"A": 1}, short={"B": 1, "C": 1, "D": 1})`
returned `A = 0.500000000001`, so a book asking for `invested=1` came out with gross
1.000000000002. `invested` is documented as gross exposure. Settling per side makes it exact.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from vqapr.authoring import Rebalance
from vqapr.domain.intent import PortfolioDirection
from vqapr.portfolio.optimize import QUANTUM


def _sides(book: Rebalance) -> tuple[Decimal, Decimal]:
    weights = book.target_weights.values()
    return (
        sum((value for value in weights if value > 0), Decimal(0)),
        sum((value for value in weights if value < 0), Decimal(0)),
    )


# ---------------------------------------------------------------------------------------------
# `Rebalance.signed`
# ---------------------------------------------------------------------------------------------


def test_the_split_is_the_signals_not_an_even_one() -> None:
    """The headline. Seven longs against eleven shorts is not a 50/50 book.

    This is the case `of` cannot express at all: it would give 0.5 and -0.5 whatever the signal
    said, because it splits `invested` evenly between the two mappings.
    """
    signal = {**{f"L{i}": 1 for i in range(7)}, **{f"S{i}": -1 for i in range(11)}}

    long_side, short_side = _sides(Rebalance.signed(signal))

    assert long_side == Decimal("0.388888888889"), long_side  # 7/18
    assert short_side == Decimal("-0.611111111111"), short_side  # -11/18


def test_gross_two_is_the_textbook_book_of_cannot_reach() -> None:
    """`docs/issues/archive/018` documented that `of` tops out at half a textbook book. This is the half.

    `gross=2` is $1 long and $1 short, which is the scale a published SMB or HML series is quoted
    at, and the scale a factor arm has to reach to be compared against one.
    """
    book = Rebalance.signed({"A": 1, "C": -1}, gross=2)

    assert _sides(book) == (Decimal(1), Decimal(-1))
    assert book.cash_weight == Decimal(1), "a dollar-neutral book is fully invested and nets zero"


def test_the_sign_carries_the_side_and_gross_is_absolute() -> None:
    """Opposite convention to `of`, deliberately: different input, so it can afford one."""
    book = Rebalance.signed({"A": 2, "B": 1, "C": -1, "D": -2})

    assert book.target_weights["A"] > 0 and book.target_weights["D"] < 0
    assert sum(abs(value) for value in book.target_weights.values()) == Decimal(1)


def test_cash_is_the_net_residual_never_one_minus_gross() -> None:
    """Three books whose cash differs while their gross is the same."""
    neutral = Rebalance.signed({"A": 1, "B": -1})
    long_only = Rebalance.signed({"A": 1, "B": 1})
    short_heavy = Rebalance.signed({"A": 1, "B": -3})

    assert neutral.cash_weight == Decimal(1), "fully invested, nets to zero"
    assert long_only.cash_weight == Decimal(0), "fully invested long"
    assert short_heavy.cash_weight == Decimal("1.500000000000"), "shorting raises cash"


def test_the_budget_is_signed_even_when_the_signal_found_no_shorts() -> None:
    """A budget that flipped to LONG_ONLY on a day with no shorts would refuse the next day.

    The author reached for the signed constructor; the book is signed whatever this particular
    signal happened to produce.
    """
    budget = Rebalance.signed({"A": 1, "B": 1}).budget

    assert budget.direction is PortfolioDirection.SIGNED
    assert (budget.target_lower, budget.target_upper) == (Decimal(-1), Decimal(1))
    assert (budget.cash_lower, budget.cash_upper) == (Decimal(-1), Decimal(2))


def test_a_zero_weight_is_kept_as_a_flat_position() -> None:
    """Dropping it would make the returned book disagree with the mapping the author passed."""
    book = Rebalance.signed({"A": 1, "B": 0, "C": -1})

    assert set(book.target_weights) == {"A", "B", "C"}
    assert book.target_weights["B"] == 0


@pytest.mark.parametrize(
    ("label", "kwargs", "says"),
    [
        ("every weight zero", {"weights": {"A": 0, "B": 0}}, "at least one non-zero weight"),
        ("gross of zero", {"weights": {"A": 1}, "gross": 0}, "greater than zero"),
        ("negative gross", {"weights": {"A": 1}, "gross": -1}, "greater than zero"),
    ],
)
def test_a_refusal_names_the_value_and_the_rule(label: str, kwargs: dict, says: str) -> None:
    with pytest.raises(ValueError) as refused:
        Rebalance.signed(**kwargs)
    assert says in str(refused.value), (label, str(refused.value))


def test_an_empty_mapping_is_refused_before_any_arithmetic() -> None:
    with pytest.raises(TypeError):
        Rebalance.signed({})


def test_a_side_finer_than_the_grid_is_refused_rather_than_rounded_away() -> None:
    """A short side that would quantise to zero is a refusal, not a silently long-only book."""
    with pytest.raises(ValueError) as refused:
        Rebalance.signed({"A": 1, "B": Decimal("-1E-20")}, gross=QUANTUM)
    assert "canonical grid" in str(refused.value), refused.value


# ---------------------------------------------------------------------------------------------
# What `of` gained by delegating
# ---------------------------------------------------------------------------------------------


def test_of_now_lands_each_side_exactly_on_its_target() -> None:
    """The measured regression. `A` used to be `0.500000000001` -- the shorts' crumb, on a long.

    Three shorts at -0.5/3 do not divide evenly. The old book-wide settle put that residual on
    the largest position by absolute size, which is the LONG, so the long side missed the target
    it was given and gross missed `invested`.
    """
    book = Rebalance.of(long={"A": 1}, short={"B": 1, "C": 1, "D": 1})

    assert book.target_weights["A"] == Decimal("0.500000000000")
    long_side, short_side = _sides(book)
    assert long_side == Decimal("0.500000000000")
    assert short_side == Decimal("-0.500000000000")


@pytest.mark.parametrize(
    ("label", "kwargs"),
    [
        ("one long against three shorts", {"long": {"A": 1}, "short": {"B": 1, "C": 1, "D": 1}}),
        ("seven against eleven", {
            "long": {f"L{i}": 1 for i in range(7)},
            "short": {f"S{i}": 1 for i in range(11)},
        }),
        ("uneven conviction", {"long": {"A": 3, "B": 2, "C": 1}, "short": {"D": 5, "E": 2}}),
        ("part invested", {"long": {"A": 2, "B": 1}, "short": {"C": 1, "D": 1, "E": 1},
                           "invested": "0.9"}),
    ],
)
def test_gross_exposure_equals_invested_exactly(label: str, kwargs: dict) -> None:
    """`invested` is documented as GROSS exposure, so it has to be gross exactly.

    Every case here has a side that does not divide evenly onto the grid, which is where the old
    book-wide settle left gross a few ulps away from what the author asked for.
    """
    book = Rebalance.of(**kwargs)
    asked = Decimal(str(kwargs.get("invested", 1)))

    gross = sum(abs(value) for value in book.target_weights.values())
    assert gross == asked.quantize(QUANTUM), (label, gross)
    assert sum(book.target_weights.values()) + book.cash_weight == Decimal(1), label


def test_invested_below_one_grid_step_is_refused_not_rounded_to_an_empty_book() -> None:
    """It used to return a book of zeros with cash 1 -- a decision that says nothing.

    Refusing is the honest answer: nothing the author asked for can be represented.
    """
    with pytest.raises(ValueError) as refused:
        Rebalance.of(long={"A": 1}, short={"B": 1}, invested=QUANTUM / 4)
    assert "canonical grid" in str(refused.value), refused.value
