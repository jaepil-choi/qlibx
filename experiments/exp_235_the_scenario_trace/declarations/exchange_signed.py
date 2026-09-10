"""The sample venue with short sales allowed: the same ten names, `ListingAccess.SIGNED`.

A factor strategy sells the weakest names short; the shipped sample exchange lists every name
`LONG_ONLY`, so a signed book needs a venue that says so. Nothing else changes: whole shares,
the academic fill.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from vqapr.public import AcademicExchange, ListingAccess, TradeRule

WHOLE_SHARE = Decimal("1")


class SampleSignedExchange(AcademicExchange):
    """Whole-share academic listings, long and short, for the sample panel."""

    def __init__(self, instruments: Sequence[str]) -> None:
        super().__init__(
            {
                str(name): TradeRule(
                    instrument_id=str(name),
                    quantity_step=WHOLE_SHARE,
                    minimum_quantity=WHOLE_SHARE,
                    fractional_allowed=False,
                    access=ListingAccess.SIGNED,
                )
                for name in instruments
            },
            exchange_id="sample-signed",
        )
