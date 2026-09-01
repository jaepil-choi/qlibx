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
    """What one declared requirement returned, and the record of how it was read.

    This is the only shape a Model ever receives data in, and until 2026-08-30 it was not
    importable from `vqapr.public` and had no docstring -- so an author could read its name in
    `observations()`'s signature and had no way to learn what it holds without opening installed
    source. One journey answered the questions below by registering a throwaway DataModel that
    reported `sorted(rows[0].keys())`, which is a full register-materialize-show cycle spent on one
    type's field names (`docs/issues/031`).

    **`rows` is a flat tuple of dicts, one per (instant, instrument) observation.** Every row
    carries:

    * `available_at` -- a timezone-aware `datetime`, the row's OWN point-in-time stamp rather than
      the window's evaluation time. Rows do not share one instant, so this is what a cross-section
      is built on.
    * `instrument` -- the instrument id, as a string. **Absent** on a dataset registered with no
      `instrument_field`: those rows are not keyed by instrument, the declared instrument list is
      not applied to them, and there is no name to put here (`docs/issues/038`).
    * the field the requirement named, under its own id -- a requirement names one field and a
      lookback, and nothing else (`docs/issues/049`). A value is `None` where the source has no
      value; a `RowsLookback` also nulls it on rows outside that field's own last-N (see
      `RowsLookback`).

    **A value keeps the parquet column's own type.** A `DOUBLE` column arrives as `float` and a
    `DECIMAL` column as `Decimal`; nothing here converts between them, because a conversion either
    way would be this package deciding how precise somebody else's measurement is. So a model must
    not assume either: `Decimal(str(value))` is correct for both and is what the scaffolds emit,
    while `Decimal(value)` on a float inherits the binary expansion and mixing the two in one
    arithmetic expression raises.

    **Ordering is guaranteed: ascending `available_at`, then the dataset's registered key fields.**
    It is pushed into SQL (`scan.observation_rows`) rather than applied afterwards, so it holds for
    every lookback and every instrument count, and `tests/data/test_observation_batch_shape.py`
    pins it. A dataset whose fields aggregate within an instant orders by `available_at` then
    `instrument` instead, because the key fields were consumed making the group and are not in
    what came out of it. Instruments therefore INTERLEAVE within an instant rather than being
    grouped by name:
    a per-instrument series is built by the reader, and a cross-section is `rows` filtered on one
    `available_at`. `ModelWindow.snapshot` returns the newest cross-section directly.

    `access` is the `AccessRecord` the framework stamps -- source digest, declared fields, the
    lookback, the bound it resolved, per-instrument non-null counts. It is provenance, not data,
    and a Model normally reads only `rows`.
    """

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

    __slots__ = (
        "__allowed",
        "__store",
        "_accesses",
        "consumer_id",
        "evaluation_time",
        "instruments",
    )

    def __init__(
        self,
        *,
        evaluation_time: datetime,
        instruments: Sequence[str],
        store: DuckDbObservationStore,
        allowed_requirements: Sequence[DataRequirement],
        consumer_id: str | None = None,
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
        if consumer_id is not None and (
            not isinstance(consumer_id, str) or not consumer_id.strip()
        ):
            raise ValueError("consumer_id must be a non-empty identifier")
        self.instruments = selected
        self.consumer_id = consumer_id
        self.__store = store
        self.__allowed = allowed
        self._accesses: list[AccessRecord] = []

    def for_consumer(self, consumer_id: str) -> ModelWindow:
        """The same window, read on behalf of another component.

        A `DataRequirement` no longer carries a consumer id, so the framework supplies it -- and
        the only place that knows which component is about to read is the loop that is about to
        call it. The constraint loops project and evaluate each constraint in turn against one
        window; each gets its own view of it, and every access still lands in the one log this
        occurrence collects.

        **The access log is shared, not copied.** A view that kept its own would silently drop
        whatever it recorded.

        A window built for several components at once carries no consumer of its own and refuses
        to be read directly, so taking a view is the only way in rather than the polite way in.
        """
        if not isinstance(consumer_id, str) or not consumer_id.strip():
            raise ValueError("consumer_id must be a non-empty identifier")
        view = ModelWindow.__new__(ModelWindow)
        view.evaluation_time = self.evaluation_time
        view.instruments = self.instruments
        view.consumer_id = consumer_id
        view.__store = self.__store
        view.__allowed = self.__allowed
        view._accesses = self._accesses
        return view

    @property
    def accesses(self) -> tuple[AccessRecord, ...]:
        return tuple(self._accesses)

    def observations(self, requirement: DataRequirement) -> ObservationBatch:
        """Every row this requirement's lookback admits, at or before the evaluation time.

        The whole window, ordered by `available_at` then the dataset's key fields -- see
        `ObservationBatch` for the row shape and the ordering guarantee, which a cross-sectional
        model depends on. `snapshot` is the same read collapsed to the newest instant.

        Refuses a requirement the component did not declare before compute: an undeclared read is
        not point-in-time bounded, and being bounded is what the declaration buys.
        """
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
        if self.consumer_id is None:
            raise RuntimeError(
                "this window serves several components, so a read must name one: take "
                "window.for_consumer(<component id>) before calling observations()"
            )
        batch = self.__store.query(
            requirement,
            evaluation_time=self.evaluation_time,
            instruments=self.instruments,
            consumer_id=self.consumer_id,
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
        # A cross-section is ordered by instrument, and a dataset with no instrument axis has one
        # row per instant rather than a cross-section at all -- so there is nothing to order it by
        # and the single row is returned as it came.
        if not batch.access.instruments:
            return ObservationBatch._trusted(rows, batch.access)
        return ObservationBatch._trusted(
            tuple(sorted(rows, key=lambda row: str(row["instrument"]))), batch.access
        )
