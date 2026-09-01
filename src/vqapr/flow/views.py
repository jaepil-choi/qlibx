"""Flow-owned construction of the restricted views passed into Models."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from vqapr.data.requirements import DataRequirement
from vqapr.data.store import DuckDbObservationStore
from vqapr.data.windows import ModelWindow
from vqapr.workspace import Workspace


def data_model_window(
    workspace: Workspace,
    *,
    evaluation_time: datetime,
    instruments: Sequence[str],
    requirements: Sequence[DataRequirement],
    consumer_id: str,
    store: DuckDbObservationStore | None = None,
) -> ModelWindow:
    """Build the sole observation capability exposed for one DataModel invocation.

    A caller driving many evaluation times in sequence passes one ``store`` for the whole
    sequence, as ``public.run()`` does for a simulation. Building one per evaluation is correct
    but pays twice: it re-hashes the source for its digest, and it denies
    ``scan.observation_rows`` the session it needs before it will bound a ``RowsLookback`` -- so
    without one, every evaluation ranks a window function across the source's whole history.
    """
    return ModelWindow(
        evaluation_time=evaluation_time,
        instruments=instruments,
        store=DuckDbObservationStore(workspace) if store is None else store,
        allowed_requirements=requirements,
        consumer_id=consumer_id,
    )
