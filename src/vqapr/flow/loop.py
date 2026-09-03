"""The loop both kinds of run share: static occurrences in order, due items between them.

A strategy run and a datamodel run are the same loop (record `148`, owner: *"datamodel은 account
없고 execution 없는 strategy처럼 돌아야 해"*). What differs is what an occurrence dispatches to --
a Strategy's callback, then the fill it asked for, or a DataModel's compute -- and what a finished
loop returns. Those are the hooks; the walk is written once.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from vqapr.runtime.agendas import OperationOccurrence
from vqapr.runtime.events import DueExecutionEnvelope, OperationEnvelope


class OccurrenceFlow:
    """Walk a frozen model's occurrences, dispatching each and every due item that falls between.

    A subclass sets `_static_occurrences`, `_on_progress` and `_start_cutoff`, and implements the
    hooks. `_pending_due` returns `None` for a flow that never mints due items, and the loop then
    is the plain sequence of occurrences.
    """

    _static_occurrences: tuple[OperationOccurrence, ...]
    _on_progress: Callable[[], None] | None
    _start_cutoff: datetime

    def run(self) -> object:
        """Synchronously process the static occurrences and every due item in their horizon."""
        self._start(self._start_cutoff)
        traces: list[object] = []
        static = iter(OperationEnvelope(item) for item in self._static_occurrences)
        next_static = next(static, None)

        while next_static is not None or self._pending_due() is not None:
            # One call per occurrence, for a caller that needs to prove it is still alive while
            # the run is executing. A run's only other outward sign is its result, which arrives
            # minutes later -- long after anything watching would have concluded it had died.
            if self._on_progress is not None:
                self._on_progress()
            due = self._pending_due()
            if due is not None and (
                next_static is None or due.sort_key() <= next_static.sort_key()
            ):
                traces.append(self._dispatch_due(due))
                continue
            assert next_static is not None
            occurrence = next_static.occurrence
            next_static = next(static, None)
            traces.append(self._dispatch_static(occurrence))

        return self._finish(tuple(traces))

    def _start(self, cutoff: datetime) -> None:
        """What happens before the first occurrence; nothing, unless a subclass says otherwise."""

    def _pending_due(self) -> DueExecutionEnvelope | None:
        """The due item waiting to be dispatched, or `None`; a flow without fills has none."""
        return None

    def _dispatch_due(self, due: DueExecutionEnvelope) -> object:
        raise NotImplementedError("this flow mints no due items")

    def _dispatch_static(self, occurrence: OperationOccurrence) -> object:
        raise NotImplementedError

    def _finish(self, traces: tuple[object, ...]) -> object:
        raise NotImplementedError


__all__ = ["OccurrenceFlow"]
