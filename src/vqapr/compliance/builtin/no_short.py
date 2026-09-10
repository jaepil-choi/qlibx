"""A shipped compliance rule: the committed book holds no negative quantity.

The observing half of `vqapr.portfolio.bounds.no_short`. The kit function is what a strategy
builds inside; this rule is what watches the book the venue actually left, on the market clock,
and it does not know or care what box the strategy used (design §7.2: a watcher that inherits
the target of the thing it watches is grading itself).
"""

from __future__ import annotations

from decimal import Decimal

from vqapr.authoring import Compliance, ComplianceCall, ComplianceFinding

FLOOR = Decimal("0")


class NoShort(Compliance):
    """Report any negative holding in the marked account."""

    def __init__(self, compliance_id: str = "no-short") -> None:
        if not isinstance(compliance_id, str) or not compliance_id:
            raise ValueError("compliance_id must be a non-empty string")
        self._compliance_id = compliance_id

    @property
    def compliance_id(self) -> str:
        return self._compliance_id

    def observe(self, call: ComplianceCall) -> ComplianceFinding:
        """Measured on quantity, deliberately.

        A short is a negative *holding*, and a name held short has a negative quantity whatever
        its price does. Reading `call.account.weight(...)` here would make the answer depend on a
        NAV the rule does not care about, and report a breach differently in a drawdown.
        """
        positions = call.account.positions
        offenders = tuple(
            sorted(instrument for instrument, quantity in positions.items() if quantity < FLOOR)
        )
        worst = min(positions.values(), default=FLOOR)
        return ComplianceFinding(
            passed=not offenders,
            measured=worst,
            bound=FLOOR,
            excess=max(FLOOR - worst, FLOOR),
            details={},
            offenders=offenders,
        )
