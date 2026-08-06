"""Clock-bound, role-scoped views with access lineage."""

from datetime import datetime

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


class StrategyView:
    """Expose only declared Strategy inputs at a frozen clock position."""

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
        binding = self._binding(semantic_role)
        dataset = self._registry.get(binding.dataset_id)
        if dataset is None or dataset.registration_identity != binding.registration_identity:
            raise ViewAccessError("resolved binding is absent or stale in the registry snapshot")
        frame = self._store.query(dataset, field=binding.field, as_of=self._as_of)
        maximum = frame["available_at"].max() if len(frame) else None
        self._accessed.append(
            AccessRecord(
                dataset_id=dataset.dataset_id,
                registration_identity=dataset.registration_identity,
                semantic_role=semantic_role,
                selected_field=binding.field,
                as_of=self._as_of,
                row_count=len(frame),
                max_available_at=maximum.to_pydatetime() if maximum is not None else None,
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


class MaterializeView(StrategyView):
    """Role-scoped view for model or transform materialization."""


class ViewGate:
    """Construct views; operations never receive the raw observation store."""

    def __init__(self, registry: RegistrySnapshot, store: ObservationStore | None = None) -> None:
        self._registry = registry
        self._store = store or ObservationStore()

    def strategy_view(
        self,
        clock: Clock,
        bindings: tuple[ResolvedBinding, ...],
    ) -> StrategyView:
        return StrategyView(
            as_of=clock.now,
            bindings=bindings,
            registry=self._registry,
            store=self._store,
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
