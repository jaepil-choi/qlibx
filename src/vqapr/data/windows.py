"""PIT-bounded observation surface exposed to Models."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from vqapr.data.lookback import Lookback
from vqapr.data.requirements import DataRequirement
from vqapr.data.store import DuckDbObservationStore
from vqapr.domain.errors import Failure, FailureFamily, VqaprError
from vqapr.domain.identifiers import DatasetId, instrument_id
from vqapr.domain.rows import Rows, normalize_rows
from vqapr.domain.timestamps import require_tz_aware

_STAGE = "model_window.requirement"


@dataclass(frozen=True, slots=True)
class AccessRecord:
    consumer_id: str
    dataset_id: DatasetId
    source_id: str
    source_digest: str
    fields: tuple[str, ...]
    lookback: Lookback
    evaluation_time: datetime
    instruments: tuple[str, ...]
    lower_bound: datetime | None
    actual_rows: Mapping[str, Mapping[str, int]]
    max_available_at: datetime | None


@dataclass(frozen=True, slots=True)
class ObservationBatch:
    rows: Rows
    access: AccessRecord

    def __init__(self, rows: object, access: AccessRecord) -> None:
        object.__setattr__(self, "rows", normalize_rows(rows))
        if not isinstance(access, AccessRecord):
            raise TypeError("access must be an AccessRecord")
        object.__setattr__(self, "access", access)


class ModelWindow:
    """One evaluation time, declared instruments, and only declared requirements."""

    __slots__ = ("__allowed", "__store", "_accesses", "evaluation_time", "instruments")

    def __init__(
        self,
        *,
        evaluation_time: datetime,
        instruments: Sequence[str],
        store: DuckDbObservationStore,
        allowed_requirements: Sequence[DataRequirement],
    ) -> None:
        self.evaluation_time = require_tz_aware(evaluation_time, name="evaluation_time")
        selected = tuple(str(instrument_id(value)) for value in instruments)
        if not selected:
            raise ValueError("ModelWindow requires at least one instrument")
        if len(set(selected)) != len(selected):
            raise ValueError("ModelWindow instruments must be unique")
        if not isinstance(store, DuckDbObservationStore):
            raise TypeError("store must be a DuckDbObservationStore")
        allowed = tuple(allowed_requirements)
        if not all(isinstance(item, DataRequirement) for item in allowed):
            raise ValueError("allowed_requirements must contain only DataRequirement values")
        self.instruments = selected
        self.__store = store
        self.__allowed = allowed
        self._accesses: list[AccessRecord] = []

    @property
    def accesses(self) -> tuple[AccessRecord, ...]:
        return tuple(self._accesses)

    def observations(self, requirement: DataRequirement) -> ObservationBatch:
        if requirement not in self.__allowed:
            raise VqaprError(
                stage=_STAGE,
                family=FailureFamily.DATA,
                failures=[
                    Failure.bounded(
                        code=f"{_STAGE}.undeclared",
                        requirement=(
                            "a Model may read only a DataRequirement declared before compute"
                        ),
                        observed=repr(requirement),
                    )
                ],
                mutation=False,
                retry_precondition="declare the exact requirement, then retry",
            )
        batch = self.__store.query(
            requirement,
            evaluation_time=self.evaluation_time,
            instruments=self.instruments,
        )
        self._accesses.append(batch.access)
        return batch
