"""Typed, immutable economic budget declarations."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator


class PortfolioDirection(StrEnum):
    """The signedness permitted for a complete intended portfolio."""

    LONG_ONLY = "long_only"
    SIGNED = "signed"


class Budget(BaseModel):
    """Declared cash and per-position bounds for one economic intent.

    The declaration is a value, not a strategy-owned mutable configuration.  It
    therefore travels with the intent and is independently checked at the Flow
    boundary.

    **The two budgets the authoring constructors make, as numbers** -- named here because an
    author building a `Rebalance` directly had to reconstruct them from a sentence inside
    `Rebalance.of`'s docstring (`docs/issues/075`):

    ```python
    Budget(direction=PortfolioDirection.LONG_ONLY,   # Rebalance.of with no `short=`
           cash_lower=Decimal(0),  cash_upper=Decimal(1),
           target_lower=Decimal(0), target_upper=Decimal(1))

    Budget(direction=PortfolioDirection.SIGNED,      # Rebalance.of with `short=`, and .signed
           cash_lower=Decimal(-1), cash_upper=Decimal(2),
           target_lower=Decimal(-1), target_upper=Decimal(1))
    ```

    `cash_upper` is 2 on a signed book and not 1 because **selling short raises cash**: a book
    that is only short holds more than its NAV in cash, by exactly what it shorted. Pinning it at
    1 refused every short-only book, naming cash when the bound was what was wrong.

    Strict: every bound is a finite `Decimal` and the direction an enum member, refused rather
    than coerced -- an author's `cash_upper=1` is a different value from `Decimal(1)` downstream.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    direction: PortfolioDirection
    cash_lower: Decimal
    cash_upper: Decimal
    target_lower: Decimal
    target_upper: Decimal

    def __init__(
        self,
        direction: PortfolioDirection,
        cash_lower: Decimal,
        cash_upper: Decimal,
        target_lower: Decimal,
        target_upper: Decimal,
    ) -> None:
        # Positional as well as keyword: the shipped sample strategy and the tests spell the
        # five bounds in declaration order.
        super().__init__(
            direction=direction,
            cash_lower=cash_lower,
            cash_upper=cash_upper,
            target_lower=target_lower,
            target_upper=target_upper,
        )

    @model_validator(mode="after")
    def _ordered_and_signed(self) -> Self:
        if self.cash_lower > self.cash_upper:
            raise ValueError("cash_lower must not exceed cash_upper")
        if self.target_lower > self.target_upper:
            raise ValueError("target_lower must not exceed target_upper")
        if self.direction is PortfolioDirection.LONG_ONLY and (
            self.cash_lower < 0 or self.target_lower < 0
        ):
            raise ValueError("long_only budgets cannot permit negative cash or targets")
        return self

    def validates_cash(self, value: Decimal) -> bool:
        """Return whether an already-validated cash target is within this budget."""
        return self.cash_lower <= value <= self.cash_upper

    def validates_target(self, value: Decimal) -> bool:
        """Return whether an already-validated target is within this budget."""
        return self.target_lower <= value <= self.target_upper
