"""Closed, non-mutating evaluation of one loaded Constraint instance set."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from vqapr.authoring import Constraint, ConstraintBounds, ConstraintFinding, EconomicAccountView
from vqapr.authoring.context import ConstraintContext
from vqapr.data.requirements import DataRequirement
from vqapr.data.windows import ModelWindow
from vqapr.domain.account_state import AccountSnapshot
from vqapr.domain.shapes import CrossSection
from vqapr.domain.values import MarkBatch

# ------------------------------------------------------------------------------------------
# findings.py, folded in (one-shape Step 7, record 162)
#
# Immutable evidence emitted by Constraint evaluation, and the framework's stamp on it.
#
# **A finding says what was measured. Which rule measured it is said once, not once per finding.**
# This module used to define a `ConstraintFinding` carrying `constraint_id`, which every author had
# to set on every finding and which `evaluation.py` then compared against the id it was already
# holding while it made the call. That is the shape record `125` removed from the Strategy callback,
# one contract over: an author who names it wrong is refused, and an author who names it *plausibly*
# wrong is accepted under another rule's identity. `Constraint.constraint_id` still declares the id
# once, and the loader still checks it against the registration.
#
# So the payload is `vqapr.authoring.ConstraintFinding` -- `passed`, `measured`, `bound`, `excess`,
# `details` -- and the stamping structure was already here, in `evaluation.py`'s
# `IntendedConstraintFinding` and `ActualConstraintFinding`. `StampedConstraintFinding` below is
# their shared shape, and it is what a reader gets: the id from the framework, the measurement from
# the author, and no way for the two to disagree.
# ------------------------------------------------------------------------------------------

__all__ = (
    "VERDICT_BREACHED",
    "VERDICT_HELD",
    "VERDICT_WITHIN_TOLERANCE",
    "ConstraintFinding",
    "ConstraintReport",
    "StampedConstraintFinding",
    "default_tolerance",
)

DEFAULT_RELATIVE_TOLERANCE = Decimal("0.01")
DEFAULT_ABSOLUTE_TOLERANCE = Decimal("0.001")
"""The framework's default tolerance: ``max(bound * 1%, 10bp of NAV)``.

Owner ruling, 2026-09-05 (`docs/issues/086`). A book executes in whole lots and is marked after
its fills, so the realised weight lands a little off the target the optimiser put on the grid; a
strict comparison then files that residue as a violation, in the same counter as a real one. The
run that filed the issue measured the two populations: the worst residue was 1bp, the real breach
489bp -- 489x apart -- so a generous line separates them with room on both sides and needs no
precision. Expressed as a share of NAV it needs no currency either; vqapr has none. An author who
wants it tighter or looser overrides it on the Constraint (`Constraint.tolerance`).
"""

VERDICT_HELD = "held"
VERDICT_WITHIN_TOLERANCE = "within_tolerance"
VERDICT_BREACHED = "breached"
"""What the framework says about one finding. `held` is the author's own verdict (`passed`);
`within_tolerance` is a finding the author failed that lands inside the tolerance; `breached` is
beyond it. The three are different facts, and `held`/`checked` used to have room for one of them."""


def default_tolerance(bound: Decimal) -> Decimal:
    """``max(|bound| * 1%, 10bp)``: one percent of the bound, floored so a small bound on a
    small book does not turn one lot into a violation."""
    return max(abs(bound) * DEFAULT_RELATIVE_TOLERANCE, DEFAULT_ABSOLUTE_TOLERANCE)


@dataclass(frozen=True, slots=True)
class StampedConstraintFinding:
    """One author's measurement under the id the framework registered it as, and the framework's
    verdict on it.

    **The tolerance is judged here, once, for every constraint** (`docs/issues/086`). Not on the
    author's `ConstraintFinding` -- every author would re-derive the same distinction, and the
    shipped `single_name_cap` and the scaffold both compare strictly -- and not on
    `ConstraintBounds`, the one place it could leak into `project` and widen the feasible set the
    optimiser works in. The author keeps comparing strictly and keeps reporting `measured`,
    `bound` and `excess`; the framework says whether the excess is inside the line.
    """

    constraint_id: str
    finding: ConstraintFinding
    tolerance: Decimal | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.constraint_id, str) or not self.constraint_id:
            raise ValueError("constraint_id must be a non-empty string")
        if not isinstance(self.finding, ConstraintFinding):
            raise TypeError("finding must be a ConstraintFinding")
        tolerance = self.tolerance
        if tolerance is None:
            tolerance = default_tolerance(self.finding.bound)
        if not isinstance(tolerance, Decimal) or not tolerance.is_finite() or tolerance < 0:
            raise ValueError("tolerance must be a finite non-negative Decimal")
        object.__setattr__(self, "tolerance", tolerance)

    @property
    def passed(self) -> bool:
        return self.finding.passed

    @property
    def verdict(self) -> str:
        """`held`, `within_tolerance` or `breached` -- see `VERDICT_*`."""
        if self.finding.passed:
            return VERDICT_HELD
        tolerance = self.tolerance
        if tolerance is None:
            raise RuntimeError("tolerance is resolved to a Decimal when the finding is stamped")
        if self.finding.excess <= tolerance:
            return VERDICT_WITHIN_TOLERANCE
        return VERDICT_BREACHED

    @property
    def breached(self) -> bool:
        """Beyond the tolerance: the only verdict that makes a contract `ok: false`."""
        return self.verdict == VERDICT_BREACHED

    @property
    def offenders(self) -> tuple[str, ...]:
        """The names this finding blames, or empty when it names none.

        Read here rather than at each call site because a refusal that cannot say WHICH name
        breached WHICH bound sends its reader back to re-run the strategy without the constraint
        (`docs/implementations/086`, and the message `flow/strategy/valuation.py` builds from it).
        """
        return self.finding.offenders

    # The snapshot a breach must leave behind -- which constraint, the bound, the value measured
    # against it -- read through here for the same reason `passed` and `offenders` are: a reader
    # of `report.findings` holds one object per constraint and should not have to know that the
    # author's half sits one level down. Same values, one access path.
    @property
    def measured(self) -> Decimal:
        return self.finding.measured

    @property
    def bound(self) -> Decimal:
        return self.finding.bound

    @property
    def excess(self) -> Decimal:
        return self.finding.excess

    @property
    def details(self) -> Mapping[str, object]:
        return self.finding.details


@dataclass(frozen=True, slots=True)
class ConstraintReport:
    """All findings from one closed evaluation of a committed account version."""

    account_version: int
    findings: tuple[StampedConstraintFinding, ...]

    def __post_init__(self) -> None:
        if isinstance(self.account_version, bool) or not isinstance(self.account_version, int):
            raise TypeError("account_version must be an integer")
        if self.account_version < 0:
            raise ValueError("account_version must be non-negative")
        if not isinstance(self.findings, tuple) or not all(
            isinstance(finding, StampedConstraintFinding) for finding in self.findings
        ):
            raise TypeError("findings must be a tuple of StampedConstraintFinding")
        ids = tuple(finding.constraint_id for finding in self.findings)
        if len(ids) != len(set(ids)):
            raise ValueError("findings must contain each constraint_id once")

    @property
    def passed(self) -> bool:
        return all(finding.passed for finding in self.findings)


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
    first, *rest = (item.bounds for item in projected)
    if not rest:
        return first
    # The intersection of boxes: lower bounds take the max, upper bounds the min, name by name.
    # `elementwise` refuses a projection that covers different names (record `183`).
    try:
        lower = _section(first.lower_weights).elementwise(
            max, *(item.lower_weights for item in rest)
        )
        upper = _section(first.upper_weights).elementwise(
            min, *(item.upper_weights for item in rest)
        )
    except ValueError as error:
        raise ValueError("projected bounds must cover the same instruments") from error
    return ConstraintBounds(lower_weights=lower, upper_weights=upper)


def _section(weights: Mapping[str, Decimal]) -> CrossSection[Decimal]:
    """The cross-section a bounds field holds; `ConstraintBounds` stores one, its annotation
    is the `Mapping` an author may pass in."""
    return weights if isinstance(weights, CrossSection) else CrossSection(weights)


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
    # declared no rules" into a monitoring failure. A missing window with rules loaded was
    # refused above, so past this line every rule has one.
    if not loaded or window is None:
        return ConstraintReport(account.version, ())
    view = build_account_view(account, marks, window.evaluation_time)
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
            tolerance=_tolerance_override(constraint),
        )
        for constraint in loaded
    )
    return ConstraintReport(account.version, findings)


def _tolerance_override(constraint: Constraint) -> Decimal | None:
    """The author's tolerance, if they declared one; `None` leaves the framework default.

    Read here so the verdict is judged in one place for every constraint and the author's only
    lever is the number (`docs/issues/086`). Refused rather than defaulted when it is not a
    finite non-negative Decimal: a tolerance that silently became "the default" would hide the
    typo the author is about to run 82 rebalances under.
    """
    declared = constraint.tolerance
    if declared is None:
        return None
    if not isinstance(declared, Decimal) or not declared.is_finite() or declared < 0:
        raise TypeError(
            f"{constraint.constraint_id}: tolerance must be a finite non-negative Decimal or "
            f"None; got {declared!r}"
        )
    return declared


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
