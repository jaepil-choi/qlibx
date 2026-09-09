"""A `Rebalance` refusal names the value it saw and the bound it crossed.

`docs/issues/archive/071`: `cash_weight is outside the declared budget` was the whole message for a book
whose quantised shorts summed to `-1.000000000001`, so cash was `2.000000000001` against a
`cash_upper` of `2`. The author reasoned both numbers out by hand. All five refusals in
`Rebalance`'s validator had the same shape: the rule, never the numbers.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from vqapr.authoring import Rebalance
from vqapr.portfolio.budgets import Budget, PortfolioDirection

SIGNED = Budget(PortfolioDirection.SIGNED, Decimal(-1), Decimal(2), Decimal(-1), Decimal(1))
LONG_ONLY = Budget(PortfolioDirection.LONG_ONLY, Decimal(0), Decimal(1), Decimal(0), Decimal(1))


def _refusal(**kw: object) -> str:
    """The sentence the validator wrote, out of the envelope pydantic wraps it in.

    `Rebalance` is a pydantic model, so the refusal reaches an author as a `ValidationError`
    carrying the validator's own `ValueError`; what this file pins is that sentence.
    """
    with pytest.raises(ValidationError) as refused:
        Rebalance(**kw)  # type: ignore[arg-type]
    (error,) = refused.value.errors()
    return str(error["ctx"]["error"])


def test_the_cash_refusal_carries_the_cash_and_both_bounds() -> None:
    message = _refusal(
        target_weights={"A": Decimal("-1")}, cash_weight=Decimal("2.000000000001"), budget=SIGNED
    )
    assert message == "cash_weight 2.000000000001 is outside the declared budget [-1, 2]"


def test_the_target_refusal_names_the_offending_weights_and_the_bounds() -> None:
    message = _refusal(
        target_weights={"A": Decimal("1.5"), "B": Decimal("-1.5")},
        cash_weight=Decimal(1),
        budget=SIGNED,
    )
    assert message == (
        "target_weights are outside the declared budget bounds [-1, 1]: A=1.5, B=-1.5"
    )


def test_the_offenders_are_bounded_like_examples() -> None:
    weights = {f"N{i:02d}": Decimal("1.5") for i in range(12)}
    wide_cash = Budget(PortfolioDirection.SIGNED, Decimal(-100), Decimal(100), Decimal(-1), Decimal(1))
    message = _refusal(target_weights=weights, cash_weight=Decimal(-17), budget=wide_cash)
    assert message.endswith("N04=1.5, and 7 more"), message


def test_a_negative_weight_under_long_only_is_named_with_the_bound_it_crossed() -> None:
    """`Budget` refuses a long-only budget whose `target_lower` is negative, so a negative weight
    under long-only is always caught by the bounds check first; the dedicated long-only refusal
    behind it is defensive. Either way the weight is named."""
    message = _refusal(
        target_weights={"A": Decimal("0.6"), "B": Decimal("-0.1")},
        cash_weight=Decimal("0.5"),
        budget=LONG_ONLY,
    )
    assert message == "target_weights are outside the declared budget bounds [0, 1]: B=-0.1"


def test_the_sum_refusal_shows_the_arithmetic() -> None:
    message = _refusal(
        target_weights={"A": Decimal("0.5")}, cash_weight=Decimal("0.4"), budget=LONG_ONLY
    )
    assert message == (
        "target_weights plus cash_weight must equal one; got "
        "sum(target_weights) 0.5 + cash_weight 0.4 = 0.9"
    )


def test_the_empty_book_refusal_shows_the_cash() -> None:
    message = _refusal(target_weights={}, cash_weight=Decimal("0.9"), budget=LONG_ONLY)
    assert message == "an empty complete position set requires cash_weight equal to one; got 0.9"
