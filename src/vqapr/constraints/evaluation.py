"""Closed, non-mutating evaluation of one loaded Constraint instance set."""

from __future__ import annotations

from dataclasses import dataclass

from vqapr.account.snapshot import AccountSnapshot
from vqapr.constraints.constraint import Constraint, ConstraintBounds
from vqapr.constraints.findings import ConstraintFinding, ConstraintReport
from vqapr.data.requirements import DataRequirement
from vqapr.data.windows import ModelWindow
from vqapr.portfolio.intents import EconomicPortfolioIntent, validate_economic_intent
from vqapr.valuation.marks import MarkBatch


@dataclass(frozen=True, slots=True)
class ProjectedConstraintFinding:
    """Typed evidence of one constraint's deterministic projected bounds."""

    constraint_id: str
    bounds: ConstraintBounds

    def __post_init__(self) -> None:
        _constraint_id(self.constraint_id)
        if not isinstance(self.bounds, ConstraintBounds):
            raise TypeError("bounds must be a ConstraintBounds")
        object.__setattr__(self, "bounds", self.bounds.detached())


@dataclass(frozen=True, slots=True)
class IntendedConstraintFinding:
    """Typed evidence emitted while validating a proposed economic intent."""

    constraint_id: str
    finding: ConstraintFinding

    def __post_init__(self) -> None:
        _constraint_id(self.constraint_id)
        if not isinstance(self.finding, ConstraintFinding):
            raise TypeError("finding must be a ConstraintFinding")
        if self.finding.constraint_id != self.constraint_id:
            raise ValueError("intended finding identity must match its constraint")


@dataclass(frozen=True, slots=True)
class ActualConstraintFinding:
    """Typed evidence emitted while monitoring a committed marked account."""

    constraint_id: str
    finding: ConstraintFinding

    def __post_init__(self) -> None:
        _constraint_id(self.constraint_id)
        if not isinstance(self.finding, ConstraintFinding):
            raise TypeError("finding must be a ConstraintFinding")
        if self.finding.constraint_id != self.constraint_id:
            raise ValueError("actual finding identity must match its constraint")


def _constraint_id(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise TypeError("Constraint.constraint_id must be a non-empty string")
    return value


def _loaded(constraints: object) -> tuple[Constraint, ...]:
    """Validate the one immutable loaded instance tuple shared by all phases."""
    if not isinstance(constraints, tuple):
        raise TypeError("constraints must be the loaded tuple of Constraint instances")
    if not all(isinstance(constraint, Constraint) for constraint in constraints):
        raise TypeError("constraints must contain Constraint implementations")
    identities = tuple(_constraint_id(constraint.constraint_id) for constraint in constraints)
    if len(identities) != len(set(identities)):
        raise ValueError("loaded constraints must have unique stable identities")
    return constraints


def _finding(constraint: Constraint, finding: object) -> ConstraintFinding:
    if not isinstance(finding, ConstraintFinding):
        raise TypeError("Constraint must return a ConstraintFinding")
    if finding.constraint_id != constraint.constraint_id:
        raise ValueError("Constraint finding identity must match its implementation")
    return finding


def constraint_requirements(constraints: tuple[Constraint, ...]) -> tuple[DataRequirement, ...]:
    """Return the exact declared PIT requirements of the loaded constraint tuple."""
    loaded = _loaded(constraints)
    requirements: list[DataRequirement] = []
    for constraint in loaded:
        declared = constraint.requirements()
        if not isinstance(declared, tuple) or not all(
            isinstance(requirement, DataRequirement) for requirement in declared
        ):
            raise TypeError("Constraint.requirements must return a tuple of DataRequirement")
        requirements.extend(declared)
    return tuple(requirements)


def project_constraints(
    constraints: tuple[Constraint, ...], window: ModelWindow
) -> tuple[ProjectedConstraintFinding, ...]:
    """Project all loaded constraints for exactly the current PIT window."""
    loaded = _loaded(constraints)
    if not isinstance(window, ModelWindow):
        raise TypeError("window must be a ModelWindow")
    instruments = window.instruments
    projected: list[ProjectedConstraintFinding] = []
    for constraint in loaded:
        bounds = constraint.project(window, instruments)
        if not isinstance(bounds, ConstraintBounds):
            raise TypeError("Constraint.project must return ConstraintBounds")
        if set(bounds.lower) != set(instruments):
            raise ValueError("Constraint.project bounds must cover every window instrument")
        projected.append(ProjectedConstraintFinding(constraint.constraint_id, bounds))
    return tuple(projected)


def merged_constraint_bounds(
    projected: tuple[ProjectedConstraintFinding, ...],
) -> ConstraintBounds:
    """Intersect immutable projections before exposing them to a Strategy."""
    if not isinstance(projected, tuple) or not all(
        isinstance(item, ProjectedConstraintFinding) for item in projected
    ):
        raise TypeError("projected must be a tuple of ProjectedConstraintFinding")
    if not projected:
        return ConstraintBounds({}, {})
    instruments = tuple(projected[0].bounds.lower)
    if any(set(item.bounds.lower) != set(instruments) for item in projected[1:]):
        raise ValueError("projected bounds must cover the same instruments")
    lower = {
        instrument: max(item.bounds.lower[instrument] for item in projected)
        for instrument in instruments
    }
    upper = {
        instrument: min(item.bounds.upper[instrument] for item in projected)
        for instrument in instruments
    }
    return ConstraintBounds(lower, upper)


def validate_intended_constraints(
    constraints: tuple[Constraint, ...],
    intent: EconomicPortfolioIntent,
    projected: tuple[ProjectedConstraintFinding, ...],
) -> tuple[IntendedConstraintFinding, ...]:
    """Validate an intent using projections from the same loaded instances."""
    loaded = _loaded(constraints)
    validated_intent = validate_economic_intent(intent)
    if not isinstance(projected, tuple) or not all(
        isinstance(item, ProjectedConstraintFinding) for item in projected
    ):
        raise TypeError("projected must be a tuple of ProjectedConstraintFinding")
    projection_by_id = {item.constraint_id: item for item in projected}
    if len(projection_by_id) != len(projected) or tuple(projection_by_id) != tuple(
        constraint.constraint_id for constraint in loaded
    ):
        raise ValueError("projected findings must exactly match the loaded constraint instances")
    return tuple(
        IntendedConstraintFinding(
            constraint.constraint_id,
            _finding(
                constraint,
                constraint.validate_intended(
                    validated_intent, projection_by_id[constraint.constraint_id].bounds
                ),
            ),
        )
        for constraint in loaded
    )


def evaluate_constraints(
    constraints: tuple[Constraint, ...], account: AccountSnapshot, marks: MarkBatch
) -> ConstraintReport:
    """Monitor every loaded Constraint against the same committed marked snapshot."""
    loaded = _loaded(constraints)
    if not isinstance(account, AccountSnapshot):
        raise TypeError("account must be an AccountSnapshot")
    if not isinstance(marks, MarkBatch):
        raise TypeError("marks must be a MarkBatch")
    findings = tuple(
        ActualConstraintFinding(
            constraint.constraint_id, _finding(constraint, constraint.evaluate(account, marks))
        )
        for constraint in loaded
    )
    return ConstraintReport(account.version, tuple(item.finding for item in findings))


__all__ = [
    "ActualConstraintFinding",
    "IntendedConstraintFinding",
    "ProjectedConstraintFinding",
    "constraint_requirements",
    "evaluate_constraints",
    "merged_constraint_bounds",
    "project_constraints",
    "validate_intended_constraints",
]
