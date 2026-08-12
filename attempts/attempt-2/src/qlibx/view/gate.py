"""IoC construction gate for clock-bound least-authority views."""

from qlibx.data.registry import RegistrySnapshot
from qlibx.data.requirements import ResolvedBinding
from qlibx.data.store import ObservationStore
from qlibx.runtime import Clock
from qlibx.view.records import (
    AccountFeedbackState,
    AccountHistoryProjection,
    AccountState,
    ArtifactInputProjection,
    ExecutionInputProjection,
    PublishedSessionPerformanceState,
    StrategyStateSnapshot,
)
from qlibx.view.views import ExecutionView, ModelView, MonitorView, StrategyView


class ViewGate:
    """Construct views; operations never receive the raw observation store."""

    def __init__(self, registry: RegistrySnapshot, store: ObservationStore | None = None) -> None:
        self._registry = registry
        self._store = store or ObservationStore()

    def strategy_view(
        self,
        clock: Clock,
        bindings: tuple[ResolvedBinding, ...],
        *,
        account_state: AccountState | None = None,
        account_feedback: AccountFeedbackState | None = None,
        session_performance: PublishedSessionPerformanceState | None = None,
        strategy_state: StrategyStateSnapshot | None = None,
        account_history_inputs: tuple[AccountHistoryProjection, ...] = (),
        artifact_inputs: tuple[ArtifactInputProjection, ...] = (),
        execution_inputs: tuple[ExecutionInputProjection, ...] = (),
    ) -> StrategyView:
        return StrategyView(
            as_of=clock.now,
            bindings=bindings,
            registry=self._registry,
            store=self._store,
            account_state=account_state,
            account_feedback=account_feedback,
            session_performance=session_performance,
            strategy_state=strategy_state,
            account_history_inputs=account_history_inputs,
            artifact_inputs=artifact_inputs,
            execution_inputs=execution_inputs,
        )

    def model_view(
        self,
        clock: Clock,
        bindings: tuple[ResolvedBinding, ...],
    ) -> ModelView:
        return ModelView(
            as_of=clock.now,
            bindings=bindings,
            registry=self._registry,
            store=self._store,
        )

    def execution_view(
        self,
        clock: Clock,
        bindings: tuple[ResolvedBinding, ...],
    ) -> ExecutionView:
        return ExecutionView(
            as_of=clock.now,
            bindings=bindings,
            registry=self._registry,
            store=self._store,
        )

    def monitor_view(
        self,
        clock: Clock,
        bindings: tuple[ResolvedBinding, ...],
        *,
        account_state: AccountState,
    ) -> MonitorView:
        return MonitorView(
            as_of=clock.now,
            bindings=bindings,
            registry=self._registry,
            store=self._store,
            account_state=account_state,
        )


__all__ = ["ViewGate"]
