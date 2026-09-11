"""What a consumer declares it reads, and how that resolves to a physical column.

A `DataRequirement` is one field of one dataset with a past-only lookback, declared by the
consumer that reads it. `resolve_field` translates the requested field through the dataset that
exposes it; a field the dataset does not declare is refused by name.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from vqapr.data.dataset import DatasetRegistration
from vqapr.data.lookback import Lookback
from vqapr.domain.errors import Failure, Stage, Status, VqaprError
from vqapr.domain.identifiers import DatasetId, dataset_id

__all__ = [
    "DataRequirement",
    "resolve_field",
]


_RESERVED_FIELDS = frozenset({"available_at", "instrument"})


def _name(kind: str, raw: str) -> str:
    if not isinstance(raw, str):
        raise TypeError(f"{kind} must be a string")
    if not raw or any(character.isspace() for character in raw):
        raise ValueError(f"{kind} must be non-empty without whitespace")
    return raw


class DataRequirement(BaseModel):
    """One dataset, one field, and how far back to read it (`docs/issues/049`).

    **A dataset and a field, because a field id is not an id on its own.** The ruling in `049`
    removed `dataset_id` on the grounds that a field id is unique across a workspace; measured
    against this package's principal consumer that premise did not hold — 21 of its 27 datasets'
    field ids are exposed by more than one of them, some as deliberately schema-identical parallel
    series and some because `fiscal_yyyymm` is simply what that column is called wherever it
    appears. The owner overturned that half of the ruling on 2026-09-01. The pair is the id.

    **No `consumer_id`, and that half of the ruling stands.** The component that declares a
    requirement *is* the consumer, so the framework stamps it rather than asking the author to
    repeat what it already knows. It still reaches `AccessRecord` exactly as before -- see
    `ModelWindow.for_consumer`.

    **One field, not a tuple.** Requirements are all declared before any read, so expressions over
    one dataset fuse into a single scan; asking for one field at a time therefore does not
    multiply scans (`docs/issues/046`).

    `of` is the door: it cleans the raw ids and refuses a field the window owns. The keyword
    constructor takes ids already cleaned; the lookback is checked at both.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    dataset_id: DatasetId
    field_id: str
    lookback: Lookback

    @classmethod
    def of(cls, raw_dataset_id: str, raw_field_id: str, *, lookback: Lookback) -> DataRequirement:
        field_id = _name("framework field", raw_field_id)
        if field_id in _RESERVED_FIELDS:
            raise ValueError(f"framework field is reserved by ModelWindow: {field_id!r}")
        return cls(dataset_id=dataset_id(raw_dataset_id), field_id=field_id, lookback=lookback)


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
