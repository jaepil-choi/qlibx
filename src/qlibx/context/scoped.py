"""Clock-bound, role-scoped views with access lineage."""

from datetime import date, datetime
from typing import Any, Protocol, TypeVar, cast

import pandas as pd
from pydantic import Field

from qlibx.data.registry import RegistrySnapshot
from qlibx.data.requirements import ResolvedBinding
from qlibx.data.store import ObservationStore
from qlibx.kernel import Clock
from qlibx.models import QlibxModel


class ViewAccessError(RuntimeError):
    """Raised when code requests an undeclared or stale binding."""


class ArtifactViewAccessError(ViewAccessError):
    """Typed Strategy artifact access failure translated by the owning Flow."""

    def __init__(self, error_code: str, context: dict[str, Any]) -> None:
        self.error_code = error_code
        self.context = context
        super().__init__(str(context.get("message", error_code)))


class ArtifactInputProjection(QlibxModel):
    """Backend-free immutable artifact payload injected into a Strategy view."""

    requirement_id: str = Field(min_length=1)
    consumer_role: str = Field(min_length=1)
    artifact_id: str = Field(min_length=1)
    artifact_type: str = Field(min_length=1)
    artifact_schema_version: int = Field(ge=1)
    content_hash: str = Field(min_length=1)
    payload: QlibxModel


class ArtifactAccessRecord(QlibxModel):
    requirement_id: str = Field(min_length=1)
    consumer_role: str = Field(min_length=1)
    artifact_id: str = Field(min_length=1)
    artifact_type: str = Field(min_length=1)
    artifact_schema_version: int = Field(ge=1)
    content_hash: str = Field(min_length=1)


PayloadModel = TypeVar("PayloadModel", bound=QlibxModel)


class AccessRecord(QlibxModel):
    dataset_id: str
    registration_identity: str
    semantic_role: str
    selected_field: str
    as_of: datetime
    row_count: int = Field(ge=0)
    max_available_at: datetime | None = None
    max_observation_time: datetime | None = None


class StateHolding(QlibxModel):
    instrument_id: str
    quantity: float
    mark: float | None = None
    marked_at: datetime | None = None


class StateAccessRecord(QlibxModel):
    account_id: str
    version: int = Field(ge=0)
    feedback_cursor: int = Field(ge=0)
    cash: float
    nav: float
    valuation_status: str
    holdings: tuple[StateHolding, ...]
    as_of: datetime | None = None
    realized_pnl: tuple[tuple[str, float], ...] = ()


class AccountState(Protocol):
    account_id: str
    version: int
    feedback_cursor: int
    cash: float
    nav: float
    valuation_status: object
    positions: tuple[object, ...]
    as_of: datetime | None
    realized_pnl: tuple[tuple[str, float], ...]


class FeedbackAccessRecord(QlibxModel):
    account_id: str
    after_cursor: int = Field(ge=0)
    next_cursor: int = Field(ge=0)
    entry_cursors: tuple[int, ...]
    event_ids: tuple[str, ...]
    change_types: tuple[str, ...]
    fill_ids: tuple[str, ...]
    marked_instruments: tuple[str, ...]


class FeedbackMarkState(Protocol):
    instrument_id: str


class FeedbackEntryState(Protocol):
    cursor: int
    event_id: str
    change_type: str
    fill_ids: tuple[str, ...]
    marks: tuple[FeedbackMarkState, ...]


class AccountFeedbackState(Protocol):
    account_id: str
    after_cursor: int
    entries: tuple[FeedbackEntryState, ...]
    next_cursor: int


class SessionPerformanceAccessRecord(QlibxModel):
    artifact_id: str
    account_id: str
    event_id: str
    event_time: datetime
    feedback_cursor: int = Field(ge=0)


class SessionPerformanceRecordState(Protocol):
    account_id: str
    event_id: str
    event_time: datetime
    feedback_cursor: int


class PublishedSessionPerformanceState(Protocol):
    artifact_id: str
    record: SessionPerformanceRecordState


class MemoryAccessRecord(QlibxModel):
    strategy_id: str
    version: int = Field(ge=0)
    feedback_cursor: int = Field(ge=0)


class MemoryState(Protocol):
    strategy_id: str
    version: int
    value: object | None
    feedback_cursor: int


class _DatasetView:
    """Expose only declared PIT dataset inputs at a frozen clock position."""

    def __init__(
        self,
        *,
        as_of: datetime,
        bindings: tuple[ResolvedBinding, ...],
        registry: RegistrySnapshot,
        store: ObservationStore,
    ) -> None:
        self._as_of = as_of
        self._bindings = {binding.semantic_role: binding for binding in bindings}
        self._registry = registry
        self._store = store
        self._accessed: list[AccessRecord] = []

    @property
    def as_of(self) -> datetime:
        return self._as_of

    def history(self, semantic_role: str) -> pd.DataFrame:
        return self._read(semantic_role)

    def session(
        self,
        semantic_role: str,
        session_date: date,
        *,
        session_timezone: str,
    ) -> pd.DataFrame:
        return self._read(
            semantic_role,
            session_date=session_date,
            session_timezone=session_timezone,
        )

    def at(self, semantic_role: str, observation_at: datetime) -> pd.DataFrame:
        """Read only the observation whose event time exactly matches the callback."""

        return self._read(semantic_role, observation_at=observation_at)

    def _read(
        self,
        semantic_role: str,
        *,
        session_date: date | None = None,
        session_timezone: str | None = None,
        observation_at: datetime | None = None,
    ) -> pd.DataFrame:
        binding = self._binding(semantic_role)
        dataset = self._registry.get(binding.dataset_id)
        if dataset is None or dataset.registration_identity != binding.registration_identity:
            raise ViewAccessError("resolved binding is absent or stale in the registry snapshot")
        frame = self._store.query(
            dataset,
            field=binding.field,
            as_of=self._as_of,
            session_date=session_date,
            session_timezone=session_timezone,
            observation_at=observation_at,
        )
        maximum = frame["available_at"].max() if len(frame) else None
        maximum_observation = frame["observation_time"].max() if len(frame) else None
        self._accessed.append(
            AccessRecord(
                dataset_id=dataset.dataset_id,
                registration_identity=dataset.registration_identity,
                semantic_role=semantic_role,
                selected_field=binding.field,
                as_of=self._as_of,
                row_count=len(frame),
                max_available_at=maximum.to_pydatetime() if maximum is not None else None,
                max_observation_time=(
                    maximum_observation.to_pydatetime()
                    if maximum_observation is not None and not pd.isna(maximum_observation)
                    else None
                ),
            )
        )
        return frame.rename(columns={"value": semantic_role}).copy()

    def latest(self, semantic_role: str) -> pd.DataFrame:
        frame = self.history(semantic_role)
        if not len(frame):
            return frame
        return (
            frame.drop_duplicates(subset=["instrument"], keep="last")
            .sort_values("instrument", kind="mergesort")
            .reset_index(drop=True)
        )

    def accessed(self) -> tuple[AccessRecord, ...]:
        return tuple(self._accessed)

    def _binding(self, semantic_role: str) -> ResolvedBinding:
        try:
            return self._bindings[semantic_role]
        except KeyError as exc:
            raise ViewAccessError(f"semantic role {semantic_role!r} was not declared") from exc


class _AccountStateView(_DatasetView):
    """Add actual-account snapshot access to a dataset-scoped view."""

    def __init__(
        self,
        *,
        as_of: datetime,
        bindings: tuple[ResolvedBinding, ...],
        registry: RegistrySnapshot,
        store: ObservationStore,
        account_state: AccountState | None = None,
    ) -> None:
        super().__init__(
            as_of=as_of,
            bindings=bindings,
            registry=registry,
            store=store,
        )
        self._account_state = account_state
        self._state_accessed: list[StateAccessRecord] = []

    def account_snapshot(self) -> AccountState:
        if self._account_state is None:
            raise ViewAccessError("this view has no declared actual-account state")
        positions = tuple(
            StateHolding(
                instrument_id=str(position.instrument_id),
                quantity=float(position.quantity),
                mark=None if position.mark is None else float(position.mark),
                marked_at=position.marked_at,
            )
            for position in self._account_state.positions
        )
        valuation = self._account_state.valuation_status
        self._state_accessed.append(
            StateAccessRecord(
                account_id=self._account_state.account_id,
                version=self._account_state.version,
                feedback_cursor=self._account_state.feedback_cursor,
                cash=self._account_state.cash,
                nav=self._account_state.nav,
                valuation_status=str(getattr(valuation, "value", valuation)),
                holdings=positions,
                as_of=self._account_state.as_of,
                realized_pnl=self._account_state.realized_pnl,
            )
        )
        return self._account_state

    def state_accessed(self) -> tuple[StateAccessRecord, ...]:
        return tuple(self._state_accessed)


class StrategyView(_AccountStateView):
    """Expose declared Strategy data, evidence, actual state, feedback, and memory."""

    def __init__(
        self,
        *,
        as_of: datetime,
        bindings: tuple[ResolvedBinding, ...],
        registry: RegistrySnapshot,
        store: ObservationStore,
        account_state: AccountState | None = None,
        account_feedback: AccountFeedbackState | None = None,
        session_performance: PublishedSessionPerformanceState | None = None,
        memory_state: MemoryState | None = None,
        artifact_inputs: tuple[ArtifactInputProjection, ...] = (),
    ) -> None:
        super().__init__(
            as_of=as_of,
            bindings=bindings,
            registry=registry,
            store=store,
            account_state=account_state,
        )
        self._account_feedback = account_feedback
        self._session_performance = session_performance
        self._memory_state = memory_state
        self._artifact_inputs = {
            artifact.consumer_role: artifact for artifact in artifact_inputs
        }
        self._feedback_accessed: list[FeedbackAccessRecord] = []
        self._performance_accessed: list[SessionPerformanceAccessRecord] = []
        self._memory_accessed: list[MemoryAccessRecord] = []
        self._artifact_accessed: list[ArtifactAccessRecord] = []

    def artifact(
        self,
        consumer_role: str,
        payload_type: type[PayloadModel],
    ) -> PayloadModel:
        projection = self._artifact_inputs.get(consumer_role)
        if projection is None:
            raise ArtifactViewAccessError(
                "STRATEGY_ARTIFACT_ACCESS_UNDECLARED",
                {
                    "consumer_role": consumer_role,
                    "expected_contract": None,
                    "actual_contract": None,
                    "message": f"artifact role {consumer_role!r} was not declared",
                },
            )
        if not isinstance(projection.payload, payload_type):
            raise ArtifactViewAccessError(
                "STRATEGY_ARTIFACT_PAYLOAD_TYPE_MISMATCH",
                {
                    "requirement_id": projection.requirement_id,
                    "consumer_role": consumer_role,
                    "artifact_id": projection.artifact_id,
                    "expected_contract": {"payload_model": payload_type.__name__},
                    "actual_contract": {
                        "payload_model": type(projection.payload).__name__
                    },
                    "message": (
                        f"artifact role {consumer_role!r} contains "
                        f"{type(projection.payload).__name__}, not {payload_type.__name__}"
                    ),
                },
            )
        self._artifact_accessed.append(
            ArtifactAccessRecord(
                requirement_id=projection.requirement_id,
                consumer_role=projection.consumer_role,
                artifact_id=projection.artifact_id,
                artifact_type=projection.artifact_type,
                artifact_schema_version=projection.artifact_schema_version,
                content_hash=projection.content_hash,
            )
        )
        return cast(PayloadModel, projection.payload)

    def artifact_accessed(self) -> tuple[ArtifactAccessRecord, ...]:
        return tuple(self._artifact_accessed)

    def account_feedback(self) -> AccountFeedbackState:
        if self._account_feedback is None:
            raise ViewAccessError("this view has no declared actual-account feedback")
        entries = self._account_feedback.entries
        self._feedback_accessed.append(
            FeedbackAccessRecord(
                account_id=self._account_feedback.account_id,
                after_cursor=self._account_feedback.after_cursor,
                next_cursor=self._account_feedback.next_cursor,
                entry_cursors=tuple(int(entry.cursor) for entry in entries),
                event_ids=tuple(str(entry.event_id) for entry in entries),
                change_types=tuple(str(entry.change_type) for entry in entries),
                fill_ids=tuple(
                    str(fill_id)
                    for entry in entries
                    for fill_id in entry.fill_ids
                ),
                marked_instruments=tuple(
                    str(mark.instrument_id)
                    for entry in entries
                    for mark in entry.marks
                ),
            )
        )
        return self._account_feedback

    def feedback_accessed(self) -> tuple[FeedbackAccessRecord, ...]:
        return tuple(self._feedback_accessed)

    def latest_session_performance(self) -> SessionPerformanceRecordState:
        if self._session_performance is None:
            raise ViewAccessError("this view has no completed session performance")
        record = self._session_performance.record
        self._performance_accessed.append(
            SessionPerformanceAccessRecord(
                artifact_id=self._session_performance.artifact_id,
                account_id=record.account_id,
                event_id=record.event_id,
                event_time=record.event_time,
                feedback_cursor=record.feedback_cursor,
            )
        )
        return record

    def performance_accessed(self) -> tuple[SessionPerformanceAccessRecord, ...]:
        return tuple(self._performance_accessed)

    def memory_snapshot(self) -> MemoryState:
        if self._memory_state is None:
            raise ViewAccessError("this view has no declared Strategy memory")
        self._memory_accessed.append(
            MemoryAccessRecord(
                strategy_id=self._memory_state.strategy_id,
                version=self._memory_state.version,
                feedback_cursor=self._memory_state.feedback_cursor,
            )
        )
        return self._memory_state

    def memory_accessed(self) -> tuple[MemoryAccessRecord, ...]:
        return tuple(self._memory_accessed)


class MaterializeView(_DatasetView):
    """Dataset-only view for model or transform materialization."""


class ExecutionView(_DatasetView):
    """Dataset-only market view for an execution callback."""


class MonitorView(_AccountStateView):
    """Dataset and committed-account view for independent monitoring."""


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
        memory_state: MemoryState | None = None,
        artifact_inputs: tuple[ArtifactInputProjection, ...] = (),
    ) -> StrategyView:
        return StrategyView(
            as_of=clock.now,
            bindings=bindings,
            registry=self._registry,
            store=self._store,
            account_state=account_state,
            account_feedback=account_feedback,
            session_performance=session_performance,
            memory_state=memory_state,
            artifact_inputs=artifact_inputs,
        )

    def materialize_view(
        self,
        clock: Clock,
        bindings: tuple[ResolvedBinding, ...],
    ) -> MaterializeView:
        return MaterializeView(
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