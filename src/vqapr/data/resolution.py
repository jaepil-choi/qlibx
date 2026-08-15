"""Translate logical DataRequirement fields through one registered dataset declaration."""

from __future__ import annotations

from vqapr.data.datasets import DatasetRegistration
from vqapr.data.requirements import DataRequirement
from vqapr.domain.errors import Failure, FailureFamily, VqaprError

_STAGE = "observation_store.resolve"


def resolve_fields(
    registration: DatasetRegistration, requirement: DataRequirement
) -> dict[str, str]:
    missing = tuple(field for field in requirement.fields if field not in registration.fields)
    if missing:
        raise VqaprError(
            stage=_STAGE,
            family=FailureFamily.DATA,
            failures=[
                Failure.bounded(
                    code=f"{_STAGE}.field_missing",
                    requirement=(
                        f"dataset {registration.dataset_id!r} must expose every requested "
                        "framework "
                        "field"
                    ),
                    observed=f"missing={list(missing)!r}; exposed={sorted(registration.fields)!r}",
                )
            ],
            mutation=False,
            retry_precondition="register the required fields or change the requirement, then retry",
        )
    return {field: registration.fields[field] for field in requirement.fields}
