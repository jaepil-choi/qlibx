"""One session of a datamodel run: the phase that stands where a strategy's callback stands.

A datamodel sees no account and passes through no venue (architecture 4.4), so this is the whole
of its per-session work: take the window, call `compute`, admit what it returned, stamp it, and
hand it to the output.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from vqapr.authoring import DataModel
from vqapr.calls import DataModelContext
from vqapr.data.store import AccessRecord
from vqapr.data.windows import ModelWindow
from vqapr.domain.agendas import OperationOccurrence
from vqapr.domain.errors import Stage, Status, VqaprError
from vqapr.domain.shapes import Row
from vqapr.flow.datamodel.output import (
    DataModelOutput,
    derived_available_at,
    refusal,
    validated_output,
)
from vqapr.flow.declaration.frozen import FrozenDataModel, FrozenRun


@dataclass(frozen=True, slots=True)
class DataModelTrace:
    """What one session's compute did: when it ran, what it read, what it produced."""

    occurrence: OperationOccurrence
    evaluation_time: datetime
    output_available_at: datetime
    row_count: int
    accesses: tuple[AccessRecord, ...]


class ComputeHandler:
    """One session's compute: window, rows, stamp, chunk."""

    def __init__(
        self,
        *,
        frozen_run: FrozenRun,
        layer: FrozenDataModel,
        model: DataModel,
        window_for_occurrence: Callable[[OperationOccurrence], ModelWindow],
        output: DataModelOutput,
    ) -> None:
        self._frozen_run = frozen_run
        self._layer = layer
        self._model = model
        self._window_for_occurrence = window_for_occurrence
        self._output = output
        # Resolved once for the whole run: `inputs()` is a declaration, not a per-session
        # decision, and re-resolving it each time would let it differ between sessions.
        self._reads = model.inputs()

    def dispatch(self, occurrence: OperationOccurrence) -> DataModelTrace:
        window = self._window_for_occurrence(occurrence)
        evaluation_time = window.evaluation_time
        try:
            raw = self._model.compute(DataModelContext(window, self._reads))
        except VqaprError:
            raise
        except Exception as error:
            raise refusal(
                Stage.RUN,
                "datamodel.compute_failed",
                "DataModel.compute must complete for every session",
                f"{occurrence.occurrence_id}: {type(error).__name__}: {error}",
                status=Status.CRASHED,
                fix=(
                    "fix the exception raised inside DataModel.compute for this session; the "
                    "traceback is in `cause`"
                ),
                cause=error,
                retry="fix the DataModel or its declared input sufficiency, then retry",
            ) from error
        rows = validated_output(
            raw,
            value_fields=self._layer.value_fields,
            selected_instruments=self._frozen_run.instruments,
        )
        available_at = derived_available_at(evaluation_time, window.accesses)
        stamped: list[Row] = []
        for row in rows:
            record: Row = {"available_at": available_at, "instrument": row["instrument"]}
            record.update({field: row[field] for field in self._layer.value_fields})
            stamped.append(record)
        self._output.append(stamped)
        return DataModelTrace(
            occurrence=occurrence,
            evaluation_time=evaluation_time,
            output_available_at=available_at,
            row_count=len(rows),
            accesses=window.accesses,
        )


__all__ = [
    "ComputeHandler",
    "DataModelTrace",
]
