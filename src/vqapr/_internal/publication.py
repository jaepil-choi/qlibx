"""Crash-safe publication: verified immutable objects, then one visibility swap.

Publication has exactly two phases, and the order between them is the whole design.

First every payload is staged as a content-addressed object: written to a temp file,
fsynced, re-read and digest-verified, then atomically installed. An object existing on
disk grants it nothing - it is not reachable through any supported read.

Second, and only after every object is durable, one catalog-root compare-and-swap adds
all of the publication's bindings together. That single swap is the only visibility
authority in the system, which is what makes the failure modes clean:

- a crash before the swap leaves unreferenced objects and a fully intact old root;
- a crash after the swap leaves a root whose every referenced digest was already
  verified on disk before the root ever mentioned it.

There is no window in which a catalog references an object that is absent or partial,
and no window in which one output of a publication is visible without its companions.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from vqapr._internal.catalog import Catalog, root_digest
from vqapr._internal.catalog_store import CatalogConflict, commit_catalog, read_catalog
from vqapr._internal.objects import stage_object

__all__ = (
    "PublicationConflict",
    "PublishedOutput",
    "PublishedRun",
    "publish_outputs",
)


class PublicationConflict(Exception):
    """A publication lost the root CAS. No output of it became visible."""

    def __init__(self, expected_generation: int, observed_generation: int):
        super().__init__(
            f"publication conflict: expected generation {expected_generation}, "
            f"observed {observed_generation}"
        )
        self.expected_generation = expected_generation
        self.observed_generation = observed_generation
        self.mutation = False


@dataclass(frozen=True, slots=True, kw_only=True)
class PublishedOutput:
    """One logical output selected for publication."""

    output_id: str
    payload: bytes
    metadata: Mapping[str, object]

    def __post_init__(self) -> None:
        if not isinstance(self.output_id, str) or not self.output_id:
            raise ValueError("output_id must be a non-empty string")
        if any(ch.isspace() for ch in self.output_id):
            raise ValueError("output_id must not contain whitespace")
        if not isinstance(self.payload, bytes):
            raise TypeError("payload must be bytes")
        if not isinstance(self.metadata, Mapping):
            raise TypeError("metadata must be a mapping")


@dataclass(frozen=True, slots=True, kw_only=True)
class PublishedRun:
    """What one atomic publication made visible."""

    generation: int
    output_ids: tuple[str, ...]
    digests: Mapping[str, str]

    def __post_init__(self) -> None:
        if isinstance(self.generation, bool) or not isinstance(self.generation, int):
            raise TypeError("generation must be an integer")
        if not isinstance(self.output_ids, tuple) or not self.output_ids:
            raise ValueError("output_ids must be a non-empty tuple")


def publish_outputs(
    root: Path,
    outputs: Sequence[PublishedOutput],
    *,
    expected_generation: int | None = None,
    expected_root_digest: str | None = None,
) -> PublishedRun:
    """Stage every object, then make all of them visible in exactly one root swap.

    `expected_generation`/`expected_root_digest` default to the snapshot read here. Passing
    them explicitly is how a caller proves it prepared against a specific root, so a
    concurrent publisher cannot slip between its preparation and its commit.
    """
    if not isinstance(outputs, Sequence) or isinstance(outputs, (str, bytes)) or not outputs:
        raise ValueError("outputs must be a non-empty sequence of PublishedOutput")
    for item in outputs:
        if not isinstance(item, PublishedOutput):
            raise TypeError("every output must be a PublishedOutput")

    output_ids = tuple(item.output_id for item in outputs)
    if len(set(output_ids)) != len(output_ids):
        raise ValueError("outputs must not repeat an output_id")

    snapshot = read_catalog(root)
    generation = snapshot.generation if expected_generation is None else expected_generation
    digest = root_digest(snapshot) if expected_root_digest is None else expected_root_digest

    # Every requested id must be absent in the snapshot the CAS will be checked against:
    # a publication never silently replaces an already-visible output.
    for output_id in output_ids:
        if output_id in snapshot.publications:
            raise ValueError(f"output {output_id!r} is already published")

    # Phase one: durable, verified objects. Nothing is visible yet.
    digests: dict[str, str] = {}
    for item in outputs:
        digests[item.output_id] = stage_object(root, item.payload)

    # Phase two: one candidate carrying every binding, installed by one CAS.
    candidate = snapshot
    for item in outputs:
        candidate = candidate.with_binding(
            "publications",
            item.output_id,
            {
                "output_id": item.output_id,
                "digest": digests[item.output_id],
                "metadata": dict(item.metadata),
            },
        )
    candidate = candidate.with_objects(tuple(digests.values()))

    try:
        committed = commit_catalog(
            root,
            candidate=candidate,
            expected_generation=generation,
            expected_root_digest=digest,
        )
    except CatalogConflict as conflict:
        # The staged objects survive as unreferenced orphans. They are harmless: logical
        # output identity lives in the catalog, so a retry is never blocked by them, and
        # the grace-period sweep reclaims them later.
        raise PublicationConflict(
            conflict.expected_generation, conflict.observed_generation
        ) from conflict

    return PublishedRun(
        generation=committed.generation,
        output_ids=output_ids,
        digests=digests,
    )


def referenced_digests(catalog: Catalog) -> set[str]:
    """Every content digest the catalog currently references."""
    return set(catalog.object_digests)
