"""Logical observation requirements declared by consumers."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from vqapr.data.lookback import Lookback
from vqapr.domain.identifiers import DatasetId, dataset_id

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
