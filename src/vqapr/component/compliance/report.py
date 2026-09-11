"""What the framework makes of a rule's finding: the stamp, the tolerance and the verdict.

A `ComplianceFinding` is the author's measurement, compared strictly. The framework stamps it with
the id the rule was registered under (`StampedFinding`) and judges its excess against a tolerance,
once for every rule -- the rule's own, or `default_tolerance` -- so the record keeps the author's
`passed` beside the framework's `verdict` and a generous default hides nothing. A
`ComplianceReport` is every stamped finding from one observation of a committed account version.

The engine's OBSERVE stage builds these (`run/engine/stages/observe.py`), and the run context
carries them; both import this module, which is why the values are not kept beside the stage.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from vqapr.component.compliance.base import ComplianceFinding

__all__ = [
    "VERDICT_BREACHED",
    "VERDICT_HELD",
    "VERDICT_WITHIN_TOLERANCE",
    "ComplianceReport",
    "StampedFinding",
    "default_tolerance",
]


DEFAULT_RELATIVE_TOLERANCE = Decimal("0.01")


DEFAULT_ABSOLUTE_TOLERANCE = Decimal("0.001")
"""The framework's default tolerance: ``max(bound * 1%, 10bp of NAV)``.

Owner ruling, 2026-09-05 (`docs/issues/archive/086`). A book executes in whole lots and is marked
after its fills, so the realised weight lands a little off the target the optimiser put on the grid;
a strict comparison then files that residue as a violation, in the same counter as a real one. The
run that filed the issue measured the two populations: the worst residue was 1bp, the real breach
489bp -- 489x apart -- so a generous line separates them with room on both sides and needs no
precision. Expressed as a share of NAV it needs no currency either; vqapr has none. An author who
wants it tighter or looser overrides it on the rule (`Compliance.tolerance`).
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
class StampedFinding:
    """One author's measurement under the id the framework registered it as, and the framework's
    verdict on it."""

    rule_id: str
    finding: ComplianceFinding
    tolerance: Decimal | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.rule_id, str) or not self.rule_id:
            raise ValueError("rule_id must be a non-empty string")
        if not isinstance(self.finding, ComplianceFinding):
            raise TypeError("finding must be a ComplianceFinding")
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
        """The names this finding blames, or empty when it names none."""
        return self.finding.offenders

    # The snapshot a breach must leave behind -- which rule, the bound, the value measured
    # against it -- read through here so a reader of `report.findings` holds one object per rule
    # and does not have to know that the author's half sits one level down.
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
class ComplianceReport:
    """All findings from one closed observation of a committed account version."""

    account_version: int
    findings: tuple[StampedFinding, ...]

    def __post_init__(self) -> None:
        if isinstance(self.account_version, bool) or not isinstance(self.account_version, int):
            raise TypeError("account_version must be an integer")
        if self.account_version < 0:
            raise ValueError("account_version must be non-negative")
        if not isinstance(self.findings, tuple) or not all(
            isinstance(finding, StampedFinding) for finding in self.findings
        ):
            raise TypeError("findings must be a tuple of StampedFinding")
        ids = tuple(finding.rule_id for finding in self.findings)
        if len(ids) != len(set(ids)):
            raise ValueError("findings must contain each rule_id once")

    @property
    def passed(self) -> bool:
        return all(finding.passed for finding in self.findings)
