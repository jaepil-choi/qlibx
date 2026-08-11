"""Orchestration for PIT-safe direct Strategy research."""

from dataclasses import dataclass

from pydantic import Field

from qlibx.contracts import (
    StrategyArtifactRequirement,
    StrategyComputationError,
    StrategyDraft,
    StrategyInvocation,
    StrategyOperation,
    StrategyPathDependenceError,
    StrategyResult,
    validate_strategy_draft_path_dependence,
)
from qlibx.data import DataSnapshotError, ObservationStore, RegistrySnapshot, RequirementResolver
from qlibx.errors import OperationError, OperationOutcome, OutcomeStatus
from qlibx.evidence import ArtifactEnvelope, DependencyEdge, LocalArtifactBackend
from qlibx.flow.artifact_inputs import (
    StrategyArtifactContractRegistry,
    StrategyArtifactResolver,
)
from qlibx.flow.failures import (
    build_operation_error,
    publish_failed_errors,
    publish_failed_outcome,
)
from qlibx.flow.strategy_results import (
    STRATEGY_RESULT_CONTRACT,
    StrategySourceLineageError,
    canonicalize_dependencies,
    collect_strategy_source_lineage,
    source_lineage_dependencies,
)
from qlibx.models import QlibxModel
from qlibx.runtime import BacktestClock
from qlibx.strategy_state import (
    StrategyStateJsonError,
    StrategyStateUpdate,
    normalize_strategy_state,
)
from qlibx.view import (
    AccountFeedbackState,
    AccountHistoryProjection,
    AccountHistoryViewAccessError,
    AccountState,
    ArtifactViewAccessError,
    ExecutionInputProjection,
    PublishedSessionPerformanceState,
    ViewGate,
)


class StrategyRunResult(QlibxModel):
    result: StrategyResult
    artifact: ArtifactEnvelope
    final_strategy_state: object = None
    computed_draft: StrategyDraft | None = Field(default=None, exclude=True, repr=False)


@dataclass(frozen=True, slots=True)
class _StrategyStateSnapshot:
    strategy_id: str
    value: object


_UNSET = object()


class ResearchFlow:
    """Resolve, scope, calculate, and publish without authoritative state mutation."""

    def __init__(
        self,
        *,
        registry: RegistrySnapshot,
        artifacts: LocalArtifactBackend,
        resolver: RequirementResolver | None = None,
        store: ObservationStore | None = None,
        artifact_contracts: StrategyArtifactContractRegistry | None = None,
        strategy_dependencies: tuple[DependencyEdge, ...] = (),
    ) -> None:
        self._registry = registry
        self._artifacts = artifacts
        self._resolver = resolver or RequirementResolver()
        self._store = store or ObservationStore()
        self._artifact_contracts = artifact_contracts or StrategyArtifactContractRegistry.built_in()
        self._strategy_dependencies = strategy_dependencies

    def invoke_strategy(
        self,
        strategy: StrategyOperation,
        invocation: StrategyInvocation,
        *,
        account_state: AccountState | None = None,
        account_feedback: AccountFeedbackState | None = None,
        account_history_inputs: tuple[AccountHistoryProjection, ...] = (),
        session_performance: PublishedSessionPerformanceState | None = None,
        strategy_state: object = _UNSET,
        additional_dependencies: tuple[DependencyEdge, ...] = (),
        execution_inputs: tuple[ExecutionInputProjection, ...] = (),
    ) -> OperationOutcome:
        raw_strategy_state = (
            invocation.initial_strategy_state
            if strategy_state is _UNSET
            else strategy_state
        )
        try:
            prior_strategy_state = normalize_strategy_state(raw_strategy_state)
        except StrategyStateJsonError as exc:
            return self._failed_invocation(
                invocation,
                "strategy.run.state.seed",
                "MEMORY_NOT_JSON",
                exc,
            )
        try:
            requirements = strategy.requirements()
        except Exception as exc:
            return self._failed_invocation(
                invocation,
                "strategy.run.requirements",
                "STRATEGY_REQUIREMENTS_FAILED",
                exc,
            )
        resolution = self._resolver.resolve(
            operation="strategy.run",
            idempotency_identity=invocation.invocation_id,
            requirements=requirements,
            registry=self._registry,
        )
        if resolution.failed:
            return self._publish_errors(resolution.errors)

        try:
            artifact_requirements_method = getattr(strategy, "artifact_requirements", None)
            if artifact_requirements_method is None:
                artifact_requirements: tuple[StrategyArtifactRequirement, ...] = ()
            else:
                if not callable(artifact_requirements_method):
                    raise TypeError("artifact_requirements must be callable")
                artifact_requirements = tuple(artifact_requirements_method())
                if not all(
                    isinstance(requirement, StrategyArtifactRequirement)
                    for requirement in artifact_requirements
                ):
                    raise TypeError(
                        "artifact_requirements must return StrategyArtifactRequirement values"
                    )
        except Exception as exc:
            return self._failed_invocation(
                invocation,
                "strategy.run.artifacts.requirements",
                "STRATEGY_ARTIFACT_REQUIREMENTS_FAILED",
                exc,
            )

        artifact_resolution = StrategyArtifactResolver().resolve(
            invocation_id=invocation.invocation_id,
            requirements=artifact_requirements,
            bindings=invocation.artifact_bindings,
            artifacts=self._artifacts,
            contract_registry=self._artifact_contracts,
        )
        if artifact_resolution.failed:
            return self._publish_errors(artifact_resolution.errors)

        clock = BacktestClock(invocation.evaluation_time)
        view = ViewGate(self._registry, self._store).strategy_view(
            clock,
            resolution.bindings,
            account_state=account_state,
            account_feedback=account_feedback,
            account_history_inputs=account_history_inputs,
            session_performance=session_performance,
            strategy_state=_StrategyStateSnapshot(
                strategy_id=strategy.strategy_id,
                value=prior_strategy_state,
            ),
            artifact_inputs=artifact_resolution.projections,
            execution_inputs=execution_inputs,
        )
        try:
            draft = strategy.run(view)
            if not isinstance(draft, StrategyDraft):
                raise TypeError("Strategy run must return StrategyDraft")
        except AccountHistoryViewAccessError as exc:
            return self._failed_invocation(
                invocation,
                "strategy.run.account_history.access",
                exc.error_code,
                exc,
                requirement_id=exc.context.get("requirement_id"),
                error_context=exc.context,
                accesses=(
                    *view.accessed(),
                    *view.account_history_accessed(),
                    *view.state_accessed(),
                    *view.feedback_accessed(),
                    *view.performance_accessed(),
                    *view.strategy_state_accessed(),
                    *view.artifact_accessed(),
                    *view.execution_accessed(),
                ),
            )
        except ArtifactViewAccessError as exc:
            return self._failed_invocation(
                invocation,
                "strategy.run.artifacts.access",
                exc.error_code,
                exc,
                requirement_id=exc.context.get("requirement_id"),
                expected=exc.context.get("expected_contract"),
                error_context=exc.context,
                accesses=(
                    *view.accessed(),
                    *view.state_accessed(),
                    *view.feedback_accessed(),
                    *view.performance_accessed(),
                    *view.strategy_state_accessed(),
                    *view.artifact_accessed(),
                    *view.execution_accessed(),
                ),
            )
        except StrategyComputationError as exc:
            return self._failed_invocation(
                invocation,
                "strategy.run.compute",
                exc.code,
                exc,
                error_context=exc.context,
                accesses=(
                    *view.accessed(),
                    *view.state_accessed(),
                    *view.feedback_accessed(),
                    *view.performance_accessed(),
                    *view.strategy_state_accessed(),
                    *view.artifact_accessed(),
                    *view.execution_accessed(),
                ),
            )
        except DataSnapshotError as exc:
            return self._failed_invocation(
                invocation,
                "strategy.run.data",
                exc.code,
                exc,
                accesses=(
                    *view.accessed(),
                    *view.state_accessed(),
                    *view.feedback_accessed(),
                    *view.performance_accessed(),
                    *view.strategy_state_accessed(),
                    *view.artifact_accessed(),
                    *view.execution_accessed(),
                ),
            )
        except Exception as exc:
            return self._failed_invocation(
                invocation,
                "strategy.run.compute",
                "STRATEGY_RUN_FAILED",
                exc,
                accesses=(
                    *view.accessed(),
                    *view.state_accessed(),
                    *view.feedback_accessed(),
                    *view.performance_accessed(),
                    *view.strategy_state_accessed(),
                    *view.artifact_accessed(),
                    *view.execution_accessed(),
                ),
            )

        try:
            proposed_state = (
                None
                if draft.proposed_state is None
                else StrategyStateUpdate(
                    value=normalize_strategy_state(draft.proposed_state.value)
                )
            )
            final_strategy_state = (
                prior_strategy_state
                if proposed_state is None
                else proposed_state.value
            )
        except StrategyStateJsonError as exc:
            return self._failed_invocation(
                invocation,
                "strategy.run.state.update",
                "MEMORY_NOT_JSON",
                exc,
                accesses=(
                    *view.accessed(),
                    *view.account_history_accessed(),
                    *view.state_accessed(),
                    *view.feedback_accessed(),
                    *view.performance_accessed(),
                    *view.strategy_state_accessed(),
                    *view.artifact_accessed(),
                    *view.execution_accessed(),
                ),
            )

        accesses = view.accessed()
        state_accesses = view.state_accessed()
        account_history_accesses = view.account_history_accessed()
        feedback_accesses = view.feedback_accessed()
        performance_accesses = view.performance_accessed()
        strategy_state_accesses = view.strategy_state_accessed()
        artifact_accesses = view.artifact_accessed()
        execution_accesses = view.execution_accessed()
        try:
            observed_direct = validate_strategy_draft_path_dependence(
                draft,
                account_history_accesses=account_history_accesses,
                state_accesses=state_accesses,
                feedback_accesses=feedback_accesses,
                performance_accesses=performance_accesses,
                strategy_state_accesses=strategy_state_accesses,
                execution_accesses=execution_accesses,
            )
            source_state_lineage = collect_strategy_source_lineage(
                artifact_resolution.projections,
                artifact_accesses,
            )
        except StrategyPathDependenceError as exc:
            return self._failed_invocation(
                invocation,
                "strategy.run.path_dependence",
                "STRATEGY_PATH_DEPENDENCE_INCONSISTENT",
                exc,
                accesses=(
                    *accesses,
                    *state_accesses,
                    *feedback_accesses,
                    *performance_accesses,
                    *strategy_state_accesses,
                    *artifact_accesses,
                ),
            )
        except StrategySourceLineageError as exc:
            return self._failed_invocation(
                invocation,
                "strategy.run.source_lineage",
                exc.code,
                exc,
                error_context=exc.context,
                accesses=artifact_accesses,
            )

        invested_gross = sum(abs(entry.weight) for entry in draft.weights)
        result = StrategyResult(
            invocation_id=invocation.invocation_id,
            strategy_id=strategy.strategy_id,
            evaluation_time=invocation.evaluation_time,
            weights=draft.weights,
            budget_mode=draft.budget_mode,
            target_gross=draft.target_gross,
            invested_gross=invested_gross,
            net_exposure=sum(entry.weight for entry in draft.weights),
            residual_budget=draft.target_gross - invested_gross,
            decision_action=draft.decision_action,
            path_dependent=observed_direct or bool(source_state_lineage),
            state_identity=draft.state_identity if observed_direct else None,

            proposed_state=proposed_state,
            diagnostics=draft.diagnostics,
            accesses=accesses,
            account_history_accesses=account_history_accesses,
            state_accesses=state_accesses,
            feedback_accesses=feedback_accesses,
            performance_accesses=performance_accesses,
            strategy_state_accesses=strategy_state_accesses,
            execution_accesses=execution_accesses,
            source_state_lineage=source_state_lineage,
        )
        dependencies = (
            *(
                DependencyEdge(
                    dependency_kind="dataset",
                    dependency_id=access.registration_identity,
                    consumer_role=access.semantic_role,
                    selected_fields=(access.selected_field,),
                    compatibility_fingerprint=access.snapshot_fingerprint,
                )
                for access in result.accesses
            ),
            DependencyEdge(
                dependency_kind="config",
                dependency_id=invocation.config_fingerprint,
                consumer_role="strategy_config",
            ),
            *(
                DependencyEdge(
                    dependency_kind="state",
                    dependency_id=(
                        f"account:{access.account_id}:history:{access.shape.value}:"
                        f"{access.start_session}:{access.end_session}"
                    ),
                    consumer_role=f"actual_account_history:{access.requirement_id}",
                    selected_fields=access.selected_fields,
                    compatibility_fingerprint=(
                        f"rows:{access.requested_rows}:sessions:{access.available_sessions}:"
                        f"instruments:{','.join(access.instruments)}"
                    ),
                )
                for access in result.account_history_accesses
            ),
            *(
                DependencyEdge(
                    dependency_kind="state",
                    dependency_id=(
                        f"account:{access.account_id}:v{access.version}:"
                        f"cursor{access.feedback_cursor}"
                    ),
                    consumer_role="actual_account",
                    selected_fields=("cash", "nav", "positions", "feedback_cursor"),
                )
                for access in result.state_accesses
            ),
            *(
                DependencyEdge(
                    dependency_kind="state",
                    dependency_id=(
                        f"account:{access.account_id}:feedback:"
                        f"{access.after_cursor}-{access.next_cursor}"
                    ),
                    consumer_role="actual_account_feedback",
                    selected_fields=(
                        "event_ids",
                        "change_types",
                        "fill_ids",
                        "marked_instruments",
                    ),
                )
                for access in result.feedback_accesses
            ),
            *(
                DependencyEdge(
                    dependency_kind="artifact",
                    dependency_id=access.artifact_id,
                    consumer_role="completed_session_performance",
                    selected_fields=(
                        "portfolio_return",
                        "transaction_cost",
                        "turnover",
                        "closing_nav",
                    ),
                )
                for access in result.performance_accesses
            ),
            *(
                DependencyEdge(
                    dependency_kind="state",
                    dependency_id=(
                        f"strategy-state:{access.strategy_id}:"
                        f"{access.state_fingerprint}"
                    ),
                    consumer_role="strategy_state",
                    selected_fields=("value",),
                    compatibility_fingerprint=access.state_fingerprint,
                )
                for access in result.strategy_state_accesses
            ),
            *(
                DependencyEdge(
                    dependency_kind="artifact",
                    dependency_id=access.artifact_id,
                    consumer_role=access.consumer_role,
                    compatibility_fingerprint=access.content_hash,
                )
                for access in artifact_accesses
            ),
            *(
                DependencyEdge(
                    dependency_kind="artifact",
                    dependency_id=access.artifact_id,
                    consumer_role="latest_execution_result",
                    compatibility_fingerprint=access.content_hash,
                )
                for access in execution_accesses
            ),
            *source_lineage_dependencies(source_state_lineage),
            *self._strategy_dependencies,
            *additional_dependencies,
        )
        try:
            dependencies = canonicalize_dependencies(dependencies)
        except StrategySourceLineageError as exc:
            return self._failed_invocation(
                invocation,
                "strategy.run.dependencies",
                exc.code,
                exc,
                error_context=exc.context,
                accesses=artifact_accesses,
            )
        publication = self._artifacts.publish_model(
            logical_identity=f"strategy:{invocation.invocation_id}",
            artifact_type=STRATEGY_RESULT_CONTRACT.artifact_type,
            artifact_schema_version=STRATEGY_RESULT_CONTRACT.artifact_schema_version,
            producer_id=strategy.strategy_id,
            payload=result,
            dependencies=dependencies,
        )
        if publication.status is not OutcomeStatus.COMPLETE:
            return publication
        return OperationOutcome(
            status=OutcomeStatus.COMPLETE,
            result=StrategyRunResult(
                result=result,
                artifact=publication.result,
                final_strategy_state=final_strategy_state,
                computed_draft=draft,
            ),
        )

    def _failed_invocation(
        self,
        invocation: StrategyInvocation,
        stage_path: str,
        error_code: str,
        exception: Exception,
        *,
        requirement_id: str | None = None,
        expected: dict[str, object] | None = None,
        error_context: dict[str, object] | None = None,
        accesses: tuple[QlibxModel, ...] = (),
    ) -> OperationOutcome:
        error = build_operation_error(
            operation="strategy.run",
            stage_path=stage_path,
            error_code=error_code,
            requirement_id=requirement_id,
            expected=expected,
            context={
                "exception": type(exception).__name__,
                "message": str(exception)[:500],
                "accesses": [access.model_dump(mode="json") for access in accesses],
                **(error_context or {}),
            },
            retry_preconditions=("correct the Strategy contract or selected input",),
            idempotency_identity=invocation.invocation_id,
            error_identity_seed=(f"{invocation.invocation_id}:{stage_path}:{error_code}"),
        )
        return publish_failed_outcome(self._artifacts, error)

    def _publish_errors(
        self,
        errors: tuple[OperationError, ...],
    ) -> OperationOutcome:
        return publish_failed_errors(self._artifacts, errors)
