"""Resolve a declared field id to the dataset that exposes it."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from vqapr.data.datasets import DatasetRegistration
from vqapr.domain.errors import ExplainTopic, Failure, FailureFamily, VqaprError

_STAGE = "observation_store.resolve"


def field_index(
    registrations: Iterable[DatasetRegistration],
) -> dict[str, DatasetRegistration]:
    """field id -> the dataset that declares it.

    A field id is an id, unique across the workspace, which is what lets a `DataRequirement` name
    one and nothing else (`docs/issues/049`). Registration is what keeps it so -- it refuses an id
    another dataset already exposes, naming that dataset -- so a later collision here would mean
    the workspace was written past that refusal. It is not re-litigated: last wins, and the
    registration path is where the question is asked.
    """
    return {
        field_id: registration
        for registration in registrations
        for field_id in registration.fields
    }


def dataset_for_field(
    index: Mapping[str, DatasetRegistration], field_id: str
) -> DatasetRegistration:
    """The dataset exposing `field_id`, or a refusal that names what this workspace does expose."""
    registration = index.get(field_id)
    if registration is not None:
        return registration
    raise VqaprError(
        stage=_STAGE,
        family=FailureFamily.DATA,
        failures=[
            Failure.bounded(
                code=f"{_STAGE}.field_unknown",
                requirement=(
                    "a DataRequirement must name a field some registered dataset exposes"
                ),
                observed=f"{field_id!r}; exposed: {', '.join(sorted(index)) or '(none)'}",
                fix=(
                    f"register a dataset that exposes {field_id!r} under `fields`, or change the "
                    "DataRequirement to name a field this workspace already has"
                ),
                explain=ExplainTopic.DATASET_PREPARATION,
            )
        ],
        mutation=False,
        retry_precondition="register the field or change the requirement, then retry",
    )
