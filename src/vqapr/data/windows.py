"""PIT-bounded observation surface exposed to Models."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from vqapr.data.panel import PanelWindow
from vqapr.data.requirements import DataRequirement
from vqapr.data.store import AccessRecord, DuckDbObservationStore, ObservationBatch
from vqapr.domain.errors import Failure, Stage, Status, VqaprError
from vqapr.domain.identifiers import instrument_id
from vqapr.domain.instants import require_tz_aware


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
        call it. The compliance evaluation observes with each rule in turn against one window;
        each gets its own view of it, and every access still lands in the one log this instant
        collects.

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
        return self.declared((requirement,))

    def panel(self, requirements: Sequence[DataRequirement], field: str) -> PanelWindow:
        """One field of a panel-grain alias as a 2d slice (design §2.5; record `137`).

        Each requirement is refused if undeclared, exactly as a row read is; the read is recorded
        as one access, so provenance and `derived_available_at` see it like any other.
        """
        declared = tuple(requirements)
        for requirement in declared:
            if requirement not in self.__allowed:
                raise self._undeclared(requirement)
        if self.consumer_id is None:
            raise RuntimeError(
                "this window serves several components, so a read must name one: take "
                "window.for_consumer(<component id>) before reading"
            )
        window, access = self.__store.panel_window(
            declared,
            field,
            evaluation_time=self.evaluation_time,
            instruments=self.instruments,
            consumer_id=self.consumer_id,
        )
        self._accesses.append(access)
        return window

    def grain(self, requirement: DataRequirement):
        """The declared grain of the dataset a requirement names, so a context can steer."""
        return self.__store.grain(requirement)

    def declared(self, requirements: Sequence[DataRequirement]) -> ObservationBatch:
        """Every field an alias declared, in one scan (`docs/issues/046`, lane D).

        The requirements are one alias's -- one dataset, one lookback, one field each -- and the
        store reads them as one `fields` mapping in one statement. Each is refused if it was not
        declared before compute, exactly as a single one is; one access is recorded, naming
        every field read.
        """
        declared = tuple(requirements)
        for requirement in declared:
            if requirement in self.__allowed:
                continue
            raise self._undeclared(requirement)
        if self.consumer_id is None:
            raise RuntimeError(
                "this window serves several components, so a read must name one: take "
                "window.for_consumer(<component id>) before calling observations()"
            )
        batch = self.__store.query_many(
            declared,
            evaluation_time=self.evaluation_time,
            instruments=self.instruments,
            consumer_id=self.consumer_id,
        )
        self._accesses.append(batch.access)
        return batch

    @staticmethod
    def _undeclared(requirement: DataRequirement) -> VqaprError:
        return VqaprError(
                stage=Stage.RUN,
                failures=[
                    Failure.bounded(
                        code="requirement.undeclared",
                        status=Status.CONTRACT,
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
                    )
                ],
                mutation=False,
                retry_precondition="declare the exact requirement, then retry",
            )

    def snapshot(self, requirement: DataRequirement) -> ObservationBatch:
        """The newest cross-section only: rows at the latest ``available_at`` per instrument.

        A lookback returns a window, not a line. Even ``InstantsLookback(1)`` on a rows-grain
        table returns each instrument's own most recent row, and those rows do not share a
        date -- a name that stopped publishing carries a row from whenever it last did. Reading
        that window as if it were one moment silently mixes dates.

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
