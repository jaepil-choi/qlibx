"""PIT-bounded observation surface exposed to Models."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from vqapr.data.lookback import Lookback
from vqapr.data.requirements import DataRequirement
from vqapr.data.store import DuckDbObservationStore
from vqapr.domain.errors import ExplainTopic, Failure, FailureFamily, VqaprError
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

    @classmethod
    def _trusted(cls, rows: Rows, access: AccessRecord) -> ObservationBatch:
        """Build from rows this module already normalized.

        The public constructor validates every cell because it accepts outside input. Rows taken
        from a batch this module produced have passed that check once already, and checking them
        again costs the same as the query that produced them.
        """
        batch = cls.__new__(cls)
        object.__setattr__(batch, "rows", rows)
        object.__setattr__(batch, "access", access)
        return batch


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
                        # Names what the AUTHOR can change. `allowed_requirements` is a
                        # ModelWindow constructor parameter the framework supplies; a reader sent
                        # looking for it finds no callsite of their own to edit.
                        fix=(
                            "return this DataRequirement from the component's requirements() so "
                            "it is declared before compute"
                        ),
                        explain=ExplainTopic.COMPONENT_CONTRACT,
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

    def snapshot(self, requirement: DataRequirement) -> ObservationBatch:
        """The newest cross-section only: rows at the latest ``available_at`` per instrument.

        A lookback returns a window, not a line. Even ``RowsLookback(1)`` returns each
        instrument's own most recent row, and those rows do not share a date -- a name that
        stopped publishing carries a row from whenever it last did. Reading that window as if it
        were one moment silently mixes dates.

        That is not hypothetical. A benchmark built this way summed above 1.0 because names that
        had left the index contributed their final positive weight alongside current members.

        Rows keep their own ``available_at``, so a caller can still see that one instrument's
        newest observation is older than another's. What this removes is the need to find that
        edge for oneself.
        """
        batch = self.observations(requirement)
        newest: datetime | None = None
        for row in batch.rows:
            available_at = row["available_at"]
            if not isinstance(available_at, datetime):
                raise TypeError("registered available_at values must be datetimes")
            if newest is None or available_at > newest:
                newest = available_at
        # One instant across the batch, not one per instrument. Taking each instrument's own
        # newest row is exactly the window this method exists to collapse: it is what leaves a
        # departed name's final value sitting beside current ones.
        rows = tuple(row for row in batch.rows if row["available_at"] == newest)
        return ObservationBatch._trusted(
            tuple(sorted(rows, key=lambda row: str(row["instrument"]))), batch.access
        )
