"""The EXECUTE stage of a market-clock instant: an accepted intent becomes orders, fills and a
committed account -- and, after VALUATION and COMPLIANCE have run on that account, the
evidence that closes the fill.

Record `147` moved the spine here verbatim from `StrategyEventLoop._execute_due`; record `207`
split it in two around the stages design §3.1 puts between them. `fill` is EXECUTE: the snapshot
the venue published at the instant, the instrument gate, `plan_orders`, the venue's `execute`,
`Account.prepare_fill` and the commit. `close` is the fill's epilogue, run once the book has
been valued (`ValuationHandler.mark_fill`) and judged (`monitor_at`): the feedback evidence and
its publication. The loop's `_handle_market` is the one place the order is written down."""

from __future__ import annotations

from decimal import Decimal

from vqapr.domain.instruments import InstrumentRoster, require_declared
from vqapr.domain.ledger import fill_entries
from vqapr.exchange.execution_table import ExactExecutionSnapshot, exact_execution_snapshot
from vqapr.exchange.listings import ExchangeRulesView
from vqapr.exchange.planning import plan_orders
from vqapr.exchange.venue import ExecutionCall
from vqapr.flow.engine.artifacts import (
    AccountCommitEvidence,
    DueExecutionEvidence,
    FeedbackEvidence,
    MarkEvidence,
    SimulationFailureKind,
    SimulationStage,
)
from vqapr.flow.engine.run_state import AcceptedRunState, PreparedRunState
from vqapr.flow.strategy.context import (
    CALLBACK_STAGE,
    AcceptedIntent,
    DueExecutionResult,
    Filled,
    FlowContext,
    Marked,
    MonitoringResult,
)


class ExecutionHandler:
    """EXECUTE: intent -> orders -> fills -> committed account; then `close` once it is marked."""

    def __init__(self, context: FlowContext) -> None:
        self._context = context

    def fill(self, pending: AcceptedIntent) -> Filled:
        """Fill the pending intent at its target instant and commit the account (EXECUTE)."""
        execution_table = self._context.frozen_run.execution
        if execution_table is None:
            raise RuntimeError("due execution requires frozen execution dataset")
        account_state = self._context.state.current.account
        if account_state is None:
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
        # Orders are a subset of the declared instruments (design §6.2), checked on everything
        # the planner may order -- the targets and the holdings -- before planning charges through
        # the roster and stops at the first unknown id. Every undeclared id, in one refusal.
        with self._context.due_boundary(
            stage=SimulationStage.DUE_INSTRUMENT_DECLARATION,
            cutoff=pending.target.target_at,
            owner=self._context.frozen_run.exchange,
            kind=SimulationFailureKind.PRE_COMMIT,
        ):
            require_declared(
                self._context.registry,
                (*target_instruments, *held_instruments),
                exchange_id=self._context.exchange.rules.exchange_id,
            )
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
            # before it is called, the call carries the orders, the book, the venue rows, the
            # instrument dictionary (design §6.1) and the rules bound to it, and what `execute`
            # left in memory is committed with the account commit below.
            self._context.restore_component_memory(self._context.visible_component_memory())
            fills = self._context.exchange.execute(
                ExecutionCall(
                    at=pending.target.target_at,
                    orders=orders,
                    account=before,
                    snapshot=snapshot,
                    instruments=self._context.registry or InstrumentRoster({}),
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
            # The producer's entries, the ledger's permission (design §5.2, record `211`): the
            # venue said what each fill did; the Account asks only whether they may go after
            # this state and whether what results is an account.
            prepared_fill = self._context.account.append(
                account_state,
                fill_entries(pending.target.target_at, fills),
                expected_version=before.version,
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
            prepared_commit = self._context.state.prepare_account(
                prepared_fill,
                pending_id=pending.pending_id,
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
            self._context.account.commit_append(prepared_fill)
        with self._context.due_boundary(
            stage=SimulationStage.DUE_ACCOUNT_COMMIT,
            cutoff=pending.target.target_at,
            owner=account_state,
            kind=SimulationFailureKind.FAILED_AFTER_COMMIT,
        ):
            committed_root = self._publish_account_commit(prepared_commit)
        return Filled(
            pending=pending,
            snapshot=snapshot,
            fills=fills,
            prepared_fill=prepared_fill,
            previous_mark=account_state.latest_mark,
            commit_evidence=commit_evidence,
            committed_root=committed_root,
        )

    def close(
        self, filled: Filled, marked: Marked, monitoring: MonitoringResult | None
    ) -> DueExecutionResult:
        """The fill's epilogue, once VALUATION and COMPLIANCE have run: publish the feedback."""
        pending = filled.pending
        if not isinstance(marked.evidence, MarkEvidence):
            raise RuntimeError("a fill is closed with the mark evidence its valuation produced")
        with self._context.due_boundary(
            stage=SimulationStage.DUE_FEEDBACK_CANDIDATE,
            cutoff=pending.target.target_at,
            owner=pending,
            kind=SimulationFailureKind.FAILED_AFTER_COMMIT,
        ):
            marked_account = marked.root.account
            if marked_account is None:
                raise RuntimeError("a marked root must carry the Account it marked")
            feedback_evidence = FeedbackEvidence(
                run_identity=self._context.frozen_run.identity,
                agenda=self._context.layer.agenda,
                occurrence=pending.occurrence,
                cutoff=pending.target.target_at,
                pending=pending,
                candidates=(filled.fills, marked.mark),
                root_version=marked.root.version,
                account_version=marked_account.snapshot.version,
            )
        due_evidence = DueExecutionEvidence(
            filled.commit_evidence, marked.evidence, feedback_evidence
        )
        with self._context.due_boundary(
            stage=SimulationStage.DUE_FEEDBACK_PUBLICATION,
            cutoff=pending.target.target_at,
            owner=feedback_evidence,
            kind=SimulationFailureKind.FAILED_AFTER_COMMIT,
        ):
            root = self._context.state.publish_infallible(
                self._context.state.prepare_feedback((due_evidence,), evidence=feedback_evidence)
            )
        assert root.account is not None
        return DueExecutionResult(
            pending.pending_id, root.account.snapshot.version, due_evidence, monitoring
        )

    def _publish_account_commit(self, prepared: PreparedRunState) -> AcceptedRunState:
        root = self._context.state.publish_infallible(prepared)
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
