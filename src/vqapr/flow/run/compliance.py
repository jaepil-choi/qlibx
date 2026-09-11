"""COMPLIANCE: the fourth stage of a market-clock instant (design §3.1, §7.2).

Right after the book is marked, every Compliance rule the run declared observes it -- as of this
instant, reading what it subscribed to as of this instant -- and what each found is written to
`vqapr.monitoring` and published with the rule's memory. The observer changes nothing: no fill,
no mark, no decision, and the pending slot is left exactly as found.

Record `209`: this is the monitoring half of `valuation.py` (record `148`) on its own clock,
without the projection it used to redo first. A rule measures with its own parameters against
its own reads; the box the strategy built inside is not handed to it, because a watcher that
inherits the target of the thing it watches is grading itself.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime

from vqapr.authoring.records import InvocationRecorder
from vqapr.compliance.evaluation import ComplianceReport, evaluate_compliance
from vqapr.flow.engine.artifacts import (
    MonitoringEvidence,
    SimulationFailureKind,
    SimulationStage,
    ValuationEvidence,
)
from vqapr.flow.run.context import (
    DEFAULT_TABLES,
    MONITORING_STAGE,
    FlowContext,
    MarketInstant,
    MonitoringResult,
    ValuationResult,
)
from vqapr.record.schema import DEFAULT_TABLE_PREFIX


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
