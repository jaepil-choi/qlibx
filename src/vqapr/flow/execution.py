"""The execution phase: an accepted intent becomes orders, fills and a committed account.

Record `147`. What was `StrategyEventLoop._execute_due`, moved verbatim: the snapshot the venue
published at the target instant, `plan_orders`, the venue's `execute`, `Account.prepare_fill` and
the commit -- the spine, called from here and not changed -- then the mark at the same instant
through the valuation phase."""

from __future__ import annotations

from decimal import Decimal

from vqapr.account.snapshot import AccountState
from vqapr.evidence.artifacts import (
    AccountCommitEvidence,
    DueExecutionEvidence,
    FeedbackEvidence,
    MarkEvidence,
    SimulationFailureKind,
    SimulationStage,
    ValuationEvidence,
)
from vqapr.exchange.execution_table import ExactExecutionSnapshot, exact_execution_snapshot
from vqapr.exchange.listings import ExchangeRulesView
from vqapr.exchange.venue import ExecutionCall
from vqapr.flow.context import (
    CALLBACK_STAGE,
    AcceptedIntent,
    DueExecutionResult,
    FlowContext,
)
from vqapr.flow.run_state import AcceptedRunState, PreparedRunState
from vqapr.flow.valuation import ValuationHandler, _marks_from_execution_snapshot
from vqapr.orders.planning import plan_orders


class ExecutionHandler:
    """One due execution: intent -> orders -> fills -> committed account -> marked account."""

    def __init__(self, context: FlowContext, valuation: ValuationHandler) -> None:
        self._context = context
        self._valuation = valuation

    def execute_due(self, pending: AcceptedIntent) -> DueExecutionResult:
        execution_table = self._context.frozen_run.execution
        if execution_table is None:
            raise RuntimeError("due execution requires frozen execution dataset")
        account_state = self._context.state.current.account
        if not isinstance(account_state, AccountState):
            raise RuntimeError("due execution requires an AccountState root")
        before = account_state.snapshot
        if pending.intent.strategy_id != str(self._context.layer.config.component.component_id):
            raise ValueError(
                "pending intent strategy_id does not match the frozen Strategy component"
            )
        if pending.intent.account_version_seen != before.version:
            raise ValueError(
                "pending intent account_version_seen does not match current AccountSnapshot"
            )
        targets = pending.intent.targets
        target_instruments = tuple(target.instrument_id for target in targets)
        held_instruments = tuple(before.positions)

        def select_snapshot() -> ExactExecutionSnapshot:
            # A held instrument absent from the table is a market fact, not a data-contract
            # breach: it delisted, or it has not listed yet. Canon 6.1 assigns that case to
            # zero-dealt evidence, and the Exchange publishes it as ABSENT. Refusing here would
            # end the run on the first delisting, which in a 3,000-name universe is the first
            # week.
            return exact_execution_snapshot(
                execution_table.table,
                target_at=pending.target.target_at,
                target_instruments=target_instruments,
                held_instruments=held_instruments,
                trade_price=pending.target.trade_price,
                reference_price=self._context.reference_price,
                session=self._context.scan_session,
            )

        with self._context.due_boundary(
            stage=SimulationStage.DUE_SNAPSHOT,
            cutoff=pending.target.target_at,
            owner=execution_table,
            kind=SimulationFailureKind.PRE_COMMIT,
        ):
            snapshot = select_snapshot()
        prices = {row.instrument: row.price for row in snapshot.rows if row.price is not None}
        selected_prices = {
            instrument: price for instrument, price in prices.items() if price is not None
        }
        # A halted row still carries a price, because a halt suspends trading and not valuation.
        # Planning has to know the difference or it funds buys from sales the venue will refuse.
        tradable = {row.instrument: row.is_tradable for row in snapshot.rows}
        # NAV values what can be priced at this instant. A holding with no row carries no
        # selected value, so it contributes nothing here and stays in the account untouched;
        # pricing it from a stale quote would put an invented number in the denominator every
        # later weight is converted against.
        nav = before.cash + sum(
            (
                before.positions[instrument] * selected_prices[instrument]
                for instrument in held_instruments
                if instrument in selected_prices
            ),
            Decimal("0"),
        )
        weights = {target.instrument_id: target.weight for target in targets}
        with self._context.due_boundary(
            stage=SimulationStage.DUE_ORDER_PLANNING,
            cutoff=pending.target.target_at,
            owner=pending.intent,
            kind=SimulationFailureKind.PRE_COMMIT,
        ):
            orders = plan_orders(
                account=before,
                execution_time_nav=nav,
                prices=selected_prices,
                weight_targets=weights,
                cash_target=pending.intent.cash_target,
                budget=pending.intent.budget,
                rules=self._bound_rules(),
                tradable=tradable,
            )
        with self._context.due_boundary(
            stage=SimulationStage.DUE_EXCHANGE_EXECUTION,
            cutoff=pending.target.target_at,
            owner=self._context.frozen_run.exchange,
            kind=SimulationFailureKind.PRE_COMMIT,
        ):
            # The venue is a Component (record `184`): its memory is restored from the root
            # before it is called, the call carries the orders, the book, the venue rows and the
            # rules bound to the project's roster, and what `execute` left in memory is
            # committed with the account commit below.
            self._context.restore_component_memory(self._context.visible_component_memory())
            fills = self._context.exchange.execute(
                ExecutionCall(
                    at=pending.target.target_at,
                    orders=orders,
                    account=before,
                    snapshot=snapshot,
                    rules=self._bound_rules(),
                )
            )
            component_memory = self._context.candidate_component_memory()
        with self._context.due_boundary(
            stage=SimulationStage.DUE_ACCOUNT_PREPARATION,
            cutoff=pending.target.target_at,
            owner=account_state,
            kind=SimulationFailureKind.PRE_COMMIT,
        ):
            prepared_fill = self._context.account.prepare_fill(
                account_state, fills, expected_version=before.version
            )
        commit_evidence = AccountCommitEvidence(
            run_identity=self._context.frozen_run.identity,
            agenda=self._context.layer.agenda,
            occurrence=pending.occurrence,
            cutoff=pending.target.target_at,
            pending=pending,
            target=pending.target,
            fill_convention=execution_table.fill,
            execution_snapshot=snapshot,
            planning_nav=nav,
            planning_cash_target=pending.intent.cash_target,
            planning_budget=pending.intent.budget,
            intended_targets=pending.intent.targets,
            requested_orders=orders,
            dealt_fills=fills,
            before=before,
            committed=prepared_fill.next_snapshot,
            root_version=self._context.state.current.version,
            account_version_before=before.version,
            account_version_committed=prepared_fill.next_snapshot.version,
        )
        with self._context.due_boundary(
            stage=SimulationStage.DUE_ACCOUNT_PREPARATION,
            cutoff=pending.target.target_at,
            owner=account_state,
            kind=SimulationFailureKind.PRE_COMMIT,
        ):
            prepared_commit = self._context.state.prepare_account_commit(
                pending_id=pending.pending_id,
                account=prepared_fill,
                fill=fills,
                evidence=commit_evidence,
                component_memory=component_memory,
                envelope={
                    "run_id": self._context.frozen_run.identity,
                    "producer_id": str(self._context.layer.config.component.component_id),
                    "stage": CALLBACK_STAGE,
                    "event_time": self._context.in_agenda_zone(pending.target.target_at),
                },
            )
        with self._context.due_boundary(
            stage=SimulationStage.DUE_ACCOUNT_COMMIT,
            cutoff=pending.target.target_at,
            owner=account_state,
            kind=SimulationFailureKind.PRE_COMMIT,
        ):
            self._context.account.commit_fill(prepared_fill)
        with self._context.due_boundary(
            stage=SimulationStage.DUE_ACCOUNT_COMMIT,
            cutoff=pending.target.target_at,
            owner=account_state,
            kind=SimulationFailureKind.FAILED_AFTER_COMMIT,
        ):
            committed_root = self._publish_account_commit(prepared_commit)
        with self._context.due_boundary(
            stage=SimulationStage.DUE_VALUATION_SELECTION,
            cutoff=pending.target.target_at,
            owner=self._context.layer.agenda,
            kind=SimulationFailureKind.FAILED_AFTER_COMMIT,
        ):
            selected_marks = _marks_from_execution_snapshot(
                snapshot,
                pending.target.target_at,
                previous=account_state.latest_mark,
                held=prepared_fill.next_snapshot.positions,
            )
        with self._context.due_boundary(
            stage=SimulationStage.DUE_VALUATION_MARK,
            cutoff=pending.target.target_at,
            owner=self._context.layer.agenda,
            kind=SimulationFailureKind.FAILED_AFTER_COMMIT,
        ):
            mark = self._context.valuation_service.mark(prepared_fill.next_snapshot, selected_marks)
        with self._context.due_boundary(
            stage=SimulationStage.DUE_ACCOUNT_MARK,
            cutoff=pending.target.target_at,
            owner=committed_root.account,
            kind=SimulationFailureKind.FAILED_AFTER_COMMIT,
        ):
            prepared_account = self._context.account.prepare_mark(
                prepared_fill,
                mark,
                marked_at=pending.target.target_at,
                observed_at={
                    selected.instrument_id: selected.observed_at for selected in selected_marks
                },
                provenance=ValuationEvidence(
                    run_identity=self._context.frozen_run.identity,
                    agenda=self._context.layer.agenda,
                    occurrence=pending.occurrence,
                    root_version=committed_root.version,
                    cutoff=pending.target.target_at,
                    account=prepared_fill.next_snapshot,
                    marks=mark,
                    account_version=prepared_fill.next_snapshot.version,
                ),
            )
        mark_evidence = MarkEvidence(
            run_identity=self._context.frozen_run.identity,
            agenda=self._context.layer.agenda,
            occurrence=pending.occurrence,
            cutoff=pending.target.target_at,
            selected_marks=selected_marks,
            marks=mark,
            limitations=(),
            account=prepared_account.next_state.snapshot,
            root_version=committed_root.version,
            account_version=prepared_account.next_state.snapshot.version,
        )
        with self._context.due_boundary(
            stage=SimulationStage.DUE_ACCOUNT_MARK,
            cutoff=pending.target.target_at,
            owner=committed_root.account,
            kind=SimulationFailureKind.FAILED_AFTER_COMMIT,
        ):
            committed_mark = prepared_account.next_state.latest_mark
            if committed_mark is None:
                raise RuntimeError("a prepared Account mark must carry the mark it appends")
            prepared_marked = self._context.state.prepare_marked(
                account=prepared_account,
                mark=mark,
                evidence=mark_evidence,
                recorder=self._valuation.measurement_recorder(
                    cutoff=pending.target.target_at,
                    account=prepared_account.next_state.snapshot,
                    mark=committed_mark,
                    selected=selected_marks,
                ),
            )
        with self._context.due_boundary(
            stage=SimulationStage.DUE_ACCOUNT_MARK,
            cutoff=pending.target.target_at,
            owner=committed_root.account,
            kind=SimulationFailureKind.FAILED_AFTER_COMMIT,
        ):
            self._context.account.commit_mark(prepared_account)
        with self._context.due_boundary(
            stage=SimulationStage.DUE_ACCOUNT_MARK,
            cutoff=pending.target.target_at,
            owner=committed_root.account,
            kind=SimulationFailureKind.FAILED_AFTER_COMMIT,
        ):
            marked_root = self._valuation.publish_marked(prepared_marked)
        with self._context.due_boundary(
            stage=SimulationStage.DUE_FEEDBACK_CANDIDATE,
            cutoff=pending.target.target_at,
            owner=pending,
            kind=SimulationFailureKind.FAILED_AFTER_COMMIT,
        ):
            marked_account = marked_root.account
            if marked_account is None:
                raise RuntimeError("a marked root must carry the Account it marked")
            feedback_evidence = FeedbackEvidence(
                run_identity=self._context.frozen_run.identity,
                agenda=self._context.layer.agenda,
                occurrence=pending.occurrence,
                cutoff=pending.target.target_at,
                pending=pending,
                candidates=(fills, mark),
                root_version=marked_root.version,
                account_version=marked_account.snapshot.version,
            )
        # Monitoring judges the committed, marked book right here (record `148`): there is no
        # later occurrence for it, and nothing later could see more than the fill instant did.
        monitoring = self._valuation.monitor_after_commit(pending)
        due_evidence = DueExecutionEvidence(commit_evidence, mark_evidence, feedback_evidence)
        with self._context.due_boundary(
            stage=SimulationStage.DUE_FEEDBACK_PUBLICATION,
            cutoff=pending.target.target_at,
            owner=feedback_evidence,
            kind=SimulationFailureKind.FAILED_AFTER_COMMIT,
        ):
            root = self._context.state.publish_feedback(
                self._context.state.prepare_feedback((due_evidence,), evidence=feedback_evidence)
            )
        assert root.account is not None
        return DueExecutionResult(
            pending.pending_id, root.account.snapshot.version, due_evidence, monitoring
        )

    def _publish_account_commit(self, prepared: PreparedRunState) -> AcceptedRunState:
        root = self._context.state.publish_account_commit(prepared)
        if root.account != self._context.account.state:
            raise RuntimeError("Account commit root does not mirror Account authority")
        return root

    def _bound_rules(self) -> ExchangeRulesView:
        """The rules order planning and the venue consume, with the roster bound if a run has one.

        One view, built here and handed to both `plan_orders` and the venue's `ExecutionCall`
        (record `184`). Until then the venue read its OWN rules inside `execute` and the roster
        had to be planted on it with `object.__setattr__`; a testbed journey had found every fill
        of a 599-fill run recording `kind: None` beside a correctly registered roster because the
        bound view never reached the venue.
        """
        rules = self._context.exchange.rules
        if self._context.registry is None:
            return rules
        return rules.with_registry(self._context.registry)
