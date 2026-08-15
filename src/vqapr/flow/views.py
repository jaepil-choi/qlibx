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
) -> ModelWindow:
    """Build the sole observation capability exposed for one DataModel invocation."""
    return ModelWindow(
        evaluation_time=evaluation_time,
        instruments=instruments,
        store=DuckDbObservationStore(workspace),
        allowed_requirements=requirements,
    )
