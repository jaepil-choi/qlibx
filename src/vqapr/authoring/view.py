"""What a callback is handed beyond its own call: the committed account, and the bounds on it.

`EconomicAccountView` is the account as one callback may see it -- an immutable snapshot, never the
live book -- and `ConstraintBounds` is what every registered Constraint's projection agreed a
target weight may be. Both are values the engine constructs and the author only reads, which is why
they sit below `call.py`: a `StrategyCall` carries them.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Self

from pydantic import BaseModel, ValidationInfo, field_validator, model_validator

from vqapr.authoring._validation import (
    _VALUE_CONFIG,
    _copy_weights,
    _finite_decimal,
    _identifier,
    _tz_aware,
)
from vqapr.domain.shapes import CrossSection


@dataclass(frozen=True, slots=True, kw_only=True)
class EconomicAccountView:
    """A bounded, immutable snapshot of the committed Account for one callback.

    **`values` was missing, and its absence made a whole rule shape inexpressible.** This view
    carried `positions` -- quantities -- plus one aggregate `nav`, and a weight is
    `value / nav`. Quantities cannot become weights without prices, so no weight-based rule
    could be written against this type at all, which is what both shipped Constraints are. The
    gap went unnoticed because monitoring ran on the engine's `MarkBatch` instead, on the other
    side of the surface split this contract exists to remove.

    So `values` is the marked value per instrument. Quantities stay, because a rule about lot
    sizes or a short position asks about quantity and would otherwise have to divide back out.

    **`values` is `None` where the framework has no marks to offer, and that is not zero.** A
    Strategy callback fires before the occurrence it decides for is executed or valued, so what
    it sees is the previous valuation's marks -- committed, and therefore point-in-time -- and
    before the first valuation there are none; a monitoring Constraint fires against a marked
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
        Constraint that would otherwise divide by a NAV it had to reassemble. Refuses rather than
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


class ConstraintBounds(BaseModel):
    """Frozen per-instrument target-weight bounds merged from every projected Constraint.

    Declared as any `Mapping[str, Decimal]`; held as the read-only `CrossSection` it validates
    into, so `bounds.lower_weights["A"]` reads the way it always did.
    """

    model_config = _VALUE_CONFIG

    lower_weights: CrossSection[Decimal]
    upper_weights: CrossSection[Decimal]

    def __init__(
        self, *, lower_weights: Mapping[str, Decimal], upper_weights: Mapping[str, Decimal]
    ) -> None:
        # The door's own signature: what an author passes is any mapping, what the field holds
        # is the cross-section it validated into. Written out so a type checker sees the former.
        super().__init__(lower_weights=lower_weights, upper_weights=upper_weights)

    @field_validator("lower_weights", "upper_weights", mode="before")
    @classmethod
    def _weights(cls, value: object, info: ValidationInfo) -> CrossSection[Decimal]:
        return _copy_weights(value, name=str(info.field_name))

    @model_validator(mode="after")
    def _same_names_ordered(self) -> Self:
        lower, upper = self.lower_weights, self.upper_weights
        if set(lower) != set(upper):
            raise ValueError("lower_weights and upper_weights must cover the same instruments")
        for instrument_id in lower:
            if lower[instrument_id] > upper[instrument_id]:
                raise ValueError("lower_weights must not exceed upper_weights")
        return self

    def lower_weight(self, instrument_id: str) -> Decimal:
        checked = _identifier(instrument_id, name="instrument_id")
        return self.lower_weights[checked]

    def upper_weight(self, instrument_id: str) -> Decimal:
        checked = _identifier(instrument_id, name="instrument_id")
        return self.upper_weights[checked]

    def detached(self) -> ConstraintBounds:
        """A fresh value with no caller-owned mapping aliases.

        Validation already copies into read-only views, so this is defensive rather than
        load-bearing -- and it is kept because `StrategyModelContext` calls it on a value it did
        not construct, where "already copied" is an assumption about someone else's code.
        """
        return ConstraintBounds(
            lower_weights=self.lower_weights, upper_weights=self.upper_weights
        )
