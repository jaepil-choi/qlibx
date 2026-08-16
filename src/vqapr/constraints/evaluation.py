"""Closed, non-mutating evaluation of loaded Constraint implementations."""

from __future__ import annotations

from collections.abc import Sequence

from vqapr.account.snapshot import AccountSnapshot
from vqapr.constraints.constraint import Constraint
from vqapr.constraints.findings import ConstraintFinding, ConstraintReport
from vqapr.valuation.marks import MarkBatch


def evaluate_constraints(
    constraints: Sequence[Constraint], account: AccountSnapshot, marks: MarkBatch
) -> ConstraintReport:
    """Evaluate every loaded Constraint against the same committed marked snapshot."""
    if not isinstance(account, AccountSnapshot):
        raise TypeError("account must be an AccountSnapshot")
    if not isinstance(marks, MarkBatch):
        raise TypeError("marks must be a MarkBatch")
    loaded = tuple(constraints)
    if not all(isinstance(constraint, Constraint) for constraint in loaded):
        raise TypeError("constraints must contain Constraint implementations")

    findings: list[ConstraintFinding] = []
    for constraint in loaded:
        constraint_id = constraint.constraint_id
        if not isinstance(constraint_id, str) or not constraint_id:
            raise TypeError("Constraint.constraint_id must be a non-empty string")
        finding = constraint.evaluate(account, marks)
        if not isinstance(finding, ConstraintFinding):
            raise TypeError("Constraint.evaluate must return a ConstraintFinding")
        if finding.constraint_id != constraint_id:
            raise ValueError("Constraint finding identity must match its implementation")
        findings.append(finding)
    return ConstraintReport(account.version, tuple(findings))


__all__ = ["evaluate_constraints"]
