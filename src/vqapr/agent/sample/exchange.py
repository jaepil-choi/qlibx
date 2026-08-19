"""A zero-friction venue listing exactly the sample instruments.

`AcademicExchange` is a shipped execution profile, so this subclass only declares which instruments
are listed and keeps the profile's own fill semantics. Replacing `execute` here would make the
realism claim unverified and the loader rejects it.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from vqapr.domain.enums import Side
from vqapr.public import AcademicExchange, ListingRule

WHOLE_SHARE = Decimal("1")
BOTH_SIDES = frozenset({Side.BUY, Side.SELL})
"""Selling must be permitted or a position could never be closed."""


class SampleExchange(AcademicExchange):
    """Whole-share academic listings for the sample panel."""

    def __init__(self, instruments: Sequence[str]) -> None:
        super().__init__(
            {
                str(name): ListingRule(
                    instrument_id=str(name),
                    quantity_step=WHOLE_SHARE,
                    minimum_quantity=WHOLE_SHARE,
                    fractional_allowed=False,
                    permitted_sides=BOTH_SIDES,
                )
                for name in instruments
            },
            exchange_id="sample",
        )
