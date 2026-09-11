"""What a Compliance rule is handed, built for a test.

Two builders, because the two cases are genuinely different and collapsing them hides which one a
test is exercising:

- `reading_call` wraps a real `ModelWindow` and is what a rule with declared `inputs()` needs. It
  is the production `ComplianceContext`, not a stand-in.
- `weightless_call` is for a rule that reads nothing -- `NoShort` is the shipped example -- and
  deliberately has no window at all. A test that hands it to a rule which does read gets an
  `AssertionError` naming `read`, which is the honest failure: the test declared the rule reads
  nothing and the rule disagreed.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from vqapr.authoring import ComplianceCall, EconomicAccountView
from vqapr.authoring.context import ComplianceContext
from vqapr.data.window import ModelWindow


def reading_call(
    window: ModelWindow,
    instruments: tuple[str, ...],
    rule,
    *,
    account: EconomicAccountView | None = None,
) -> ComplianceCall:
    """The production context, aliased by whatever the rule declared, over `account`.

    Without one, an empty unmarked book: what a test of the rule's *reads* (`ceilings`) is
    handed, since it never looks at the account.
    """
    if account is None:
        account = EconomicAccountView(cash=Decimal(0), positions={}, nav=None, nav_observed_at=None)
    return ComplianceContext(
        window=window, account=account, instruments=tuple(instruments), reads=rule.inputs()
    )


@dataclass(frozen=True, slots=True)
class _Weightless(ComplianceCall):
    instruments: tuple[str, ...]
    account: EconomicAccountView

    @property
    def evaluation_time(self):
        raise AssertionError("a rule that declares no reads has no evaluation time to use")

    def read(self, alias: str, field: str):
        raise AssertionError(f"this call serves no reads; {alias!r} was asked for")

    def rows(self, alias: str):
        raise AssertionError(f"this call serves no reads; {alias!r} was asked for")


def weightless_call(
    instruments: tuple[str, ...], *, account: EconomicAccountView
) -> ComplianceCall:
    """A call for a rule that declared no `inputs()`. Reading through it is an error."""
    return _Weightless(tuple(instruments), account)
