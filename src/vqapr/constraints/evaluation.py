"""Closed, non-mutating evaluation of one loaded Constraint instance set."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from vqapr.account.snapshot import AccountSnapshot
from vqapr.authoring import EconomicAccountView
from vqapr.calls import ConstraintContext
from vqapr.constraints.constraint import Constraint, ConstraintBounds
from vqapr.constraints.findings import (
    ConstraintFinding,
    ConstraintReport,
    StampedConstraintFinding,
)
from vqapr.data.requirements import DataRequirement
from vqapr.data.windows import ModelWindow
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


class ActualConstraintFinding(StampedConstraintFinding):
    """Typed evidence emitted while monitoring a committed marked account."""


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


def _finding(finding: object) -> ConstraintFinding:
    """Check the shape and nothing else.

    The identity comparison this used to make is gone with the field it compared: the framework
    stamps the id it is already holding rather than asking the author for a copy of it and then
    checking the copy.
    """
    if not isinstance(finding, ConstraintFinding):
        raise TypeError("Constraint must return a ConstraintFinding")
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
        # A view per constraint, because a `DataRequirement` no longer says who is reading it and
        # this loop is the only place that knows. The accesses all land in `window`.
        bounds = constraint.project(
            ConstraintContext(
                window=window.for_consumer(constraint.constraint_id),
                instruments=instruments,
                reads=constraint.inputs(),
            )
        )
        if not isinstance(bounds, ConstraintBounds):
            raise TypeError("Constraint.project must return ConstraintBounds")
        if set(bounds.lower_weights) != set(instruments):
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
        return ConstraintBounds(lower_weights={}, upper_weights={})
    instruments = tuple(projected[0].bounds.lower_weights)
    if any(set(item.bounds.lower_weights) != set(instruments) for item in projected[1:]):
        raise ValueError("projected bounds must cover the same instruments")
    lower = {
        instrument: max(item.bounds.lower_weights[instrument] for item in projected)
        for instrument in instruments
    }
    upper = {
        instrument: min(item.bounds.upper_weights[instrument] for item in projected)
        for instrument in instruments
    }
    return ConstraintBounds(lower_weights=lower, upper_weights=upper)


def evaluate_constraints(
    constraints: tuple[Constraint, ...],
    window: ModelWindow | None,
    account: AccountSnapshot,
    marks: MarkBatch,
    projected: tuple[ProjectedConstraintFinding, ...],
) -> ConstraintReport:
    """Monitor one marked account against bounds projected in its PIT window."""
    loaded = _loaded(constraints)
    if window is None:
        if loaded:
            raise TypeError("window must be a ModelWindow when constraints are loaded")
    elif not isinstance(window, ModelWindow):
        raise TypeError("window must be a ModelWindow or None")
    if not isinstance(account, AccountSnapshot):
        raise TypeError("account must be an AccountSnapshot")
    if not isinstance(marks, MarkBatch):
        raise TypeError("marks must be a MarkBatch")
    if not isinstance(projected, tuple) or not all(
        isinstance(item, ProjectedConstraintFinding) for item in projected
    ):
        raise TypeError("projected must be a tuple of ProjectedConstraintFinding")
    projection_by_id = {item.constraint_id: item for item in projected}
    if len(projection_by_id) != len(projected) or tuple(projection_by_id) != tuple(
        constraint.constraint_id for constraint in loaded
    ):
        raise ValueError("projected findings must exactly match the loaded constraint instances")
    # Built only when something will read it. `window` is legitimately `None` for a run with no
    # constraints, and reaching through it for an instant nobody asked for turned "this run
    # declared no rules" into a monitoring failure.
    view = build_account_view(account, marks, window.evaluation_time) if loaded else None
    findings = tuple(
        ActualConstraintFinding(
            constraint.constraint_id,
            _finding(
                constraint.monitor(
                    ConstraintContext(
                        window=window.for_consumer(constraint.constraint_id),
                        instruments=window.instruments,
                        reads=constraint.inputs(),
                    ),
                    view,
                    projection_by_id[constraint.constraint_id].bounds,
                )
            ),
        )
        for constraint in loaded
    )
    return ConstraintReport(account.version, findings)


def build_account_view(
    account: AccountSnapshot, marks: MarkBatch, observed_at: datetime
) -> EconomicAccountView:
    """The marked account as an author sees it.

    Built here, once per monitoring occurrence, rather than by each Constraint out of an
    `AccountSnapshot` and a `MarkBatch`: `nav = marks.total_value + account.cash` and
    `weight = value / nav` are the two derivations every weight rule needs and neither is a
    judgement, so a rule that got either subtly different from its neighbour would report a
    breach its neighbour permitted. `docs/issues/014` is that defect measured on one constraint
    disagreeing with itself.

    `observed_at` is this monitoring occurrence's own cutoff, which is the instant these marks
    are the account's value at. `MarkBatch` does not carry one: a `Mark` is a quantity, a price
    and their product, and when it was taken is a property of the occurrence that took it.
    """
    nav = marks.total_value + account.cash
    return EconomicAccountView(
        cash=account.cash,
        positions=dict(account.positions),
        values={mark.instrument_id: mark.value for mark in marks.marks},
        nav=nav,
        nav_observed_at=observed_at,
    )


__all__ = [
    "ActualConstraintFinding",
    "ProjectedConstraintFinding",
    "StampedConstraintFinding",
    "build_account_view",
    "constraint_requirements",
    "evaluate_constraints",
    "merged_constraint_bounds",
    "project_constraints",
]
