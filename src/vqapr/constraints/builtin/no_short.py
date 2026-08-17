"""A shipped constraint forbidding negative weights.

This is the constraint that makes long-only an **emergent property of the constraint set** rather
than a precondition on an input. A signed alpha can enter the enhanced-index construction unchanged;
it is this projection, intersected with the others, that removes the short leg.

The upper bound is not padding. ``constraints/evaluation.py`` rejects any projection that does not
cover every window instrument with both bounds, so a lower-only constraint is inexpressible; the
neutral upper bound keeps ``merged_constraint_bounds`` intersecting correctly.
"""

from __future__ import annotations

from decimal import Decimal

from vqapr.account.snapshot import AccountSnapshot
from vqapr.constraints.constraint import Constraint, ConstraintBounds
from vqapr.constraints.findings import ConstraintFinding
from vqapr.data.requirements import DataRequirement
from vqapr.data.windows import ModelWindow
from vqapr.portfolio.intents import EconomicPortfolioIntent
from vqapr.valuation.marks import MarkBatch

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

    def requirements(self) -> tuple[DataRequirement, ...]:
        """No observation is needed: the rule is a property of the weight itself."""
        return ()

    def project(self, window: ModelWindow, instruments: tuple[str, ...]) -> ConstraintBounds:
        return ConstraintBounds(
            {instrument: FLOOR for instrument in instruments},
            {instrument: CEILING for instrument in instruments},
        )

    def validate_intended(
        self, intent: EconomicPortfolioIntent, bounds: ConstraintBounds
    ) -> ConstraintFinding:
        weights = [target.weight for target in intent.targets if target.weight is not None]
        worst = min(weights, default=FLOOR)
        offenders = tuple(
            sorted(
                target.instrument_id
                for target in intent.targets
                if target.weight is not None and target.weight < FLOOR
            )
        )
        return ConstraintFinding(
            self._constraint_id,
            not offenders,
            worst,
            FLOOR,
            max(FLOOR - worst, FLOOR),
            {"stage": "intended", "offenders": offenders},
        )

    def evaluate(
        self,
        window: ModelWindow,
        account: AccountSnapshot,
        marks: MarkBatch,
        bounds: ConstraintBounds,
    ) -> ConstraintFinding:
        offenders = tuple(
            sorted(
                instrument for instrument, quantity in account.positions.items() if quantity < FLOOR
            )
        )
        worst = min(account.positions.values(), default=FLOOR)
        return ConstraintFinding(
            self._constraint_id,
            not offenders,
            worst,
            FLOOR,
            max(FLOOR - worst, FLOOR),
            {
                "stage": "monitoring",
                "account_version": account.version,
                "offenders": offenders,
            },
        )
