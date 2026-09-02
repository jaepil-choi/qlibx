"""A shipped constraint forbidding negative weights.

This is the constraint that makes long-only an **emergent property of the constraint set** rather
than a precondition on an input. A signed alpha can enter the enhanced-index construction unchanged;
it is this projection, intersected with the others, that removes the short leg.

The upper bound is not padding. ``constraints/evaluation.py`` rejects any projection that does not
cover every window instrument with both bounds, so a lower-only constraint is inexpressible; the
neutral upper bound keeps ``merged_constraint_bounds`` intersecting correctly.

**Two members, written against the one authored contract**: it bounds construction, and it
observes the committed account. It used to have a third that judged the decision the moment it was
made, and to take four framework types no other kind of extension sees.
"""

from __future__ import annotations

from decimal import Decimal

from vqapr.authoring import (
    Constraint,
    ConstraintBounds,
    ConstraintCall,
    ConstraintFinding,
    EconomicAccountView,
)

FLOOR = Decimal("0")
CEILING = Decimal("1")


class NoShort(Constraint):
    """Refuse any negative weight, in intent and in the marked account alike."""

    def __init__(self, constraint_id: str = "no-short") -> None:
        if not isinstance(constraint_id, str) or not constraint_id:
            raise ValueError("constraint_id must be a non-empty string")
        self._constraint_id = constraint_id

    @property
    def constraint_id(self) -> str:
        return self._constraint_id

    def project(self, call: ConstraintCall) -> ConstraintBounds:
        """No observation is needed: the rule is a property of the weight itself."""
        return ConstraintBounds(
            lower_weights={instrument: FLOOR for instrument in call.instruments},
            upper_weights={instrument: CEILING for instrument in call.instruments},
        )

    def monitor(
        self,
        call: ConstraintCall,
        account: EconomicAccountView,
        bounds: ConstraintBounds,
    ) -> ConstraintFinding:
        """Measured on quantity, deliberately, and this is the one member that may differ.

        A short is a negative *holding*, and a name held short has a negative quantity whatever
        its price does. Reading `account.weight(...)` here would make the answer depend on a NAV
        the rule does not care about, and would report a breach differently in a drawdown.
        """
        positions = account.positions
        offenders = tuple(
            sorted(instrument for instrument, quantity in positions.items() if quantity < FLOOR)
        )
        worst = min(positions.values(), default=FLOOR)
        return ConstraintFinding(
            passed=not offenders,
            measured=worst,
            bound=FLOOR,
            excess=max(FLOOR - worst, FLOOR),
            details={},
            offenders=offenders,
        )
