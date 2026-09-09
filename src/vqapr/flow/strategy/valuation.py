"""The valuation phase: mark -> account, and monitoring.

Record `147`. What was `StrategyEventLoop._value_due`, `_dispatch_valuation`, `_dispatch_monitoring`
and their helpers, moved verbatim; `_marks_from_execution_snapshot` lives here because the
execution phase values the book from the snapshot it just filled against."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal

from vqapr.account.marking import SelectedMark
from vqapr.authoring.records import InvocationRecorder
from vqapr.constraints.evaluation import (
    ConstraintReport,
    evaluate_constraints,
    project_constraints,
)
from vqapr.domain.account_state import AccountMark, AccountSnapshot, AccountState
from vqapr.domain.agendas import OperationOccurrence
from vqapr.domain.values import MarkBatch
from vqapr.exchange.execution_table import exact_execution_snapshot
from vqapr.flow.engine.artifacts import (
    MonitoringEvidence,
    SimulationFailureKind,
    SimulationStage,
    ValuationEvidence,
)
from vqapr.flow.engine.run_state import AcceptedRunState, PreparedRunState
from vqapr.flow.strategy.context import (
    _ACCOUNT_IDENTITY,
    DEFAULT_TABLE_PREFIX,
    DEFAULT_TABLES,
    MONITORING_STAGE,
    VALUATION_STAGE,
    AcceptedIntent,
    FlowContext,
    HeldResult,
    MonitoringResult,
    PendingValuation,
    ValuationResult,
)


def _marks_from_execution_snapshot(
    snapshot: object,
    target_at: datetime,
    *,
    previous: AccountMark | None = None,
    held: Mapping[str, Decimal] | None = None,
) -> tuple[SelectedMark, ...]:
    """Value the book from the prices the venue published as executable at this instant.

    A row with a price marks the name, **including when `is_tradable` is false**: the venue
    published a price, and refusing to trade is a different fact from refusing to quote.

    A name the venue published nothing for **carries its previous mark forward, keeping the
    instant that mark was originally observed at**. A halt is not a reason to write a holding
    down, and it is not a reason to drop it out of NAV either; it is a reason for its price to
    stop moving. `SelectedMark.staleness(cutoff)` is what makes the gap visible afterwards.

    A name with no row and no previous mark produces nothing. That is a position the venue has
    never priced, so there is no honest number to put in the denominator.
    """
    marks: dict[str, SelectedMark] = {}
    for row in getattr(snapshot, "rows", ()):
        price = row.price
        if price is None or price <= 0:
            continue
        marks[row.instrument] = SelectedMark(row.instrument, price, target_at)
    if previous is not None and held is not None:
        for carried in previous.marks.marks:
            if carried.instrument_id in marks or carried.instrument_id not in held:
                continue
            observed_at = _observed_at(previous, carried.instrument_id)
            if observed_at is None:
                continue
            marks[carried.instrument_id] = SelectedMark(
                carried.instrument_id, carried.price, observed_at
            )
    return tuple(marks[instrument] for instrument in sorted(marks))


def _observed_at(mark: AccountMark, instrument: str) -> datetime | None:
    """When the carried price was actually observed, not when it was carried.

    A mark taken before this design carries no instant; it cannot claim one retroactively.
    """
    selected = mark.observed_at_by_instrument
    if selected is not None:
        return selected.get(instrument, mark.marked_at)
    return mark.marked_at


class ValuationHandler:
    """Values the book at each execution instant from the venue snapshot, commits the mark with
    the NAV it measured, and judges the committed account right after each commit (record `148`:
    valuation and monitoring have no clock of their own)."""

    def __init__(self, context: FlowContext) -> None:
        self._context = context

    def value_due(self, pending: PendingValuation) -> HeldResult:
        """Value the book at an execution instant that carried no orders.

        Same instant, same snapshot, same prices an order would have been filled at -- only
        without an order. The Account is not changed, so no version is consumed.
        """
        execution_table = self._context.frozen_run.execution
        if execution_table is None:
            raise RuntimeError("due valuation requires frozen execution dataset")
        account_state = self._context.state.current.account
        if account_state is None:
            raise RuntimeError("due valuation requires an AccountState root")
        before = account_state.snapshot
        held_instruments = tuple(before.positions)

        with self._context.due_boundary(
            stage=SimulationStage.DUE_SNAPSHOT,
            cutoff=pending.target.target_at,
            owner=execution_table,
            kind=SimulationFailureKind.PRE_COMMIT,
        ):
            snapshot = exact_execution_snapshot(
                execution_table.table,
                target_at=pending.target.target_at,
                target_instruments=(),
                held_instruments=held_instruments,
                trade_price=pending.target.trade_price,
                session=self._context.scan_session,
            )
        with self._context.due_boundary(
            stage=SimulationStage.DUE_VALUATION_SELECTION,
            cutoff=pending.target.target_at,
            owner=self._context.layer.agenda,
            kind=SimulationFailureKind.PRE_COMMIT,
        ):
            selected_marks = _marks_from_execution_snapshot(
                snapshot,
                pending.target.target_at,
                previous=account_state.latest_mark,
                held=before.positions,
            )
        with self._context.due_boundary(
            stage=SimulationStage.DUE_VALUATION_MARK,
            cutoff=pending.target.target_at,
            owner=self._context.layer.agenda,
            kind=SimulationFailureKind.PRE_COMMIT,
        ):
            mark = self._context.valuation_service.mark(before, selected_marks)
        evidence = ValuationEvidence(
            run_identity=self._context.frozen_run.identity,
            agenda=self._context.layer.agenda,
            occurrence=pending.occurrence,
            cutoff=pending.target.target_at,
            account=before,
            marks=mark,
            root_version=self._context.state.current.version,
            account_version=before.version,
        )
        with self._context.due_boundary(
            stage=SimulationStage.DUE_ACCOUNT_MARK,
            cutoff=pending.target.target_at,
            owner=account_state,
            kind=SimulationFailureKind.PRE_COMMIT,
        ):
            prepared_account = self._context.account.prepare_valuation(
                account_state,
                mark,
                expected_version=before.version,
                provenance=evidence,
                marked_at=pending.target.target_at,
                observed_at={
                    selected.instrument_id: selected.observed_at for selected in selected_marks
                },
            )
        with self._context.due_boundary(
            stage=SimulationStage.DUE_ACCOUNT_MARK,
            cutoff=pending.target.target_at,
            owner=account_state,
            kind=SimulationFailureKind.PRE_COMMIT,
        ):
            committed_mark = prepared_account.next_state.latest_mark
            if committed_mark is None:
                raise RuntimeError("a prepared Account valuation must carry the mark it appends")
            prepared_root = self._context.state.prepare_valuation_only(
                pending_id=pending.pending_id,
                account=prepared_account,
                mark=mark,
                evidence=evidence,
                recorder=self.measurement_recorder(
                    cutoff=pending.target.target_at,
                    account=before,
                    mark=committed_mark,
                    selected=selected_marks,
                ),
            )
        with self._context.due_boundary(
            stage=SimulationStage.DUE_ACCOUNT_MARK,
            cutoff=pending.target.target_at,
            owner=account_state,
            kind=SimulationFailureKind.FAILED_AFTER_COMMIT,
        ):
            self._context.account.commit_valuation(prepared_account)
        with self._context.due_boundary(
            stage=SimulationStage.DUE_ACCOUNT_MARK,
            cutoff=pending.target.target_at,
            owner=account_state,
            kind=SimulationFailureKind.FAILED_AFTER_COMMIT,
        ):
            self._context.state.publish_valuation_only(prepared_root)
        return HeldResult(evidence, self.monitor_after_commit(pending))

    def measurement_recorder(
        self,
        *,
        cutoff: datetime,
        account: AccountSnapshot,
        mark: AccountMark,
        selected: tuple[SelectedMark, ...],
    ) -> InvocationRecorder:
        """The NAV one mark measured, as rows of the package's own account table.

        Valuation happens at the instant the venue fills and nowhere else (record 148), so the
        measurement rides the same run-state transition as the mark it came from. `event_time`
        and `observed_at` are both that instant: dating the series by the decision that led to
        the fill would put every value one commit late (`callback.py` carries the number). The
        callback's own account row stays for a mark nothing here recorded, which is why the
        instant is remembered in `recorded_measurements`.
        """
        # Both mark paths stamp the instant they mark at; a mark without one was taken outside
        # the flow and has no measurement to date.
        if mark.marked_at is None:
            raise RuntimeError("a mark measured in the flow must carry the instant it was taken")
        recorder = InvocationRecorder(
            DEFAULT_TABLES,
            run_id=self._context.frozen_run.identity,
            producer_id=str(self._context.layer.config.component.component_id),
            stage=VALUATION_STAGE,
            event_time=self._context.in_agenda_zone(cutoff),
        )
        priced = {selection.instrument_id: selection for selection in selected}
        recorder.append(
            f"{DEFAULT_TABLE_PREFIX}account",
            {
                "instrument": _ACCOUNT_IDENTITY,
                # The values themselves, not their text: the run record writer records what
                # type each column was encoded from, so a reader gets a Decimal back.
                "cash": account.cash,
                "nav": mark.nav,
                "quantity": None,
                "price": None,
                "observed_at": mark.marked_at,
                "account_version": account.version,
            },
        )
        for instrument in (
            sorted(account.positions) if self._context.record_account_positions else ()
        ):
            selection = priced.get(instrument)
            recorder.append(
                f"{DEFAULT_TABLE_PREFIX}account",
                {
                    "instrument": instrument,
                    "cash": None,
                    "nav": None,
                    "quantity": account.positions[instrument],
                    "price": None if selection is None else selection.price,
                    "observed_at": None if selection is None else selection.observed_at,
                    "account_version": account.version,
                },
            )
        self._context.recorded_measurements.add(mark.marked_at)
        return recorder

    def publish_marked(self, prepared: PreparedRunState) -> AcceptedRunState:
        root = self._context.state.publish_marked(prepared)
        if root.account != self._context.account.state:
            raise RuntimeError("Account mark root does not mirror Account authority")
        return root

    def _committed_marks(self, state: AccountState) -> MarkBatch:
        """The valuation the Account already committed, or an empty one before the first mark.

        A run values its book where it executes. Between execution instants nothing about the
        valuation can have changed, because no new price has been published to change it.
        """
        latest = state.latest_mark
        if latest is None:
            return self._context.valuation_service.mark(state.snapshot, ())
        return latest.marks

    def monitor_after_commit(
        self, pending: AcceptedIntent | PendingValuation
    ) -> MonitoringResult | None:
        """Judge the committed, marked book at the execution instant it was just marked at.

        Record `148`: monitoring has no occurrence of its own. It runs right after each commit
        -- a fill's or a held book's -- reading the committed mark rather than valuing the book a
        second time, and the constraints read their data as of the fill instant. A run that
        declared no constraint has nothing to judge and records nothing.
        """
        if not self._context.constraints:
            return None
        occurrence = pending.occurrence
        cutoff = pending.target.target_at
        with self._context.due_boundary(
            stage=SimulationStage.MONITORING,
            cutoff=cutoff,
            owner=self._context.layer.agenda,
            kind=SimulationFailureKind.FAILED_AFTER_COMMIT,
        ):
            return self._monitor(occurrence, cutoff)

    def _monitor(self, occurrence: OperationOccurrence, cutoff: datetime) -> MonitoringResult:
        state = self._context.state.current.account
        if state is None:
            raise RuntimeError("monitoring requires an AccountState root")
        current = state.snapshot
        window = self._context.constraint_window_at(cutoff)
        # Restored before, committed after, with the findings (record `181`): what `project`
        # and `monitor` leave in a constraint's memory is published in the monitoring root.
        self._context.restore_component_memory(self._context.visible_component_memory())
        projected = project_constraints(self._context.constraints, window)
        # Monitoring judges the account the run actually committed, so it reads the committed
        # mark rather than valuing the book a second time.
        marks = self._committed_marks(state)
        valuation_evidence = ValuationEvidence(
            run_identity=self._context.frozen_run.identity,
            agenda=self._context.layer.agenda,
            occurrence=occurrence,
            cutoff=cutoff,
            account=current,
            marks=marks,
            root_version=self._context.state.current.version,
            account_version=current.version,
        )
        valuation = ValuationResult(current, marks, valuation_evidence)
        report = evaluate_constraints(self._context.constraints, window, current, marks, projected)
        evidence = MonitoringEvidence(
            run_identity=self._context.frozen_run.identity,
            agenda=self._context.layer.agenda,
            occurrence=occurrence,
            cutoff=cutoff,
            account=current,
            valuation=valuation_evidence,
            report=report,
            root_version=self._context.state.current.version,
        )
        if report.findings:
            self._record_findings(
                occurrence, report, cutoff, self._context.candidate_component_memory()
            )
        return MonitoringResult(valuation, report, evidence)

    def _record_findings(
        self,
        occurrence: OperationOccurrence,
        report: ConstraintReport,
        cutoff: datetime,
        component_memory: Mapping[str, object],
    ) -> None:
        """Write what monitoring measured into the package's own table, and publish it.

        Through the same accept funnel as a valuation's rows, so a run with a store streams
        these to disk as each occurrence passes and a run killed midway keeps every finding it
        made. A run that declared no constraint writes nothing here rather than an empty
        occurrence: there is no finding to record, and a lifecycle entry saying so would be
        noise on every monitoring day.

        `event_time` is the monitoring cutoff -- when the account was judged -- and `offenders`
        is the breaching names joined by a single space, which no instrument id may contain, so
        a reader splits on it without a quoting rule.
        """
        recorder = InvocationRecorder(
            DEFAULT_TABLES,
            run_id=self._context.frozen_run.identity,
            producer_id=str(self._context.layer.config.component.component_id),
            stage=MONITORING_STAGE,
            event_time=self._context.in_agenda_zone(cutoff),
        )
        for finding in report.findings:
            recorder.append(
                f"{DEFAULT_TABLE_PREFIX}monitoring",
                {
                    "constraint": finding.constraint_id,
                    "passed": finding.passed,
                    "measured": finding.measured,
                    "bound": finding.bound,
                    "excess": finding.excess,
                    # The framework's verdict beside the author's `passed`
                    # (`docs/issues/archive/086`): `held`, `within_tolerance` or `breached`, and the
                    # tolerance it was judged against, so a reader of this table can split the
                    # populations the way the record's `contract` block does.
                    "verdict": finding.verdict,
                    "tolerance": finding.tolerance,
                    "offenders": " ".join(finding.offenders),
                    "account_version": report.account_version,
                },
            )
        self._context.state.publish_monitoring(
            self._context.state.prepare_monitoring(
                recorder=recorder, component_memory=component_memory
            )
        )
