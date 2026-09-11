"""What a callback is handed beyond its own call: the committed account.

`EconomicAccountView` is the account as one callback may see it -- an immutable snapshot, never the
live book. A value the engine constructs and the author only reads, which is why it sits below
`call.py`: a `StrategyCall` carries it, and a `Compliance` rule's `observe` receives it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from vqapr.authoring._validation import (
    _copy_weights,
    _finite_decimal,
    _identifier,
    _tz_aware,
)
from vqapr.data.panel import CrossSection


@dataclass(frozen=True, slots=True, kw_only=True)
class EconomicAccountView:
    """A bounded, immutable snapshot of the committed Account for one callback.

    **`values` was missing, and its absence made a whole rule shape inexpressible.** This view
    carried `positions` -- quantities -- plus one aggregate `nav`, and a weight is
    `value / nav`. Quantities cannot become weights without prices, so no weight-based rule
    could be written against this type at all, which is what both shipped rules are. The
    gap went unnoticed because monitoring ran on the engine's `MarkBatch` instead, on the other
    side of the surface split this contract exists to remove.

    So `values` is the marked value per instrument. Quantities stay, because a rule about lot
    sizes or a short position asks about quantity and would otherwise have to divide back out.

    **`values` is `None` where the framework has no marks to offer, and that is not zero.** A
    Strategy callback fires before the occurrence it decides for is executed or valued, so what
    it sees is the previous valuation's marks -- committed, and therefore point-in-time -- and
    before the first valuation there are none; a Compliance rule fires against a marked
    account and always has them. An empty mapping would make `weight()` return a confident zero
    for every name and every weight rule report `passed`, so absence refuses instead.
    """

    cash: Decimal
    positions: Mapping[str, Decimal]
    nav: Decimal | None
    nav_observed_at: datetime | None
    values: Mapping[str, Decimal] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "cash", _finite_decimal(self.cash, name="cash"))
        object.__setattr__(self, "positions", _copy_weights(self.positions, name="positions"))
        if self.values is not None:
            object.__setattr__(self, "values", _copy_weights(self.values, name="values"))
        if (self.nav is None) != (self.nav_observed_at is None):
            raise ValueError("nav and nav_observed_at must both be set or both be None")
        if self.nav is not None:
            object.__setattr__(self, "nav", _finite_decimal(self.nav, name="nav"))
            object.__setattr__(
                self,
                "nav_observed_at",
                _tz_aware(self.nav_observed_at, name="nav_observed_at"),
            )

    @classmethod
    def _trusted(
        cls,
        *,
        cash: Decimal,
        positions: Mapping[str, Decimal],
        nav: Decimal | None,
        nav_observed_at: datetime | None,
        values: Mapping[str, Decimal] | None = None,
    ) -> EconomicAccountView:
        """The view from values the framework already proved, without proving them again.

        The engine builds one of these at every market-clock instant, from an `AccountSnapshot`
        whose ids and quantities were validated when it was committed and a `MarkBatch` whose
        values were validated when it was marked. Re-checking 3,000 ids and 6,000 Decimals per
        instant was a third of the compliance stage (record `223`). Same shape, same read-only
        cross-sections, same sorted order; only the author's constructor validates.
        """
        view = object.__new__(cls)
        object.__setattr__(view, "cash", cash)
        object.__setattr__(
            view, "positions", CrossSection._trusted(dict(sorted(positions.items())))
        )
        object.__setattr__(
            view,
            "values",
            None if values is None else CrossSection._trusted(dict(sorted(values.items()))),
        )
        object.__setattr__(view, "nav", nav)
        object.__setattr__(view, "nav_observed_at", nav_observed_at)
        return view

    def quantity(self, instrument_id: str) -> Decimal:
        """The current quantity held, or `Decimal(0)` for a valid absent instrument."""
        checked = _identifier(instrument_id, name="instrument_id")
        return self.positions.get(checked, Decimal(0))

    def value(self, instrument_id: str) -> Decimal:
        """The marked value held, or `Decimal(0)` for a valid absent instrument."""
        checked = _identifier(instrument_id, name="instrument_id")
        if self.values is None:
            raise ValueError(
                "this view carries no marked values; it was built at an instant the framework "
                "had no marks to offer, and a zero here would be an answer rather than a gap"
            )
        return self.values.get(checked, Decimal(0))

    def weight(self, instrument_id: str) -> Decimal:
        """This instrument's share of NAV, signed.

        The one derivation every weight-based rule needs, written once here rather than in each
        rule that would otherwise divide by a NAV it had to reassemble. Refuses rather than
        returning zero when NAV is absent or zero: a weight against no NAV is not a small number,
        it is an undefined one, and a rule that silently measured zero would report `passed`.
        """
        if self.nav is None or not self.nav:
            raise ValueError(
                "weight is undefined without a non-zero nav; this view was built at an instant "
                "the account had not been marked"
            )
        return self.value(instrument_id) / self.nav

    def weights(self) -> CrossSection[Decimal]:
        """Every marked name's share of NAV, signed. The whole book as a weight vector."""
        if self.values is None:
            raise ValueError(
                "this view carries no marked values; it was built at an instant the framework "
                "had no marks to offer, and an empty book here would be an answer rather than a gap"
            )
        return CrossSection._trusted(
            {instrument_id: self.weight(instrument_id) for instrument_id in sorted(self.values)},
            self.nav_observed_at,
        )
