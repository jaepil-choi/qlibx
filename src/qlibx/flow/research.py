"""Orchestration for PIT-safe direct Strategy research."""

import hashlib

from qlibx.context import AccountState, MemoryState, ViewGate
from qlibx.data import ObservationStore, RegistrySnapshot, RequirementResolver
from qlibx.errors import CommitStatus, OperationError, OperationOutcome, OutcomeStatus
from qlibx.evidence import ArtifactEnvelope, DependencyEdge, LocalArtifactBackend
from qlibx.kernel import BacktestClock
from qlibx.models import QlibxModel
from qlibx.operations import StrategyInvocation, StrategyOperation, StrategyResult


class StrategyRunResult(QlibxModel):
    result: StrategyResult
    artifact: ArtifactEnvelope


class ResearchFlow:
    """Resolve, scope, calculate, and publish without authoritative state mutation."""

    def __init__(
        self,
        *,
        registry: RegistrySnapshot,
        artifacts: LocalArtifactBackend,
        resolver: RequirementResolver | None = None,
        store: ObservationStore | None = None,
    ) -> None:
        self._registry = registry
        self._artifacts = artifacts
        self._resolver = resolver or RequirementResolver()
        self._store = store or ObservationStore()

    def invoke_strategy(
        self,
        strategy: StrategyOperation,
        invocation: StrategyInvocation,
        *,
        account_state: AccountState | None = None,
        memory_state: MemoryState | None = None,
        additional_dependencies: tuple[DependencyEdge, ...] = (),
    ) -> OperationOutcome:
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
            published = tuple(self._artifacts.publish_failure(error) for error in resolution.errors)
            envelopes = tuple(
                outcome.result for outcome in published if outcome.status is OutcomeStatus.COMPLETE
            )
            return OperationOutcome(
                status=OutcomeStatus.FAILED,
                diagnostics=envelopes,
                errors=resolution.errors,
            )

        clock = BacktestClock(invocation.evaluation_time)
        view = ViewGate(self._registry, self._store).strategy_view(
            clock,
            resolution.bindings,
            account_state=account_state,
            memory_state=memory_state,
        )
        try:
            draft = strategy.run(view)
        except Exception as exc:
            return self._failed_invocation(
                invocation,
                "strategy.run.compute",
                "STRATEGY_RUN_FAILED",
                exc,
                accesses=(
                    *view.accessed(),
                    *view.state_accessed(),
                    *view.memory_accessed(),
                ),
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
            path_dependent=draft.path_dependent,
            state_identity=draft.state_identity,
            feedback_cursor=draft.feedback_cursor,
            proposed_memory=draft.proposed_memory,
            expected_memory_version=draft.expected_memory_version,
            diagnostics=draft.diagnostics,
            accesses=view.accessed(),
            state_accesses=view.state_accessed(),
            memory_accesses=view.memory_accessed(),
        )
        dependencies = (
            *(
                DependencyEdge(
                    dependency_kind="dataset",
                    dependency_id=access.registration_identity,
                    consumer_role=access.semantic_role,
                    selected_fields=(access.selected_field,),
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
                        f"memory:{access.strategy_id}:v{access.version}:"
                        f"cursor{access.feedback_cursor}"
                    ),
                    consumer_role="strategy_memory",
                    selected_fields=("value", "feedback_cursor"),
                )
                for access in result.memory_accesses
            ),
            *additional_dependencies,
        )
        publication = self._artifacts.publish_model(
            logical_identity=f"strategy:{invocation.invocation_id}",
            artifact_type="strategy_result",
            artifact_schema_version=1,
            producer_id=strategy.strategy_id,
            payload=result,
            dependencies=dependencies,
        )
        if publication.status is not OutcomeStatus.COMPLETE:
            return publication
        return OperationOutcome(
            status=OutcomeStatus.COMPLETE,
            result=StrategyRunResult(result=result, artifact=publication.result),
        )

    def _failed_invocation(
        self,
        invocation: StrategyInvocation,
        stage_path: str,
        error_code: str,
        exception: Exception,
        *,
        accesses: tuple[QlibxModel, ...] = (),
    ) -> OperationOutcome:
        seed = hashlib.sha256(
            f"{invocation.invocation_id}:{stage_path}:{error_code}".encode()
        ).hexdigest()[:24]
        error = OperationError(
            operation="strategy.run",
            stage_path=stage_path,
            error_code=error_code,
            context={
                "exception": type(exception).__name__,
                "message": str(exception)[:500],
                "accesses": [access.model_dump(mode="json") for access in accesses],
            },
            commit_status=CommitStatus.NONE,
            retry_preconditions=("correct the Strategy contract or selected input",),
            idempotency_identity=invocation.invocation_id,
            error_id=f"error-{seed}",
        )
        published = self._artifacts.publish_failure(error)
        diagnostics = (
            (published.result,) if published.status is OutcomeStatus.COMPLETE else published.errors
        )
        return OperationOutcome(
            status=OutcomeStatus.FAILED,
            diagnostics=diagnostics,
            errors=(error,),
        )
