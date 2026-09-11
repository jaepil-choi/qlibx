"""COMPLIANCE: the fourth stage of a market-clock instant (design §3.1, §7.2).

Right after the book is marked, every Compliance rule the run declared observes it -- as of this
instant, reading what it subscribed to as of this instant -- and what each found is written to
`vqapr.monitoring` and published with the rule's memory. The observer changes nothing: no fill,
no mark, no decision, and the pending slot is left exactly as found.

Record `209`: this is the monitoring half of `valuation.py` (record `148`) on its own clock,
without the projection it used to redo first. A rule measures with its own parameters against
its own reads; the box the strategy built inside is not handed to it, because a watcher that
inherits the target of the thing it watches is grading itself.

The rule set's evaluation lives here too. A finding says what was measured; which rule measured it
is said once -- the rule declares its id, the loader checks it against the id it was registered
under, and this stage stamps it onto the finding. The stamped finding, its tolerance and verdict,
and the report they make are values in `component/compliance/report.py`: the run context carries
the report, and this stage imports the context.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime
from decimal import Decimal

from vqapr.component.account_view import EconomicAccountView
from vqapr.component.compliance.base import Compliance, ComplianceFinding
from vqapr.component.compliance.report import ComplianceReport, StampedFinding
from vqapr.component.strategy.recorder import InvocationRecorder
from vqapr.data.requirement import DataRequirement
from vqapr.data.window import ModelWindow
from vqapr.domain.account import AccountSnapshot, MarkBatch
from vqapr.record.schema import DEFAULT_TABLE_PREFIX
from vqapr.run.engine.calls import ComplianceContext
from vqapr.run.engine.context import (
    DEFAULT_TABLES,
    MONITORING_STAGE,
    FlowContext,
    MarketInstant,
    MonitoringResult,
    ValuationResult,
)
from vqapr.run.engine.evidence import MonitoringEvidence, ValuationEvidence
from vqapr.run.engine.failure import SimulationFailureKind, SimulationStage

__all__ = [
    "ComplianceHandler",
    "build_account_view",
    "compliance_requirements",
    "evaluate_compliance",
]


















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
                        account=view,
                        instruments=window.instruments,
                        reads=rule.inputs(),
                    )
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
    # Trusted (record `223`): the snapshot and the marks proved every id and value when they
    # were committed, and this runs once per market-clock instant on every held name.
    return EconomicAccountView._trusted(
        cash=account.cash,
        positions=account.positions,
        values={mark.instrument_id: mark.value for mark in marks.marks},
        nav=nav,
        nav_observed_at=observed_at,
    )


class ComplianceHandler:
    """COMPLIANCE: the declared rules observe the committed, marked book at a market instant."""

    def __init__(self, context: FlowContext) -> None:
        self._context = context

    def observe(self, instant: MarketInstant) -> MarketInstant:
        """COMPLIANCE: judge the book VALUATION just marked, at the instant it marked it.

        A run that declared no rule has nothing to observe and records nothing -- `monitoring`
        stays `None`, not an empty report, so a reader of the trace can tell "nothing to judge"
        from "judged clean".
        """
        if not self._context.compliance:
            return instant
        with self._context.due_boundary(
            stage=SimulationStage.MARKET_COMPLIANCE,
            cutoff=instant.at,
            owner=self._context.layer.compliance,
            kind=SimulationFailureKind.FAILED_AFTER_COMMIT,
        ):
            return replace(instant, monitoring=self._observe(instant))

    def _observe(self, instant: MarketInstant) -> MonitoringResult:
        # The rules judge the account the run actually committed: the mark VALUATION left on
        # this instant (record `226`), not a second valuation and not a re-read of the root.
        marked = instant.require_marked()
        root = marked.root
        state = root.account
        if state is None:
            raise RuntimeError("compliance requires an AccountState root")
        current = state.snapshot
        window = self._context.compliance_window_at(instant.at)
        # Restored before, committed after, with the findings (record `181`): what `observe`
        # leaves in a rule's memory is published in the monitoring root.
        self._context.restore_component_memory(self._context.visible_component_memory())
        summary = marked.mark.summary()
        valuation_evidence = ValuationEvidence(
            run_identity=self._context.frozen_run.identity,
            agenda=self._context.layer.agenda,
            occurrence=None,
            cutoff=instant.at,
            account=current,
            marks=summary,
            root_version=root.version,
            account_version=current.version,
        )
        valuation = ValuationResult(current, summary, valuation_evidence)
        report = evaluate_compliance(self._context.compliance, window, current, marked.mark)
        evidence = MonitoringEvidence(
            run_identity=self._context.frozen_run.identity,
            agenda=self._context.layer.agenda,
            cutoff=instant.at,
            account=current,
            valuation=valuation_evidence,
            report=report,
            root_version=root.version,
        )
        if report.findings:
            self._record_findings(report, instant.at, self._context.candidate_component_memory())
        return MonitoringResult(valuation, report, evidence)

    def _record_findings(
        self,
        report: ComplianceReport,
        instant: datetime,
        component_memory: Mapping[str, object],
    ) -> None:
        """Write what the rules measured into the package's own table, and publish it.

        Through the same accept funnel as a valuation's rows, so a run with a store streams
        these to disk as each instant passes and a run killed midway keeps every finding it
        made. `event_time` is the instant the book was judged at -- when it was marked -- and
        `offenders` is the breaching names joined by a single space, which no instrument id may
        contain, so a reader splits on it without a quoting rule.
        """
        recorder = InvocationRecorder(
            DEFAULT_TABLES,
            run_id=self._context.frozen_run.identity,
            producer_id=str(self._context.layer.config.component.component_id),
            stage=MONITORING_STAGE,
            event_time=self._context.in_agenda_zone(instant),
            sequencer=self._context.next_sequence,
        )
        for finding in report.findings:
            recorder.append(
                f"{DEFAULT_TABLE_PREFIX}monitoring",
                {
                    "rule": finding.rule_id,
                    "passed": finding.passed,
                    "measured": finding.measured,
                    "bound": finding.bound,
                    "excess": finding.excess,
                    # The framework's verdict beside the author's `passed`
                    # (`docs/issues/archive/086`): `held`, `within_tolerance` or `breached`, and
                    # the tolerance it was judged against, so a reader of this table can split
                    # the populations the way the record's `contract` block does.
                    "verdict": finding.verdict,
                    "tolerance": finding.tolerance,
                    "offenders": " ".join(finding.offenders),
                    "account_version": report.account_version,
                },
            )
        self._context.state.publish_infallible(
            self._context.state.prepare_monitoring(
                recorder=recorder, component_memory=component_memory
            )
        )
