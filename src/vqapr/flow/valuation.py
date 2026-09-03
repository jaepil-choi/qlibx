"""The valuation phase: mark -> account, and monitoring.

Record `147`. What was `SimulationFlow._value_due`, `_dispatch_valuation`, `_dispatch_monitoring`
and their helpers, moved verbatim; `_marks_from_execution_snapshot` lives here because the
execution phase values the book from the snapshot it just filled against."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from vqapr.account.snapshot import AccountMark, AccountState
from vqapr.constraints.evaluation import (
    evaluate_constraints,
    project_constraints,
)
from vqapr.constraints.findings import ConstraintReport
from vqapr.data.windows import ModelWindow
from vqapr.evidence.artifacts import (
    MonitoringEvidence,
    SimulationFailureFamily,
    SimulationFailureKind,
    SimulationStage,
    ValuationEvidence,
)
from vqapr.evidence.recorder import InvocationRecorder
from vqapr.exchange.execution_table import exact_execution_snapshot
from vqapr.flow.context import (
    _ACCOUNT_IDENTITY,
    DEFAULT_TABLE_PREFIX,
    DEFAULT_TABLES,
    FlowContext,
    MonitoringResult,
    OccurrenceTrace,
    PendingValuation,
    ValuationResult,
)
from vqapr.runtime.agendas import OperationOccurrence
from vqapr.valuation.marking import SelectedMark
from vqapr.valuation.marks import MarkBatch

if TYPE_CHECKING:
    from vqapr.flow.callback import CallbackPhase



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



class ValuationPhase:
    """Values the book -- at an execution instant from the snapshot, or standalone at a valuation
    occurrence -- commits the mark, and judges the committed account at a monitoring occurrence."""

    def __init__(self, context: FlowContext, callback: CallbackPhase) -> None:
        self._context = context
        self._callback = callback

    def value_due(self, pending: PendingValuation) -> object:
        """Value the book at an execution instant that carried no orders.

        Same instant, same snapshot, same prices an order would have been filled at -- only
        without an order. The Account is not changed, so no version is consumed.
        """
        execution_input = self._context.frozen_run.execution_input
        if execution_input is None:
            raise RuntimeError("due valuation requires frozen execution input")
        account_state = self._context.state.current.account
        if not isinstance(account_state, AccountState):
            raise RuntimeError("due valuation requires an AccountState root")
        before = account_state.snapshot
        held_instruments = tuple(before.positions)

        snapshot = self._context.due_boundary(
            stage=SimulationStage.DUE_SNAPSHOT,
            cutoff=pending.target.target_at,
            owner=execution_input,
            family=SimulationFailureFamily.DATA,
            kind=SimulationFailureKind.PRE_COMMIT,
            operation=lambda: exact_execution_snapshot(
                execution_input.table,
                target_at=pending.target.target_at,
                target_instruments=(),
                held_instruments=held_instruments,
                trade_price=pending.target.trade_price,
                session=self._context.scan_session,
            ),
        )
        selected_marks = self._context.due_boundary(
            stage=SimulationStage.DUE_VALUATION_SELECTION,
            cutoff=pending.target.target_at,
            owner=self._context.frozen_run.valuation,
            family=SimulationFailureFamily.VALUATION,
            kind=SimulationFailureKind.PRE_COMMIT,
            operation=lambda: _marks_from_execution_snapshot(
                snapshot,
                pending.target.target_at,
                previous=account_state.latest_mark,
                held=before.positions,
            ),
        )
        mark = self._context.due_boundary(
            stage=SimulationStage.DUE_VALUATION_MARK,
            cutoff=pending.target.target_at,
            owner=self._context.frozen_run.valuation,
            family=SimulationFailureFamily.VALUATION,
            kind=SimulationFailureKind.PRE_COMMIT,
            operation=lambda: self._context.valuation_service.mark(before, selected_marks),
        )
        evidence = ValuationEvidence(
            run_identity=self._context.frozen_run.identity,
            agenda=self._context.layer.agenda,
            occurrence=pending.occurrence,
            cutoff=pending.target.target_at,
            valuation_config=self._context.frozen_run.valuation,
            account=before,
            marks=mark,
            root_version=self._context.state.current.version,
            account_version=before.version,
        )
        prepared_account = self._context.due_boundary(
            stage=SimulationStage.DUE_ACCOUNT_MARK,
            cutoff=pending.target.target_at,
            owner=account_state,
            family=SimulationFailureFamily.ACCOUNT,
            kind=SimulationFailureKind.PRE_COMMIT,
            operation=lambda: self._context.account.prepare_valuation(
                account_state,
                mark,
                expected_version=before.version,
                provenance=evidence,
                marked_at=pending.target.target_at,
                observed_at={
                    selected.instrument_id: selected.observed_at for selected in selected_marks
                },
            ),
        )
        prepared_root = self._context.due_boundary(
            stage=SimulationStage.DUE_ACCOUNT_MARK,
            cutoff=pending.target.target_at,
            owner=account_state,
            family=SimulationFailureFamily.ACCOUNT,
            kind=SimulationFailureKind.PRE_COMMIT,
            operation=lambda: self._context.state.prepare_valuation_only(
                pending_id=pending.pending_id,
                account=prepared_account,
                mark=mark,
                evidence=evidence,
            ),
        )
        self._context.due_boundary(
            stage=SimulationStage.DUE_ACCOUNT_MARK,
            cutoff=pending.target.target_at,
            owner=account_state,
            family=SimulationFailureFamily.ACCOUNT,
            kind=SimulationFailureKind.FAILED_AFTER_COMMIT,
            operation=lambda: self._context.account.commit_valuation(prepared_account),
        )
        self._context.due_boundary(
            stage=SimulationStage.DUE_ACCOUNT_MARK,
            cutoff=pending.target.target_at,
            owner=account_state,
            family=SimulationFailureFamily.ACCOUNT,
            kind=SimulationFailureKind.FAILED_AFTER_COMMIT,
            operation=lambda: self._context.state.publish_valuation_only(prepared_root),
        )
        return evidence

    def publish_marked(self, prepared: object) -> object:
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

    def _valuation_instant(self, occurrence: OperationOccurrence) -> datetime | None:
        """The execution instant a standalone valuation marks at, or `None` when none exists.

        Valuation resolution is (valuation clock) intersected with (execution `trade_at` set). The
        valuation clock says *when the run wants to know* what the book is worth; the execution
        table says *when the venue published a price* that could answer. Only their intersection
        is a moment where an honest number exists.

        This deliberately does not reuse `select_target`. That selects the first **strictly-later**
        eligible instant, which is right for an intent -- a decision cannot fill in a print that
        already happened -- and wrong here by exactly one instant: on the shipped cadence (decide
        08:00, fill 15:30, value 16:00) a 16:00 valuation would bind *tomorrow's* fill rather than
        the 15:30 close that just happened, stamping NAV one execution instant late along its
        entire length.
        """
        execution_input = self._context.frozen_run.execution_input
        if execution_input is None or self._context.frozen_run.end is None:
            # A run declared without execution authority never values against venue prices.
            return None
        return self._callback.execution_horizon(execution_input).at_or_before(
            occurrence.evaluation_time
        )

    def _standalone_marks(
        self, state: AccountState, valuation_at: datetime
    ) -> tuple[SelectedMark, ...]:
        """Value the held book from the prices the venue published at `valuation_at`.

        This is the same mark path a due execution uses -- `exact_execution_snapshot` feeding
        `_marks_from_execution_snapshot` -- so a standalone valuation and a fill-time valuation
        cannot disagree about what a price means. Reaching that path was the whole point of the
        change; only the instant it is asked about is different.
        """
        execution_input = self._context.frozen_run.execution_input
        if execution_input is None:
            return ()
        held = state.snapshot.positions
        if not held:
            return ()
        snapshot = exact_execution_snapshot(
            execution_input.table,
            target_at=valuation_at,
            target_instruments=(),
            held_instruments=tuple(held),
            trade_price=execution_input.fill.trade_price,
            session=self._context.scan_session,
        )
        return _marks_from_execution_snapshot(
            snapshot,
            valuation_at,
            previous=state.latest_mark,
            held=held,
        )

    def dispatch_valuation(self, occurrence: OperationOccurrence) -> OccurrenceTrace:
        state = self._context.state.current.account
        if not isinstance(state, AccountState):
            raise RuntimeError("valuation requires an AccountState root")
        account = state.snapshot
        # A valuation occurrence marks at its OWN instant. It used to replay whatever mark the
        # Account last committed, which made the NAV series inherit the decision cadence: a
        # monthly-rebalancing strategy reported a monthly NAV even though the venue published a
        # price every session and the book was worth something on every one of them.
        #
        # The pending slot is never touched here. `pending_accepted_intent` holds a single
        # occupant (`run_state.py:59`), so routing a daily valuation through it would overwrite
        # accepted decisions on most days. Marking synchronously sidesteps that entirely, which
        # is the decisive reason this is done here rather than through the pending lifecycle.
        valuation_at = self._valuation_instant(occurrence)
        if valuation_at is None:
            # The venue published no price at or before this instant, so no value exists. That is
            # a fact about the venue, not a failure, and it is reported as the empty mark rather
            # than as a stale number carried forward from somewhere else.
            selected: tuple[SelectedMark, ...] = ()
        else:
            selected = self._standalone_marks(state, valuation_at)
        marks = self._context.valuation_service.mark(account, selected)
        evidence = ValuationEvidence(
            run_identity=self._context.frozen_run.identity,
            agenda=self._context.frozen_run.valuation_agenda,
            occurrence=occurrence,
            cutoff=occurrence.evaluation_time,
            valuation_config=self._context.frozen_run.valuation,
            account=account,
            marks=marks,
            root_version=self._context.state.current.version,
            account_version=account.version,
        )
        valuation = ValuationResult(account, marks, evidence)
        if self._standalone_valuation_adds_a_measurement(state, occurrence):
            self._commit_standalone_valuation(occurrence, state, marks, selected, evidence)
        return OccurrenceTrace(occurrence, valuation, self._context.state.current)

    def _standalone_valuation_adds_a_measurement(
        self, state: AccountState, occurrence: OperationOccurrence
    ) -> bool:
        """Whether this occurrence has something new to record, or the book is already valued.

        Mark history is strictly increasing in instant (`account/snapshot.py:118-122`), and it is
        that way because two marks at one instant are two answers to the same question. A fill
        already marks the book at its own execution instant, so a valuation occurrence landing on
        an instant already marked has nothing to add -- recording anyway would not merely
        duplicate a row, it would break the invariant.

        The value of the book is unchanged either way. What is skipped is a redundant restatement
        of it, not a measurement.
        """
        latest = state.latest_mark
        if latest is None or latest.marked_at is None:
            return True
        return occurrence.evaluation_time > latest.marked_at

    def _commit_standalone_valuation(
        self,
        occurrence: OperationOccurrence,
        state: AccountState,
        marks: MarkBatch,
        selected: tuple[SelectedMark, ...],
        evidence: ValuationEvidence,
    ) -> None:
        """Commit the mark and write the NAV it measured into the package's own account table.

        Marking without recording would leave the change invisible. `vqapr.account` is what a
        later reader reconstructs the series from (canon 7.3), and it was written **only** from
        the strategy-callback path, so the series resolution silently followed the DECISION clock:
        a monthly-rebalancing strategy left a monthly NAV series no matter how often the run
        valued the book. Recording here is what makes the valuation clock's independence
        observable rather than merely internal.

        The Account does not change -- there is no fill -- so this goes through the mark-only
        transition rather than an account commit, and the pending slot is still never touched.

        `observed_at` carries the instant each price was measured at, which is not the instant
        this row was written. Keeping them two columns is what lets a reader date the series by
        the measurement rather than by the occurrence; mislabelling one for the other was measured
        moving a factor correlation from 0.93 to 0.02.
        """
        observed_at = {mark.instrument_id: mark.observed_at for mark in selected}
        prepared_account = self._context.account.prepare_valuation(
            state,
            marks,
            expected_version=state.snapshot.version,
            provenance=evidence,
            marked_at=occurrence.evaluation_time,
            observed_at=observed_at,
        )
        mark = prepared_account.next_state.latest_mark
        account = state.snapshot

        recorder = InvocationRecorder(
            DEFAULT_TABLES,
            run_id=self._context.frozen_run.identity,
            producer_id=str(self._context.layer.config.component.component_id),
            stage=occurrence.role.value,
            event_time=occurrence.evaluation_time,
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

        self._context.account.commit_valuation(prepared_account)
        self._context.state.publish_standalone_valuation(
            self._context.state.prepare_standalone_valuation(
                account=prepared_account,
                mark=marks,
                recorder=recorder,
                evidence=evidence,
            )
        )
        # Recorded so a later callback does not write this same measurement a second time. Keyed
        # on the instant the mark was TAKEN rather than on this occurrence, because a callback
        # replays a committed mark and the two clocks differ -- comparing occurrences would never
        # match, and the duplicate would go out under a later `available_at`.
        recorded_at = getattr(mark, "marked_at", None)
        if recorded_at is not None:
            self._context.recorded_measurements.add(recorded_at)

    def dispatch_monitoring(self, occurrence: OperationOccurrence) -> OccurrenceTrace:
        state = self._context.state.current.account
        if not isinstance(state, AccountState):
            raise RuntimeError("monitoring requires an AccountState root")
        current = state.snapshot
        window = None
        projected = ()
        if self._context.constraints:
            window = self._context.constraint_window_for_occurrence(occurrence)
            if not isinstance(window, ModelWindow):
                raise TypeError("constraint_window_for_occurrence must return a ModelWindow")
            projected = project_constraints(self._context.constraints, window)
        # Monitoring judges the account the run actually committed, so it reads the committed
        # mark rather than valuing the book a second time.
        marks = self._committed_marks(state)
        valuation_evidence = ValuationEvidence(
            run_identity=self._context.frozen_run.identity,
            agenda=self._context.frozen_run.monitoring_agenda,
            occurrence=occurrence,
            cutoff=occurrence.evaluation_time,
            valuation_config=self._context.frozen_run.valuation,
            account=current,
            marks=marks,
            root_version=self._context.state.current.version,
            account_version=current.version,
        )
        valuation = ValuationResult(current, marks, valuation_evidence)
        report = evaluate_constraints(self._context.constraints, window, current, marks, projected)
        evidence = MonitoringEvidence(
            run_identity=self._context.frozen_run.identity,
            agenda=self._context.frozen_run.monitoring_agenda,
            occurrence=occurrence,
            cutoff=occurrence.evaluation_time,
            account=current,
            valuation=valuation_evidence,
            report=report,
            root_version=self._context.state.current.version,
        )
        if report.findings:
            self._record_findings(occurrence, report)
        return OccurrenceTrace(
            occurrence, MonitoringResult(valuation, report, evidence), self._context.state.current
        )

    def _record_findings(self, occurrence: OperationOccurrence, report: ConstraintReport) -> None:
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
            stage=occurrence.role.value,
            event_time=occurrence.evaluation_time,
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
                    "offenders": " ".join(finding.offenders),
                    "account_version": report.account_version,
                },
            )
        self._context.state.publish_monitoring(self._context.state.prepare_monitoring(recorder=recorder))

    def committed_mark(self) -> object | None:
        state = self._context.state.current.account
        return state.latest_mark if isinstance(state, AccountState) else None

