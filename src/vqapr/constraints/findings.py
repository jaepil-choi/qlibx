"""Immutable evidence emitted by Constraint evaluation, and the framework's stamp on it.

**A finding says what was measured. Which rule measured it is said once, not once per finding.**
This module used to define a `ConstraintFinding` carrying `constraint_id`, which every author had
to set on every finding and which `evaluation.py` then compared against the id it was already
holding while it made the call. That is the shape record `125` removed from the Strategy callback,
one contract over: an author who names it wrong is refused, and an author who names it *plausibly*
wrong is accepted under another rule's identity. `Constraint.constraint_id` still declares the id
once, and the loader still checks it against the registration.

So the payload is `vqapr.authoring.ConstraintFinding` -- `passed`, `measured`, `bound`, `excess`,
`details` -- and the stamping structure was already here, in `evaluation.py`'s
`IntendedConstraintFinding` and `ActualConstraintFinding`. `StampedConstraintFinding` below is
their shared shape, and it is what a reader gets: the id from the framework, the measurement from
the author, and no way for the two to disagree.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from vqapr.authoring import ConstraintFinding

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
        if self.finding.excess <= self.tolerance:
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
        (`docs/implementations/086`, and the message `flow/valuation.py` builds from it).
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
