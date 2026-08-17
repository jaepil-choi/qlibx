"""Vocabulary every layer may depend on and that depends on nothing."""

from __future__ import annotations

from enum import StrEnum


class Side(StrEnum):
    """The direction of one executed or requested quantity."""

    BUY = "buy"
    SELL = "sell"


def side_of(quantity: object) -> Side | None:
    """Return the side implied by a signed quantity, or ``None`` for an exact zero."""
    if quantity > 0:  # type: ignore[operator]
        return Side.BUY
    if quantity < 0:  # type: ignore[operator]
        return Side.SELL
    return None
