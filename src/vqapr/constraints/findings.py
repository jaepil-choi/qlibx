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

from dataclasses import dataclass

from vqapr.authoring import ConstraintFinding

__all__ = ("ConstraintFinding", "ConstraintReport", "StampedConstraintFinding")


@dataclass(frozen=True, slots=True)
class StampedConstraintFinding:
    """One author's measurement under the id the framework registered it as."""

    constraint_id: str
    finding: ConstraintFinding

    def __post_init__(self) -> None:
        if not isinstance(self.constraint_id, str) or not self.constraint_id:
            raise ValueError("constraint_id must be a non-empty string")
        if not isinstance(self.finding, ConstraintFinding):
            raise TypeError("finding must be a ConstraintFinding")

    @property
    def passed(self) -> bool:
        return self.finding.passed

    @property
    def offenders(self) -> tuple[str, ...]:
        """The names this finding blames, or empty when it names none.

        Read here rather than at each call site because a refusal that cannot say WHICH name
        breached WHICH bound sends its reader back to re-run the strategy without the constraint
        (`docs/issues/086`, and the message `flow/simulation.py` builds from it).
        """
        return self.finding.offenders


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
