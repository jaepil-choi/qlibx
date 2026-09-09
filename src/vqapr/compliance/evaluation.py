"""Closed, non-mutating evaluation of one loaded Compliance rule set.

**A finding says what was measured. Which rule measured it is said once, not once per finding.**
The rule declares its id once (`Compliance.compliance_id`), the loader checks it against the id it
was registered under, and the framework stamps that id onto the author's finding here -- so the
two cannot disagree (record `125` removed the same repetition from the Strategy callback).

**The tolerance is judged here, once, for every rule** (`docs/issues/archive/086`). The author
compares strictly and reports `measured`, `bound` and `excess`; the framework says whether the
excess is inside the line, and the record keeps the author's `passed` beside the framework's
`verdict` so a generous default hides nothing.

Record `209`: this is `constraints/evaluation.py` with the projection half removed. A rule no
longer projects a box for the strategy (that is the strategy's own kit call, design §7.1) and
no longer receives the box it projected: it observes the book with its own parameters, on the
market clock, and what it measures against is its own business. A watcher that inherits the
target of the thing it watches is grading itself.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from vqapr.authoring import Compliance, ComplianceFinding, EconomicAccountView
from vqapr.authoring.context import ComplianceContext
from vqapr.data.requirements import DataRequirement
from vqapr.data.windows import ModelWindow
from vqapr.domain.account_state import AccountSnapshot
from vqapr.domain.values import MarkBatch

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


def _rule_id(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise TypeError("Compliance.compliance_id must be a non-empty string")
    return value


def _loaded(rules: object) -> tuple[Compliance, ...]:
    """Validate the one immutable loaded instance tuple."""
    if not isinstance(rules, tuple):
        raise TypeError("rules must be the loaded tuple of Compliance instances")
    if not all(isinstance(rule, Compliance) for rule in rules):
        raise TypeError("rules must contain Compliance implementations")
    identities = tuple(_rule_id(rule.compliance_id) for rule in rules)
    if len(identities) != len(set(identities)):
        raise ValueError("loaded rules must have unique stable identities")
    return rules


def _finding(finding: object) -> ComplianceFinding:
    if not isinstance(finding, ComplianceFinding):
        raise TypeError("Compliance.observe must return a ComplianceFinding")
    return finding


def compliance_requirements(rules: tuple[Compliance, ...]) -> tuple[DataRequirement, ...]:
    """Return the exact declared PIT requirements of the loaded rule tuple."""
    loaded = _loaded(rules)
    requirements: list[DataRequirement] = []
    for rule in loaded:
        declared = rule.requirements()
        if not isinstance(declared, tuple) or not all(
            isinstance(requirement, DataRequirement) for requirement in declared
        ):
            raise TypeError("Compliance.requirements must return a tuple of DataRequirement")
        requirements.extend(declared)
    return tuple(requirements)


def evaluate_compliance(
    rules: tuple[Compliance, ...],
    window: ModelWindow | None,
    account: AccountSnapshot,
    marks: MarkBatch,
) -> ComplianceReport:
    """Observe one marked account with every loaded rule, as of the window's instant."""
    loaded = _loaded(rules)
    if window is None:
        if loaded:
            raise TypeError("window must be a ModelWindow when rules are loaded")
    elif not isinstance(window, ModelWindow):
        raise TypeError("window must be a ModelWindow or None")
    if not isinstance(account, AccountSnapshot):
        raise TypeError("account must be an AccountSnapshot")
    if not isinstance(marks, MarkBatch):
        raise TypeError("marks must be a MarkBatch")
    # `window` is legitimately `None` for a run with no rules, and reaching through it for an
    # instant nobody asked for turned "this run declared no rule" into a failure.
    if not loaded or window is None:
        return ComplianceReport(account.version, ())
    view = build_account_view(account, marks, window.evaluation_time)
    findings = tuple(
        StampedFinding(
            rule.compliance_id,
            _finding(
                rule.observe(
                    ComplianceContext(
                        window=window.for_consumer(rule.compliance_id),
                        instruments=window.instruments,
                        reads=rule.inputs(),
                    ),
                    view,
                )
            ),
            tolerance=_tolerance_override(rule),
        )
        for rule in loaded
    )
    return ComplianceReport(account.version, findings)


def _tolerance_override(rule: Compliance) -> Decimal | None:
    """The author's tolerance, if they declared one; `None` leaves the framework default.

    Refused rather than defaulted when it is not a finite non-negative Decimal: a tolerance that
    silently became "the default" would hide the typo the author is about to run 82 rebalances
    under.
    """
    declared = rule.tolerance
    if declared is None:
        return None
    if not isinstance(declared, Decimal) or not declared.is_finite() or declared < 0:
        raise TypeError(
            f"{rule.compliance_id}: tolerance must be a finite non-negative Decimal or None; "
            f"got {declared!r}"
        )
    return declared


def build_account_view(
    account: AccountSnapshot, marks: MarkBatch, observed_at: datetime
) -> EconomicAccountView:
    """The marked account as an author sees it.

    Built here, once per observation, rather than by each rule out of an `AccountSnapshot` and a
    `MarkBatch`: `nav = marks.total_value + account.cash` and `weight = value / nav` are the two
    derivations every weight rule needs and neither is a judgement, so a rule that got either
    subtly different from its neighbour would report a breach its neighbour permitted
    (`docs/issues/archive/014`).

    `observed_at` is the market-clock instant these marks are the account's value at.
    `MarkBatch` does not carry one: a `Mark` is a quantity, a price and their product, and when
    it was taken is a property of the instant that took it.
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
    "VERDICT_BREACHED",
    "VERDICT_HELD",
    "VERDICT_WITHIN_TOLERANCE",
    "ComplianceReport",
    "StampedFinding",
    "build_account_view",
    "compliance_requirements",
    "default_tolerance",
    "evaluate_compliance",
]
