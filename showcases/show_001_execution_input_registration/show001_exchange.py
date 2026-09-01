"""The venue this showcase fills against, as a registrable component.

An `AcademicExchange` is frictionless by construction: no cost, no partial fill, full
discretionary quantity. That is deliberate here — the claim under test is that a non-selected
execution row cannot change an outcome, and a venue with its own frictions would put a second
explanation between the two runs.
"""

from __future__ import annotations

from decimal import Decimal

from vqapr.public import AcademicExchange, ListingAccess, TradeRule


class ShowcaseExchange(AcademicExchange):
    """One listing, fractional quantity, long-only access."""

    def __init__(self):
        super().__init__(
            {
                "A": TradeRule(
                    "A",
                    Decimal("0.1"),
                    Decimal("0.1"),
                    True,
                    ListingAccess.LONG_ONLY,
                )
            },
            "showcase-academic",
        )
