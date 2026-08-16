"""The project extension contract for economic Constraints."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from vqapr.account.snapshot import AccountSnapshot
from vqapr.constraints.findings import ConstraintFinding
from vqapr.valuation.marks import MarkBatch


@runtime_checkable
class Constraint(Protocol):
    """Evaluate one immutable, fully marked committed account snapshot.

    Constraint implementations own the economic predicate.  They must not mutate
    either input and must return exactly one finding bearing ``constraint_id``.
    """

    constraint_id: str

    def evaluate(self, account: AccountSnapshot, marks: MarkBatch) -> ConstraintFinding:
        """Return this Constraint's pass or violation finding."""
