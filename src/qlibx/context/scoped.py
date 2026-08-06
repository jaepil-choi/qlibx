"""Clock-bound, role-scoped views with access lineage."""

from datetime import date, datetime
from typing import Protocol

import pandas as pd
from pydantic import Field

from qlibx.data.registry import RegistrySnapshot
from qlibx.data.requirements import ResolvedBinding
from qlibx.data.store import ObservationStore
from qlibx.kernel import Clock
from qlibx.models import QlibxModel


class ViewAccessError(RuntimeError):
    """Raised when code requests an undeclared or stale binding."""


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


class StateAccessRecord(QlibxModel):
    account_id: str
    version: int = Field(ge=0)
    feedback_cursor: int = Field(ge=0)
    cash: float
    nav: float
    valuation_status: str
    holdings: tuple[StateHolding, ...]


class AccountState(Protocol):
    account_id: str
    version: int
    feedback_cursor: int
    cash: float
    nav: float
    valuation_status: object
    positions: tuple[object, ...]


class MemoryAccessRecord(QlibxModel):
    strategy_id: str
    version: int = Field(ge=0)
    feedback_cursor: int = Field(ge=0)


class MemoryState(Protocol):
    strategy_id: str
    version: int
    value: object | None
    feedback_cursor: int


class StrategyView:
    """Expose only declared Strategy inputs at a frozen clock position."""

    def __init__(
        self,
        *,
        as_of: datetime,
        bindings: tuple[ResolvedBinding, ...],
        registry: RegistrySnapshot,
        store: ObservationStore,
        account_state: AccountState | None = None,
        memory_state: MemoryState | None = None,
    ) -> None:
        self._as_of = as_of
        self._bindings = {binding.semantic_role: binding for binding in bindings}
        self._registry = registry
        self._store = store
        self._account_state = account_state
        self._memory_state = memory_state
        self._accessed: list[AccessRecord] = []
        self._state_accessed: list[StateAccessRecord] = []
        self._memory_accessed: list[MemoryAccessRecord] = []

    @property
    def as_of(self) -> datetime:
        return self._as_of

    def history(self, semantic_role: str) -> pd.DataFrame:
        return self._read(semantic_role)

    def session(self, semantic_role: str, session_date: date) -> pd.DataFrame:
        return self._read(semantic_role, session_date=session_date)

    def _read(
        self,
        semantic_role: str,
        *,
        session_date: date | None = None,
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

    def account_snapshot(self) -> AccountState:
        if self._account_state is None:
            raise ViewAccessError("this view has no declared actual-account state")
        positions = tuple(
            StateHolding(
                instrument_id=str(position.instrument_id),
                quantity=float(position.quantity),
                mark=(
                    None
                    if position.mark is None
                    else float(position.mark)
                ),
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
            )
        )
        return self._account_state

    def state_accessed(self) -> tuple[StateAccessRecord, ...]:
        return tuple(self._state_accessed)

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

    def _binding(self, semantic_role: str) -> ResolvedBinding:
        try:
            return self._bindings[semantic_role]
        except KeyError as exc:
            raise ViewAccessError(f"semantic role {semantic_role!r} was not declared") from exc


class MaterializeView(StrategyView):
    """Role-scoped view for model or transform materialization."""


class ExecutionView(StrategyView):
    """Role-scoped market view for an execution callback."""


class MonitorView(StrategyView):
    """Role-scoped data view for an independent monitoring callback."""


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
        memory_state: MemoryState | None = None,
    ) -> StrategyView:
        return StrategyView(
            as_of=clock.now,
            bindings=bindings,
            registry=self._registry,
            store=self._store,
            account_state=account_state,
            memory_state=memory_state,
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
        *,
        account_state: AccountState,
    ) -> ExecutionView:
        return ExecutionView(
            as_of=clock.now,
            bindings=bindings,
            registry=self._registry,
            store=self._store,
            account_state=account_state,
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
