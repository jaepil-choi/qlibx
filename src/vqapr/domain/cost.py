"""What one fill costs.

A venue charges per side, and the two sides are genuinely different numbers: KRX takes a
commission on both and a securities transaction tax only on sells. So a rate is declared as a pair
of :class:`SideCost` on the instrument's own :class:`~vqapr.domain.listing.TradeRule`, which is
the same shape the research declares:

```yaml
stock:  buy_bps: 3.0   sell_bps: 23.0
etf:    buy_bps: 3.0   sell_bps: 3.0
```

**There is no rule-matching engine here, deliberately.** Rates used to be a tuple of selectable
bands keyed by ``(kind, side, effective window)``, resolved at charge time and guarded against
matching zero or several. Every part of that existed to support effective-dated rates, and nothing
ever declared one -- both shipped KRX declarations were flat, and the dated path was in fact
*broken* until it was measured, because a venue with dated bands could not be planned at all.
Machinery whose only user is its own test is not a feature.

A side's rate is now reached by a dictionary lookup on ``instrument_id``, so zero matches and
several matches are not failure modes that can occur. If effective-dated rates are needed later,
they belong above this: a venue expanding a different set of ``TradeRule`` for a different period,
not a matcher underneath every charge.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


def _rate(value: Decimal, *, name: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must be a Decimal")
    if not value.is_finite() or value < 0:
        raise ValueError(f"{name} must be a finite non-negative rate")
    return value


@dataclass(frozen=True, slots=True)
class FillCost:
    """The charged components for one dealt fill, kept separate for reporting."""

    commission: Decimal = Decimal("0")
    tax: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        _rate(self.commission, name="commission")
        _rate(self.tax, name="tax")

    @property
    def total(self) -> Decimal:
        return self.commission + self.tax

    def __bool__(self) -> bool:
        return bool(self.total)


@dataclass(frozen=True, slots=True)
class SideCost:
    """What one side of a trade costs, as rates on traded notional.

    Commission and tax stay separate because they are separate facts: a venue may exempt a
    category from the tax while charging it the same commission, and reporting has to be able to
    say which of the two a book actually paid.
    """

    commission_rate: Decimal = Decimal("0")
    tax_rate: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        _rate(self.commission_rate, name="commission_rate")
        _rate(self.tax_rate, name="tax_rate")

    @property
    def free(self) -> bool:
        return not self.commission_rate and not self.tax_rate

    def charge(self, notional: Decimal) -> FillCost:
        """Charge this side against a non-negative traded notional."""
        if not isinstance(notional, Decimal):
            raise TypeError("notional must be a Decimal")
        if not notional.is_finite() or notional < 0:
            raise ValueError("notional must be a finite non-negative Decimal")
        return FillCost(
            commission=notional * self.commission_rate,
            tax=notional * self.tax_rate,
        )

    @property
    def declaration_identity(self) -> tuple[str, str]:
        return (str(self.commission_rate), str(self.tax_rate))


FREE = SideCost()
"""A side that costs nothing, which is what an academic venue declares."""
