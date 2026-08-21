"""A zero-friction venue listing exactly the sample instruments.

`AcademicExchange` is a shipped execution profile, so this subclass only declares which instruments
are listed and keeps the profile's own fill semantics. Replacing `execute` here would make the
realism claim unverified and the loader rejects it.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from vqapr.public import AcademicExchange, ListingAccess, TradeRule

WHOLE_SHARE = Decimal("1")
LONG_ONLY = ListingAccess.LONG_ONLY
"""Buy, and sell what is held. The sample never goes short."""


class SampleExchange(AcademicExchange):
    """Whole-share academic listings for the sample panel."""

    def __init__(self, instruments: Sequence[str]) -> None:
        super().__init__(
            {
                str(name): TradeRule(
                    instrument_id=str(name),
                    quantity_step=WHOLE_SHARE,
                    minimum_quantity=WHOLE_SHARE,
                    fractional_allowed=False,
                    access=LONG_ONLY,
                )
                for name in instruments
            },
            exchange_id="sample",
        )
