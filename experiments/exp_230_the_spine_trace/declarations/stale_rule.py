# ruff: noqa: E501 -- the declaration as it was traced
"""A Compliance rule written against the 0.10.0 contract: `observe(self, call, account)`.

0.11.0 (record 229) hands a rule one Call, with the account on it. This class constructs from its
registered config and still subclasses `Compliance`, so only the conformance check at registration can catch it.
"""

from decimal import Decimal

from vqapr.authoring import Compliance, ComplianceFinding


class StaleCap(Compliance):
    def __init__(self, compliance_id: str = "stale-cap") -> None:
        self._compliance_id = compliance_id

    @property
    def compliance_id(self) -> str:
        return self._compliance_id

    def inputs(self):
        return {}

    def observe(self, call, account) -> ComplianceFinding:
        worst = max((abs(q) for q in account.positions.values()), default=Decimal("0"))
        return ComplianceFinding(
            passed=worst <= Decimal("1"),
            measured=worst,
            bound=Decimal("1"),
            excess=max(worst - Decimal("1"), Decimal("0")),
            details={},
        )
