"""The VALUATION stage: mark -> account.

Record `147`. What was `StrategyEventLoop._value_due`, `_dispatch_valuation` and their helpers,
moved verbatim; `_marks_from_execution_snapshot` lives here because the execution phase values
the book from the snapshot it just filled against. Record `209` moved monitoring out to
`compliance.py`: it is the next stage of the market-clock instant, not part of this one."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal

from vqapr.account.marking import SelectedMark
from vqapr.authoring.records import InvocationRecorder
from vqapr.domain.account_state import AccountMark, AccountSnapshot
from vqapr.flow.engine.artifacts import (
    MarkEvidence,
    SimulationFailureKind,
    SimulationStage,
    ValuationEvidence,
)
from vqapr.flow.engine.run_state import AcceptedRunState, PreparedRunState
from vqapr.flow.run.context import (
    _ACCOUNT_IDENTITY,
    DEFAULT_TABLE_PREFIX,
    DEFAULT_TABLES,
    VALUATION_STAGE,
    Filled,
    FlowContext,
    Marked,
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
    """VALUATION and COMPLIANCE: values the book at every market-clock instant from the venue
    snapshot -- the fill's own (`mark_fill`) or a fresh one for a held book (`mark_held`) --
    commits the mark with the NAV it measured, and judges the committed account right after
    (design §3.1: two stages of the market clock, with no clock of their own)."""

    def __init__(self, context: FlowContext) -> None:
        self._context = context

    def mark_fill(self, filled: Filled) -> Marked:
        """VALUATION after EXECUTE: value the just-committed book from the snapshot the fill was
        priced from, and publish the mark on the same root (record `148`: the marked account and
        the account-table row stating its NAV are one commit)."""
        pending = filled.pending
        at = pending.target.target_at
        prepared_fill = filled.prepared_fill
        committed_root = filled.committed_root
        with self._context.due_boundary(
            stage=SimulationStage.DUE_VALUATION_SELECTION,
            cutoff=at,
            owner=self._context.layer.agenda,
            kind=SimulationFailureKind.FAILED_AFTER_COMMIT,
        ):
            selected_marks = _marks_from_execution_snapshot(
                filled.snapshot,
                at,
                previous=filled.previous_mark,
                held=prepared_fill.next_snapshot.positions,
            )
        with self._context.due_boundary(
            stage=SimulationStage.DUE_VALUATION_MARK,
            cutoff=at,
            owner=self._context.layer.agenda,
            kind=SimulationFailureKind.FAILED_AFTER_COMMIT,
        ):
            mark = self._context.valuation_service.mark(prepared_fill.next_snapshot, selected_marks)
        with self._context.due_boundary(
            stage=SimulationStage.DUE_ACCOUNT_MARK,
            cutoff=at,
            owner=committed_root.account,
            kind=SimulationFailureKind.FAILED_AFTER_COMMIT,
        ):
            committed_account = committed_root.account
            if committed_account is None:
                raise RuntimeError("a committed root must carry the Account it appended to")
            prepared_account = self._context.account.mark(
                committed_account,
                mark,
                marked_at=at,
                observed_at={
                    selected.instrument_id: selected.observed_at for selected in selected_marks
                },
                provenance=ValuationEvidence(
                    run_identity=self._context.frozen_run.identity,
                    agenda=self._context.layer.agenda,
                    occurrence=pending.occurrence,
                    root_version=committed_root.version,
                    cutoff=at,
                    account=prepared_fill.next_snapshot,
                    marks=mark.summary(),
                    account_version=prepared_fill.next_snapshot.version,
                ),
            )
        mark_evidence = MarkEvidence(
            run_identity=self._context.frozen_run.identity,
            agenda=self._context.layer.agenda,
            occurrence=pending.occurrence,
            cutoff=at,
            selected=len(selected_marks),
            marks=mark.summary(),
            limitations=(),
            account=prepared_account.next_state.snapshot,
            root_version=committed_root.version,
            account_version=prepared_account.next_state.snapshot.version,
        )
        with self._context.due_boundary(
            stage=SimulationStage.DUE_ACCOUNT_MARK,
            cutoff=at,
            owner=committed_root.account,
            kind=SimulationFailureKind.FAILED_AFTER_COMMIT,
        ):
            committed_mark = prepared_account.mark
            prepared_marked = self._context.state.prepare_account(
                prepared_account,
                evidence=mark_evidence,
                recorder=self.measurement_recorder(
                    cutoff=at,
                    account=prepared_account.next_state.snapshot,
                    mark=committed_mark,
                    selected=selected_marks,
                ),
            )
        with self._context.due_boundary(
            stage=SimulationStage.DUE_ACCOUNT_MARK,
            cutoff=at,
            owner=committed_root.account,
            kind=SimulationFailureKind.FAILED_AFTER_COMMIT,
        ):
            self._context.account.commit_mark(prepared_account)
        with self._context.due_boundary(
            stage=SimulationStage.DUE_ACCOUNT_MARK,
            cutoff=at,
            owner=committed_root.account,
            kind=SimulationFailureKind.FAILED_AFTER_COMMIT,
        ):
            marked_root = self.publish_marked(prepared_marked)
        return Marked(marked_root, mark, mark_evidence, selected_marks)

    def mark_held(self, instant: datetime) -> Marked:
        """VALUATION at a market-clock instant no fill was due at: value the held book.

        Same instant, same snapshot, same prices an order would have been filled at -- only
        without an order. The Account is not changed, so no version is consumed, and a pending
        intent whose target is a later instant stays pending.
        """
        execution_table = self._context.frozen_run.execution
        if execution_table is None:
            raise RuntimeError("valuation requires frozen execution dataset")
        account_state = self._context.state.current.account
        if account_state is None:
            raise RuntimeError("valuation requires an AccountState root")
        before = account_state.snapshot
        held_instruments = tuple(before.positions)

        with self._context.due_boundary(
            stage=SimulationStage.DUE_SNAPSHOT,
            cutoff=instant,
            owner=execution_table,
            kind=SimulationFailureKind.PRE_COMMIT,
        ):
            snapshot = self._context.execution_snapshot(
                instant,
                target_instruments=(),
                held_instruments=held_instruments,
                trade_price=execution_table.fill.trade_price,
                with_reference=False,
            )
        with self._context.due_boundary(
            stage=SimulationStage.DUE_VALUATION_SELECTION,
            cutoff=instant,
            owner=self._context.layer.agenda,
            kind=SimulationFailureKind.PRE_COMMIT,
        ):
            selected_marks = _marks_from_execution_snapshot(
                snapshot,
                instant,
                previous=account_state.latest_mark,
                held=before.positions,
            )
        with self._context.due_boundary(
            stage=SimulationStage.DUE_VALUATION_MARK,
            cutoff=instant,
            owner=self._context.layer.agenda,
            kind=SimulationFailureKind.PRE_COMMIT,
        ):
            mark = self._context.valuation_service.mark(before, selected_marks)
        evidence = ValuationEvidence(
            run_identity=self._context.frozen_run.identity,
            agenda=self._context.layer.agenda,
            occurrence=None,
            cutoff=instant,
            account=before,
            marks=mark.summary(),
            root_version=self._context.state.current.version,
            account_version=before.version,
        )
        with self._context.due_boundary(
            stage=SimulationStage.DUE_ACCOUNT_MARK,
            cutoff=instant,
            owner=account_state,
            kind=SimulationFailureKind.PRE_COMMIT,
        ):
            prepared_account = self._context.account.mark(
                account_state,
                mark,
                provenance=evidence,
                marked_at=instant,
                observed_at={
                    selected.instrument_id: selected.observed_at for selected in selected_marks
                },
            )
        with self._context.due_boundary(
            stage=SimulationStage.DUE_ACCOUNT_MARK,
            cutoff=instant,
            owner=account_state,
            kind=SimulationFailureKind.PRE_COMMIT,
        ):
            committed_mark = prepared_account.mark
            prepared_root = self._context.state.prepare_account(
                prepared_account,
                evidence=evidence,
                recorder=self.measurement_recorder(
                    cutoff=instant,
                    account=before,
                    mark=committed_mark,
                    selected=selected_marks,
                ),
            )
        with self._context.due_boundary(
            stage=SimulationStage.DUE_ACCOUNT_MARK,
            cutoff=instant,
            owner=account_state,
            kind=SimulationFailureKind.FAILED_AFTER_COMMIT,
        ):
            self._context.account.commit_mark(prepared_account)
        with self._context.due_boundary(
            stage=SimulationStage.DUE_ACCOUNT_MARK,
            cutoff=instant,
            owner=account_state,
            kind=SimulationFailureKind.FAILED_AFTER_COMMIT,
        ):
            root = self._context.state.publish_infallible(prepared_root)
        return Marked(root, mark, evidence, selected_marks)

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
        # The `_ACCOUNT` row first -- cash and NAV, the values themselves and not their text, so
        # a reader gets a Decimal back -- then one row per held name: its quantity, the price it
        # was marked at and when that price was observed. As columns (record `221`): a 3,000-name
        # book is seven tuples here, not 3,000 dicts, and is checked by column.
        held = sorted(account.positions) if self._context.record_account_positions else []
        selections = [priced.get(instrument) for instrument in held]
        nothing = [None] * len(held)
        recorder.append_columns(
            f"{DEFAULT_TABLE_PREFIX}account",
            {
                "instrument": [_ACCOUNT_IDENTITY, *held],
                "cash": [account.cash, *nothing],
                "nav": [mark.nav, *nothing],
                "quantity": [None, *(account.positions[instrument] for instrument in held)],
                "price": [None, *(None if s is None else s.price for s in selections)],
                "observed_at": [
                    mark.marked_at,
                    *(None if s is None else s.observed_at for s in selections),
                ],
                "account_version": [account.version] * (len(held) + 1),
            },
        )
        self._context.recorded_measurements.add(mark.marked_at)
        return recorder

    def publish_marked(self, prepared: PreparedRunState) -> AcceptedRunState:
        root = self._context.state.publish_infallible(prepared)
        if root.account != self._context.account.state:
            raise RuntimeError("Account mark root does not mirror Account authority")
        return root
