"""The callback phase: the strategy decides, and its decision becomes an accepted intent.

Record `147`. What was `StrategyEventLoop._dispatch_callback` and its helpers, moved verbatim: the
visible model state is restored, the window read, `decide` called, the intent stamped and its
authority checked, the package's own rows recorded, and the accepted intent published."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
from io import BytesIO
from typing import NoReturn
from uuid import NAMESPACE_URL, UUID, uuid5

from vqapr.authoring import EconomicAccountView, Hold, Rebalance
from vqapr.authoring.context import StrategyModelContext
from vqapr.authoring.history import AccountHistory
from vqapr.authoring.records import InvocationRecorder, TableSpec
from vqapr.constraints.evaluation import (
    build_account_view,
    merged_constraint_bounds,
    project_constraints,
)
from vqapr.data.windows import ModelWindow
from vqapr.domain.account_state import AccountSnapshot, AccountState
from vqapr.domain.agendas import OperationOccurrence
from vqapr.domain.errors import VqaprError
from vqapr.domain.identifiers import ModelStateRef
from vqapr.domain.model_state import prepare_model_state
from vqapr.domain.values import ModelMemory, normalize_memory
from vqapr.exchange.conventions import ExecutionHorizon
from vqapr.exchange.execution_table import ExecutionTable
from vqapr.flow.engine.artifacts import (
    CallbackEvidence,
    SimulationFailure,
    SimulationFailureKind,
    SimulationStage,
)
from vqapr.flow.engine.run_state import (
    LifecycleKind,
    LifecycleTrace,
    PreparedRunState,
)
from vqapr.flow.strategy.context import (
    _ACCOUNT_IDENTITY,
    _VALUATION_NAMESPACE,
    CALLBACK_STAGE,
    DEFAULT_TABLE_PREFIX,
    DEFAULT_TABLES,
    AcceptedIntent,
    FlowContext,
    OccurrenceTrace,
    PendingValuation,
    _raise_callback_return_type,
    _shadows_package_table,
)
from vqapr.portfolio.intents import (
    EconomicPortfolioIntent,
    IntentSourceRef,
    PortfolioTarget,
    validate_economic_intent,
)


class CallbackHandler:
    """One strategy callback, from the model's visible state to a published, accepted intent."""

    def __init__(self, context: FlowContext) -> None:
        self._context = context

    def dispatch(self, occurrence: OperationOccurrence) -> OccurrenceTrace:
        with self._context.guard(
            SimulationStage.CALLBACK_STATE,
            occurrence.evaluation_time,
            owner=self._context.layer.config,
        ):
            current_ref, before, payload_before = self._visible_callback_state()
        previous_recorder = self._context.strategy.recorder
        # Every Component's memory is restored before its callback and what the callback left
        # is committed with the publication (record `181`). The constraints' goes in the same
        # root as the Strategy's, so a rule that counts commits its count with the decision.
        # Read before the try: a failure anywhere inside restores it.
        component_before = self._context.visible_component_memory()
        try:
            with self._context.guard(
                SimulationStage.CALLBACK_STATE,
                occurrence.evaluation_time,
                owner=self._context.layer.config,
            ):
                self._restore_callback_state(before, payload_before)
            with self._context.guard(
                SimulationStage.CALLBACK_WINDOW,
                occurrence.evaluation_time,
                owner=self._context.layer.requirements,
            ):
                window = self._strategy_window(occurrence)
            state_account = self._context.state.current.account
            if state_account is None:
                with self._context.guard(
                    SimulationStage.CALLBACK_STATE,
                    occurrence.evaluation_time,
                    owner=self._context.layer.config,
                ):
                    self._raise_callback_account_state_error()
            account = state_account.snapshot
            with self._callback_intent_boundary(occurrence, self._context.layer.config):
                recorder = self._callback_recorder(occurrence)
            with self._context.guard(
                SimulationStage.CALLBACK_PUBLICATION,
                occurrence.evaluation_time,
                owner=recorder,
            ):
                self._set_callback_recorder(recorder)
            projected = ()
            component_candidate: dict[str, ModelMemory] | None = None
            if self._context.constraints:
                with self._context.guard(
                    SimulationStage.CALLBACK_STATE,
                    occurrence.evaluation_time,
                    owner=self._context.layer.constraints,
                ):
                    self._context.restore_component_memory(component_before)
                with self._context.guard(
                    SimulationStage.CALLBACK_WINDOW,
                    occurrence.evaluation_time,
                    owner=self._context.layer.constraint_requirements,
                ):
                    constraint_window = self._constraint_window(occurrence)
                projections = []
                for constraint in self._context.constraints:
                    with self._callback_intent_boundary(occurrence, constraint):
                        projections.append(project_constraints((constraint,), constraint_window)[0])
                projected = tuple(projections)
                with self._context.guard(
                    SimulationStage.CALLBACK_STATE,
                    occurrence.evaluation_time,
                    owner=self._context.layer.constraints,
                ):
                    component_candidate = self._context.candidate_component_memory()
            with self._callback_intent_boundary(occurrence, projected):
                constraint_bounds = merged_constraint_bounds(projected)
            with self._callback_intent_boundary(
                occurrence, self._context.layer.config, data_owner=self._context.layer.requirements
            ):
                result = self._context.strategy.decide(
                    StrategyModelContext(
                        occurrence=occurrence,
                        window=window,
                        account=self._callback_account_view(state_account),
                        reads=self._context.strategy.inputs(),
                        constraint_bounds=constraint_bounds,
                        account_history=self._account_history(),
                    )
                )
            # The envelope, stamped here rather than asked of the callback. Every field it
            # adds is one the Flow already had to derive in order to check the author's copy of
            # it, so this replaces a comparison rather than adding a step. Record `125`.
            #
            # The decision is kept beside the intent stamped from it, because a Constraint judges
            # the decision: the five fields stamping adds are facts about the run, and a rule
            # about weights has no business reading any of them.
            if not isinstance(result, (Hold, Rebalance)):
                with self._callback_intent_boundary(occurrence, self._context.layer.config):
                    _raise_callback_return_type(result)
            if isinstance(result, Rebalance):
                with self._callback_intent_boundary(occurrence, self._context.layer.config):
                    result = self._stamp_intent(result, occurrence, account, window)

            pending_valuation: PendingValuation | None = None
            if isinstance(result, Hold):
                accepted: Hold | AcceptedIntent = result
                # A Hold still reaches the execution instant, because the book is still
                # worth something there and the venue still publishes prices for it.
                with self._callback_intent_boundary(
                    occurrence, self._context.frozen_run.execution
                ):
                    pending_valuation = self._accept_valuation(occurrence)
            else:
                with self._callback_intent_boundary(occurrence, result):
                    intent = validate_economic_intent(result)
                with self._callback_intent_boundary(occurrence, intent):
                    self._validate_intent_authority(intent, account, window)
                # No constraint check here, deliberately. Construction had the projected bounds
                # and did its best inside them; whether the book actually breached a limit is a
                # question about the committed account, and monitoring asks it (PRD 7.1,
                # architecture 5.7). Judging the decision here also could not see the breach that
                # matters most -- rounding a weight into whole shares moves it, and no fills exist
                # yet.
                with self._callback_intent_boundary(
                    occurrence, self._context.frozen_run.execution
                ):
                    accepted = self._accept_intent(intent, occurrence)
            # The package's own account of this occurrence, written without the Strategy asking.
            # Both values are package-computed, so recording them is a statement of what the run
            # did rather than a claim the Strategy made.
            self._record_defaults(recorder, accepted, account)
            with self._context.guard(
                SimulationStage.CALLBACK_STATE,
                occurrence.evaluation_time,
                owner=self._context.layer.config,
            ):
                candidate, payload_candidate, committed_ref = self._candidate_callback_state(
                    before, payload_before
                )
            with self._callback_intent_boundary(occurrence, accepted):
                evidence, lifecycle = self._callback_evidence(
                    occurrence, account, current_ref, committed_ref, window, accepted, projected
                )
            with self._context.guard(
                SimulationStage.CALLBACK_PUBLICATION,
                occurrence.evaluation_time,
                owner=evidence,
            ):
                prepared = self._prepare_callback_publication(
                    candidate,
                    payload_candidate,
                    lifecycle,
                    recorder,
                    accepted,
                    pending_valuation,
                    component_memory=component_candidate,
                )
            with self._context.guard(
                SimulationStage.CALLBACK_PUBLICATION,
                occurrence.evaluation_time,
                owner=prepared,
            ):
                root = self._context.state.publish(prepared)
        except Exception:
            with self._context.guard(
                SimulationStage.CALLBACK_STATE,
                occurrence.evaluation_time,
                owner=self._context.layer.config,
            ):
                self._restore_callback_state(before, payload_before)
                self._context.restore_component_memory(component_before)
            raise
        finally:
            self._context.strategy.recorder = previous_recorder
        return OccurrenceTrace(occurrence, result, root)

    def load_visible_state(self) -> None:
        """Load every component's visible memory before any callback mutation: the Strategy's
        pair, and each constraint's (record `181`)."""
        current_ref = self._context.state.current.current_model_state_ref
        if current_ref is None:
            raise RuntimeError("run state has no current Strategy root")
        self._context.strategy.memory = self._context.state.load_model_state(current_ref)
        self._context.strategy.load_payload(BytesIO(self._context.state.load_payload(current_ref)))
        self._context.restore_component_memory(self._context.visible_component_memory())

    @contextmanager
    def _callback_intent_boundary(
        self,
        occurrence: OperationOccurrence,
        owner: object,
        *,
        data_owner: object | None = None,
    ) -> Iterator[None]:
        """Keep callback data-access failures out of the intent boundary.

        A typed refusal raised inside this boundary is the framework refusing a READ the callback
        made -- a source that cannot be scanned, a field the dataset does not expose, a
        requirement the model never declared -- so it is reported at the window stage against
        the layer's requirements. Until record `171` this branched on the refusal's `family`, and
        every family that could reach here was `DATA`: the author's own code raises bare
        exceptions, which the two clauses below own, and no other typed refusal is raised
        between a window and a published intent.
        """
        try:
            yield
        except SimulationFailure:
            raise
        except VqaprError as error:
            raise self._context.failure(
                stage=SimulationStage.CALLBACK_WINDOW,
                cutoff=occurrence.evaluation_time,
                owner=self._context.layer.requirements,
                cause=error,
                kind=SimulationFailureKind.PRE_COMMIT,
            ) from error
        except OSError as error:
            raise self._context.failure(
                stage=SimulationStage.CALLBACK_WINDOW,
                cutoff=occurrence.evaluation_time,
                owner=owner if data_owner is None else data_owner,
                cause=error,
                kind=SimulationFailureKind.PRE_COMMIT,
            ) from error
        except Exception as error:
            raise self._context.failure(
                stage=SimulationStage.CALLBACK_INTENT,
                cutoff=occurrence.evaluation_time,
                owner=owner,
                cause=error,
                kind=SimulationFailureKind.PRE_COMMIT,
            ) from error

    def _prepare_callback_publication(
        self,
        memory: ModelMemory,
        payload: bytes,
        lifecycle: LifecycleTrace,
        recorder: InvocationRecorder,
        accepted: Hold | AcceptedIntent,
        pending_valuation: PendingValuation | None = None,
        *,
        component_memory: Mapping[str, ModelMemory] | None = None,
    ) -> PreparedRunState:
        if isinstance(accepted, Hold):
            if pending_valuation is None:
                # Nothing to take: leave whatever the root already had pending untouched.
                return self._context.state.prepare_callback(
                    memory,
                    payload,
                    lifecycle=lifecycle,
                    recorder=recorder,
                    component_memory=component_memory,
                )
            # A Hold still carries a pending identity when an execution instant remains,
            # so the occurrence reaches the venue's prices and values the book there.
            return self._context.state.prepare_callback(
                memory,
                payload,
                lifecycle=lifecycle,
                recorder=recorder,
                pending_accepted_intent=pending_valuation,
                component_memory=component_memory,
            )
        return self._context.state.prepare_callback(
            memory,
            payload,
            lifecycle=lifecycle,
            recorder=recorder,
            pending_accepted_intent=accepted,
            component_memory=component_memory,
        )

    def _restore_callback_state(self, memory: ModelMemory, payload: bytes) -> None:
        self._context.strategy.memory = memory
        self._context.strategy.load_payload(BytesIO(payload))

    def _record_defaults(
        self,
        recorder: InvocationRecorder,
        accepted: object,
        account: AccountSnapshot,
    ) -> None:
        """Write the package-owned tables for one occurrence.

        A declining occurrence still records its account state: that the Strategy chose not to act
        is itself part of what a later run needs to reuse this one.
        """
        intent = getattr(accepted, "intent", accepted)
        for target in getattr(intent, "targets", ()):
            weight = getattr(target, "weight", None)
            if weight is None:
                continue
            recorder.append(
                f"{DEFAULT_TABLE_PREFIX}weight",
                {"instrument": target.instrument_id, "weight": str(weight)},
            )
        # `vqapr.account` carries measurements only, and this path contributes one just in the
        # case where nobody else did: every fill records the NAV it was marked at (record `148`,
        # `ValuationHandler.measurement_recorder`), so this is the mark nothing recorded -- an
        # opening mark, or one a caller committed outside the flow. 056 measured what dropping
        # the fallback cost under the old sparse valuation clock -- 8 of 10 measurements lost --
        # so the row survives for exactly that case.
        #
        # What is gone is the row written when a valuation ALREADY recorded this measurement.
        # That one carried `nav=None` and competed with a real value in the same table, which is
        # the null-pairing 056 measured as HML 0.9726 -> 0.6877. A row with nothing to add is now
        # simply not written here; the decision-time facts it also carried moved to their own
        # table below, where no measurement claim competes with them. See `docs/issues/archive/010`.
        account_state = self._context.state.current.account
        mark = None if account_state is None else account_state.latest_mark
        marked_at = getattr(mark, "marked_at", None)
        if (
            mark is not None
            and marked_at is not None
            and marked_at not in self._context.recorded_measurements
        ):
            prices = {m.instrument_id: m for m in mark.marks.marks}
            observed = mark.observed_at_by_instrument or {}
            recorder.append(
                f"{DEFAULT_TABLE_PREFIX}account",
                {
                    "instrument": _ACCOUNT_IDENTITY,
                    "cash": account.cash,
                    "nav": mark.nav,
                    "quantity": None,
                    "price": None,
                    # When the nav was MEASURED, which is not when this row was written. Dating
                    # the series by the occurrence instead puts every value one commit late;
                    # measured once, that mislabelling took a correlation from 0.93 to 0.02.
                    "observed_at": marked_at,
                    "account_version": account.version,
                },
            )
            self._context.recorded_measurements.add(marked_at)
            positions = sorted(account.positions) if self._context.record_account_positions else ()
            for instrument in positions:
                valued = prices.get(instrument)
                recorder.append(
                    f"{DEFAULT_TABLE_PREFIX}account",
                    {
                        "instrument": instrument,
                        "cash": None,
                        "nav": None,
                        "quantity": account.positions[instrument],
                        "price": None if valued is None else valued.price,
                        "observed_at": observed.get(instrument),
                        "account_version": account.version,
                    },
                )

        # Nothing else is written here. A `vqapr.decision_account` table briefly stood at this
        # point, holding the cash and positions a callback saw before deciding, on the argument
        # that this is a different fact from what the book was worth.
        #
        # Measured, it was not a different fact. Matched on `account_version`, its rows were
        # IDENTICAL to `vqapr.account`'s on every version the two shared -- the same series offset
        # by one commit, because a callback reports the account it saw and a valuation reports the
        # account it valued. The only genuinely unique row was version 0, the initial account,
        # which `FrozenRun.initial_account_snapshot` already carries. Nothing read it.
        #
        # Removed under this package's own rule: machinery whose only user is its own test is not
        # a feature. If a decision-time account series is ever wanted, it should be designed with
        # the consumer that wants it, which will also say whether it needs to be a table at all.

    @staticmethod
    def _callback_account_view(state: AccountState) -> EconomicAccountView:
        """The committed Account as the Strategy sees it: the snapshot, valued at its last mark.

        A callback fires before the occurrence it decides for is executed or valued, so the
        marks it can see are the previous valuation's -- committed, and therefore point-in-time.
        The same builder a monitoring Constraint's view comes from (record `130`), so `nav` and
        `weights()` mean one thing on both sides of a decision. Before the first valuation there
        is no mark, and the view says so with `nav=None` rather than a fabricated zero.
        """
        mark = state.latest_mark
        if mark is not None and mark.marked_at is not None:
            return build_account_view(state.snapshot, mark.marks, mark.marked_at)
        snapshot = state.snapshot
        return EconomicAccountView(
            cash=snapshot.cash,
            positions=dict(snapshot.positions),
            nav=None,
            nav_observed_at=None,
        )

    def _set_callback_recorder(self, recorder: InvocationRecorder | None) -> None:
        self._context.strategy.recorder = recorder

    def _visible_callback_state(self) -> tuple[ModelStateRef, ModelMemory, bytes]:
        current_ref = self._context.state.current.current_model_state_ref
        if current_ref is None:
            raise RuntimeError("callback requires a current Strategy root")
        return (
            current_ref,
            self._context.state.load_model_state(current_ref),
            self._context.state.load_payload(current_ref),
        )

    @staticmethod
    def _raise_callback_account_state_error() -> NoReturn:
        raise RuntimeError("callback requires an AccountState root")

    def _strategy_window(self, occurrence: OperationOccurrence) -> ModelWindow:
        return self._context.strategy_window_for_occurrence(occurrence)

    def _constraint_window(self, occurrence: OperationOccurrence) -> ModelWindow:
        return self._context.constraint_window_for_occurrence(occurrence)

    def _callback_recorder(self, occurrence: OperationOccurrence) -> InvocationRecorder:
        tables = self._context.strategy.tables()
        if not isinstance(tables, tuple) or not all(
            isinstance(table, TableSpec) for table in tables
        ):
            raise TypeError("StrategyModel.tables must return a tuple of TableSpec")
        declared = {table.table_id for table in tables}
        shadowed = sorted(name for name in declared if _shadows_package_table(name))
        if shadowed:
            # The prefix is reserved in canon so a Strategy cannot collide with or shadow a
            # package record. It fires while the recorder is built, before any row is written.
            raise ValueError(
                f"table ids beginning with {DEFAULT_TABLE_PREFIX!r} are package-owned: {shadowed}"
            )
        return InvocationRecorder(
            tables + DEFAULT_TABLES,
            run_id=self._context.frozen_run.identity,
            producer_id=str(self._context.layer.config.component.component_id),
            stage=CALLBACK_STAGE,
            event_time=occurrence.evaluation_time,
        )

    def _candidate_callback_state(
        self, before: ModelMemory, payload_before: bytes
    ) -> tuple[ModelMemory, bytes, ModelStateRef]:
        candidate = normalize_memory(self._context.strategy.memory)
        payload_candidate = BytesIO()
        self._context.strategy.save_payload(payload_candidate)
        payload = payload_candidate.getvalue()
        committed_ref = prepare_model_state(candidate, payload).ref
        self._validate_candidate_payload(candidate, payload, before, payload_before)
        return candidate, payload, committed_ref

    def _callback_evidence(
        self,
        occurrence: OperationOccurrence,
        account: AccountSnapshot,
        current_ref: ModelStateRef,
        committed_ref: ModelStateRef,
        window: ModelWindow,
        accepted: Hold | AcceptedIntent,
        projected: tuple[object, ...],
    ) -> tuple[CallbackEvidence, LifecycleTrace]:
        evidence = CallbackEvidence(
            run_identity=self._context.frozen_run.identity,
            strategy=self._context.layer.config,
            agenda=self._context.layer.agenda,
            occurrence=occurrence,
            cutoff=occurrence.evaluation_time,
            root_version=self._context.state.current.version,
            account=account,
            current_model_state_ref=current_ref,
            committed_model_state_ref=committed_ref,
            strategy_accesses=window.accesses,
            actual_source_refs=self._callback_actual_source_refs(occurrence, window),
            decision=accepted,
            pending=None if isinstance(accepted, Hold) else accepted,
            # The projections only. What a callback's evidence carries about constraints is
            # what the rules permitted at that instant, not a verdict on the decision -- there is
            # no verdict at this point, by design (PRD 7.1). The verdict is monitoring's.
            constraints=projected,
        )
        lifecycle = LifecycleTrace(
            LifecycleKind.NO_DECISION
            if isinstance(accepted, Hold)
            else LifecycleKind.ACCEPTED_INTENT,
            evidence,
        )
        return evidence, lifecycle

    def _callback_actual_source_refs(
        self, occurrence: OperationOccurrence, window: ModelWindow
    ) -> tuple[IntentSourceRef, ...]:
        with self._context.guard(
            SimulationStage.CALLBACK_WINDOW,
            occurrence.evaluation_time,
            owner=self._context.layer.requirements,
        ):
            return self._actual_source_refs(window)

    def _validate_candidate_payload(
        self,
        candidate: ModelMemory,
        payload_candidate: bytes,
        before: ModelMemory,
        payload_before: bytes,
    ) -> None:
        """Prove the live Strategy can load and reproduce its candidate before root swap."""
        try:
            self._context.strategy.memory = normalize_memory(candidate)
            self._context.strategy.load_payload(BytesIO(payload_candidate))
            round_trip = BytesIO()
            self._context.strategy.save_payload(round_trip)
            if round_trip.getvalue() != payload_candidate:
                raise ValueError(
                    "StrategyModel payload load/save round-trip changed candidate bytes"
                )
            self._context.strategy.memory = normalize_memory(candidate)
        except Exception:
            self._context.strategy.memory = before
            self._context.strategy.load_payload(BytesIO(payload_before))
            raise

    def _stamp_intent(
        self,
        decision: Rebalance,
        occurrence: OperationOccurrence,
        account: AccountSnapshot,
        window: ModelWindow,
    ) -> EconomicPortfolioIntent:
        """Turn one economic decision into the intent the Flow accepts.

        Five of an intent's eight fields are facts about the RUN, not about the decision: which
        Strategy this is, what it read, which account version it saw, which model state was
        visible, and the intent's own identity. The callback cannot know four of them correctly
        and can only copy the fifth, so asking for them made every author restate what the Flow
        already knew -- and made a wrong restatement a possible outcome.

        The id is `uuid5` over `(strategy_id, occurrence_id)` rather than random, so the same
        decision in the same occurrence of the same run mints the same identity. A replayed run
        produces byte-identical intents, which is what makes a record comparable to itself.
        """
        strategy_id = str(self._context.layer.config.component.component_id)
        targets = tuple(
            PortfolioTarget(instrument, weight=weight)
            for instrument, weight in sorted(decision.target_weights.items())
        )
        return EconomicPortfolioIntent(
            uuid5(NAMESPACE_URL, f"{strategy_id}/{occurrence.occurrence_id}"),
            strategy_id,
            targets,
            Decimal(decision.cash_weight),
            decision.budget,
            self._actual_source_refs(window),
            account.version,
            self._context.state.current.current_model_state_ref,
        )

    def _validate_intent_authority(
        self,
        intent: EconomicPortfolioIntent,
        account: AccountSnapshot,
        window: ModelWindow,
    ) -> None:
        """The one thing left to check: that the author named instruments this run trades.

        The four comparisons that stood here -- strategy id, model state ref, account version
        seen, source refs -- each read a field the callback supplied and compared it against a
        value this class derived. Record `125` stamps those fields from the derived values
        instead, so there is nothing left to disagree with. What survives is a real check on a
        real authored value: `target_weights` is the author's, and a name outside the frozen
        universe is an authoring error the Flow must refuse rather than execute.
        """
        outside_universe = tuple(
            target.instrument_id
            for target in intent.targets
            if target.instrument_id not in self._context.frozen_run.instrument_set
        )
        if outside_universe:
            raise ValueError(
                f"intent targets are outside the frozen instrument universe: {outside_universe}"
            )

    def _actual_source_refs(self, window: ModelWindow) -> tuple[IntentSourceRef, ...]:
        datasets = {
            str(dataset.dataset_id): dataset for dataset in self._context.frozen_run.datasets
        }
        sources = {str(source.source_id): source for source in self._context.frozen_run.sources}
        actual: dict[str, str] = {}
        for access in window.accesses:
            dataset = datasets.get(str(access.dataset_id))
            if dataset is None:
                raise ValueError("ModelWindow read a dataset absent from the FrozenRun")
            source_id = str(dataset.source)
            if source_id not in sources or access.source_id != source_id:
                raise ValueError(
                    "FrozenRun dataset source is absent from frozen source declarations"
                )
            previous = actual.setdefault(source_id, access.source_digest)
            if previous != access.source_digest:
                raise RuntimeError("one callback observed multiple byte digests for one source")
        return tuple(IntentSourceRef(source_id, digest) for source_id, digest in actual.items())

    def execution_horizon(self, execution_table: ExecutionTable) -> ExecutionHorizon:
        """Read the run's candidate execution instants once, not once per callback.

        Built lazily so constructing a StrategyEventLoop still opens no physical source. The lower
        bound is the frozen run start, which no decision can precede.
        """
        horizon = self._context.horizon
        if horizon is None:
            frozen = self._context.frozen_run
            if frozen.end is None:
                raise ValueError("an execution horizon requires a frozen run end")
            start = frozen.start
            if start is None:
                raise ValueError("an execution horizon requires a frozen run start")
            horizon = execution_table.build_horizon(
                start_time=start,
                end_time=frozen.end,
                # The run owns a scan session; the horizon is the one query that reads every
                # distinct instant in the execution table, so it is the last one that should be
                # opening a connection of its own.
                session=self._context.scan_session,
            )
            self._context.horizon = horizon
        return horizon

    def _accept_valuation(self, occurrence: OperationOccurrence) -> PendingValuation | None:
        """Bind a no-order occurrence to the execution instant it would have traded at.

        Returns None when this occurrence must not take one, in which case the root's existing
        pending is left exactly as it was:

        - **An accepted intent is already pending.** It is waiting for its own due execution, and
          that execution will value the book. Replacing it here would silently discard a decision
          the Strategy already made and a fill that was going to happen.
        - **The run declared no execution authority.** A research run that only exercises
          callbacks never values against venue prices, so a Hold in it stays what it was.
        - **No execution instant remains in the horizon.** There is nothing left to value
          against, and a run ending on a Hold must still finalize.
        """
        if self._context.state.current.pending_accepted_intent is not None:
            return None
        frozen = self._context.frozen_run
        execution_table = frozen.execution
        if execution_table is None or frozen.end is None or frozen.start is None:
            # A run declared without execution authority never values against venue prices. That
            # is a legitimate configuration -- a research run that only exercises callbacks -- and
            # a Hold in it stays exactly what it was.
            return None
        target = execution_table.select_target(
            decision_time=occurrence.evaluation_time,
            end_time=frozen.end,
            horizon=self.execution_horizon(execution_table),
        )
        if target is None:
            return None
        return PendingValuation(
            occurrence=occurrence,
            decision_time=occurrence.evaluation_time,
            target=target,
            valuation_id=self._pending_valuation_key(
                self._context.frozen_run.identity, CALLBACK_STAGE, occurrence.evaluation_time
            ),
        )

    @staticmethod
    def _pending_valuation_key(identity: object, role: str, instant: datetime) -> UUID:
        """The pending identity for a valuation, discriminated by role as well as instant.

        The role belongs in the key. Without it, occurrences differing only in role mint the SAME
        uuid5 at one instant in one run, and `pending_id` is the token that proves a completion
        matches its own preparation (`run_state.py:346-348`, `:434-436`). Two identical ids would
        degrade that invariant from a proof to a coincidence.
        """
        return uuid5(_VALUATION_NAMESPACE, f"{identity}|{role}|{instant.isoformat()}")

    def _accept_intent(
        self, intent: EconomicPortfolioIntent, occurrence: OperationOccurrence
    ) -> AcceptedIntent:
        execution_table = self._context.frozen_run.execution
        if execution_table is None or self._context.frozen_run.end is None:
            raise ValueError("an accepted intent requires frozen execution dataset and run end")
        target = execution_table.select_target(
            decision_time=occurrence.evaluation_time,
            end_time=self._context.frozen_run.end,
            horizon=self.execution_horizon(execution_table),
        )
        if target is None:
            raise ValueError("no exact execution target exists within the run horizon")
        accepted = AcceptedIntent(
            intent=intent,
            occurrence=occurrence,
            decision_time=occurrence.evaluation_time,
            target=target,
        )
        if target.dataset_id != execution_table.dataset_id:
            raise ValueError(
                "selected target execution dataset does not match the frozen execution table"
            )
        return accepted

    def _account_history(self) -> AccountHistory:
        """The Strategy's declared window onto marks the Account already committed.

        Bounded by the declaration, so this copies the declared window rather than the run so
        far. A Strategy that declared nothing gets an empty projection that refuses every read.
        """
        state = self._context.state.current.account
        marks = () if state is None else state.mark_history
        return AccountHistory(marks, self._context.account_history_declaration)
