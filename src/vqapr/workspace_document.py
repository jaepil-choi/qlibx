"""The workspace document and the declaration document, as pydantic models.

One model per YAML section: the shape a section has on disk (`workspace.yaml`) and in a
declaration an author registers. Key sets, scalar types, enums, dates and times are the model's
field declarations; pydantic checks them, and `declarations.refusals_from` turns what it finds
into this package's refusals. Nothing here opens a file, resolves a path or looks another
section up -- a model is a shape, and the cross-reference checks stay with the workspace.

Record `145` (deletion campaign Step 4): these models replace the hand-written `_decode` /
`_encode` / `_detach_*` in `workspace_codec.py` and the `_require_keys` / `_mapping` / `_enum`
family in `declarations.py`, one section at a time. Where the stored shape and the domain
dataclass coincide, `to_domain` is a one-liner; where they differ (a dataset's measured span, an
agenda's occurrences, a run's initial account) the model is the one place the mapping is written.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from vqapr.data.sources import SourceSpec


class Document(BaseModel):
    """Every section model: frozen, and an unknown key is a refusal rather than a warning."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=False)


class SourceDocument(Document):
    """`sources.<source_id>` on disk, and the inline `source:` block of a dataset declaration.

    `path` is a string here: on disk it is whatever the registration recorded, in a declaration
    it is relative to the declaration file, and resolving it is the declaration reader's job.
    """

    path: str
    hive_partitioned: bool = False

    def to_domain(self, source_id: str) -> SourceSpec:
        return SourceSpec.of(source_id, self.path, hive_partitioned=self.hive_partitioned)

    @classmethod
    def from_domain(cls, source: SourceSpec) -> SourceDocument:
        return cls(path=str(source.path), hive_partitioned=source.hive_partitioned)


__all__ = ["Document", "SourceDocument"]
