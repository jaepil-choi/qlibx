"""A datamodel run: the same loop as a strategy's, with compute where the callback was.

Record `148` closes `docs/issues/059`. A DataModel used to be run by `materialize()`: its own loop
over a list of instants from a spec file, every row of every evaluation held in memory until the
end, one parquet and a lineage file written at once, and a `record.json` of its own kind. It is a
run now, registered under `runs:` like a strategy run, frozen by the same preflight, walked by the
same `EventLoop`, recorded under the same `runs/<run-id>/` directory -- with a
`ComputeHandler` in the callback handler's place and no execution or valuation handler, because a
datamodel sees no account and passes through no venue (architecture 4.4).

What leaves the process is `output.py`'s subject: the sessions' rows land as one parquet file and
the dataset registers right after.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from vqapr.authoring import DataModel
from vqapr.data.datasets import DatasetRegistration
from vqapr.data.windows import ModelWindow
from vqapr.domain.agendas import OperationOccurrence
from vqapr.flow.datamodel.compute import ComputeHandler, DataModelTrace
from vqapr.flow.datamodel.output import DataModelOutput
from vqapr.flow.declaration.frozen import FrozenDataModel, FrozenRun
from vqapr.flow.loop import EventLoop, OccurrenceEvent


@dataclass(frozen=True, slots=True)
class DataModelResult:
    """A finished datamodel run: one trace per session, and the dataset it registered."""

    occurrences: tuple[DataModelTrace, ...]
    rows: int
    output_path: Path
    registration: DatasetRegistration | None = None


class DataModelEventLoop(EventLoop[OccurrenceEvent, DataModelTrace, DataModelResult]):
    """Walk one datamodel's sessions: compute at each, chunk the rows, register at the end.

    No due events: a datamodel mints nothing between its sessions, so `pending` keeps the
    base's `None` and the loop is the plain sequence of scheduled occurrences.
    """

    def __init__(
        self,
        frozen_run: FrozenRun,
        layer: FrozenDataModel,
        model: DataModel,
        *,
        window_for_occurrence: Callable[[OperationOccurrence], ModelWindow],
        output: DataModelOutput,
        on_progress: Callable[[], None] | None = None,
    ) -> None:
        if layer not in frozen_run.datamodels:
            raise ValueError("layer must be one of the frozen run's datamodels")
        if not callable(window_for_occurrence):
            raise TypeError("window_for_occurrence must be callable")
        cutoff = frozen_run.start or frozen_run.end
        if cutoff is None:
            raise RuntimeError("a datamodel run requires a frozen boundary")
        super().__init__(
            schedule=frozen_run.dispatch_order(layer), start_cutoff=cutoff, on_progress=on_progress
        )
        self._output = output
        self._phase = ComputeHandler(
            frozen_run=frozen_run,
            layer=layer,
            model=model,
            window_for_occurrence=window_for_occurrence,
            output=output,
        )

    def start(self, cutoff: datetime) -> None:
        self._output.open()

    def handle(self, event: OccurrenceEvent) -> DataModelTrace:
        return self._phase.dispatch(event.occurrence)

    def finish(self, traces: tuple[DataModelTrace, ...]) -> DataModelResult:
        return DataModelResult(
            occurrences=traces,
            rows=self._output.rows,
            output_path=self._output.directory,
        )


__all__ = [
    "DataModelEventLoop",
    "DataModelResult",
]
