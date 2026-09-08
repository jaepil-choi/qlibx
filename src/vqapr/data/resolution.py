"""Translate one declared DataRequirement field through the dataset that exposes it."""

from __future__ import annotations

from vqapr.data.datasets import DatasetRegistration
from vqapr.data.requirements import DataRequirement
from vqapr.domain.errors import Failure, Stage, Status, VqaprError


def resolve_field(registration: DatasetRegistration, requirement: DataRequirement) -> str:
    """The expression the named dataset exposes under the requirement's field id.

    A requirement names a dataset and a field, so this asks only the second half: the dataset was
    resolved by name before getting here. A field id is unique **within** a dataset and not across
    the workspace (`docs/issues/049`, the owner's 2026-09-01 correction), which is why the pair is
    what identifies a read.
    """
    expression = registration.fields.get(requirement.field_id)
    if expression is not None:
        return expression
    raise VqaprError(
        stage=Stage.RUN,
        failures=[
            Failure.bounded(
                code="store.field_missing",
                status=Status.MISSING,
                requirement=(
                    f"dataset {str(registration.dataset_id)!r} must expose the field a "
                    "requirement names"
                ),
                observed=(
                    f"missing={requirement.field_id!r}; "
                    f"exposed={sorted(registration.fields)!r}"
                ),
                fix=(
                    f"register {requirement.field_id!r} on dataset "
                    f"{str(registration.dataset_id)!r} under `fields`, or name a field it "
                    "already exposes"
                ),
            )
        ],
        mutation=False,
        retry_precondition="register the required field or change the requirement, then retry",
    )
