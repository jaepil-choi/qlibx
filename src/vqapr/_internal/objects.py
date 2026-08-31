"""Content-addressed immutable object store rooted at ``.vqapr/objects/sha256/<digest>``.

Internal-transition: this module implements the "Crash-safe content-addressed publication"
mechanism from the candidate-catalog transactional design. An object landing on disk here does
NOT make it catalog-visible; visibility belongs solely to the catalog root swap that a peer
module (`catalog.py` / `catalog_store.py`) owns. This module's only job is to guarantee that
every object that lands under `objects/sha256/` is complete and digest-verified, and that a
crash mid-write never leaves a corrupt or partial object at a final digest path.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from pathlib import Path

from vqapr._internal import atomic

OBJECT_SCHEMA = "vqapr.objects/v1"

_OBJECTS_DIRECTORY = ".vqapr"
_OBJECTS_SUBPATH = ("objects", "sha256")
_DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _require_digest(digest: str) -> str:
    if not isinstance(digest, str) or not _DIGEST_PATTERN.match(digest):
        raise ValueError("digest must be exactly 64 lowercase hex characters")
    return digest


def _objects_directory(root: Path) -> Path:
    return Path(root) / _OBJECTS_DIRECTORY / Path(*_OBJECTS_SUBPATH)


def object_path(root: Path, digest: str) -> Path:
    """Path an installed object with `digest` occupies, whether or not it exists yet."""
    _require_digest(digest)
    return _objects_directory(root) / digest


def has_object(root: Path, digest: str) -> bool:
    """Whether an object file exists at `digest`'s path (existence only, no verification)."""
    _require_digest(digest)
    return object_path(root, digest).is_file()


def read_object(root: Path, digest: str) -> bytes:
    """Read and digest-verify the object at `digest`; raises if the bytes do not hash to it."""
    _require_digest(digest)
    path = object_path(root, digest)
    payload = path.read_bytes()
    observed = hashlib.sha256(payload).hexdigest()
    if observed != digest:
        raise ValueError(
            f"object at {path} is corrupt: expected digest {digest}, observed {observed}"
        )
    return payload


def stage_object(root: Path, payload: bytes) -> str:
    """Write `payload` to the content-addressed store, returning its sha256 digest.

    Idempotent: re-staging identical bytes does not rewrite the installed file. If a file is
    already installed at the target digest path but its bytes do not hash to that digest, this
    is corruption and is never silently repaired -- it raises instead of overwriting.
    """
    if not isinstance(payload, bytes):
        raise TypeError("payload must be bytes")
    digest = hashlib.sha256(payload).hexdigest()
    directory = _objects_directory(root)
    final_path = directory / digest
    if final_path.is_file():
        existing = final_path.read_bytes()
        observed = hashlib.sha256(existing).hexdigest()
        if observed != digest:
            raise ValueError(
                f"object at {final_path} is corrupt: expected digest {digest}, observed "
                f"{observed}"
            )
        return digest

    directory.mkdir(parents=True, exist_ok=True)

    def verify(written: bytes) -> None:
        """Re-read what actually landed on disk and check it before installing.

        This is the crash-safety boundary of a content-addressed store: anything that goes wrong
        before this point leaves only an orphaned temp file, never a corrupt object at the final
        digest path. It is this store's invariant rather than a property of writing files, which
        is why the shared writer takes it as a hook instead of charging every caller for it.
        """
        observed = hashlib.sha256(written).hexdigest()
        if observed != digest:
            raise ValueError(
                f"staged object failed verification before install: expected digest {digest}, "
                f"observed {observed}"
            )

    atomic.write_atomically(final_path, payload, verify=verify)
    return digest


def stage_many(root: Path, payloads: Sequence[bytes]) -> tuple[str, ...]:
    """Stage each payload in order, returning digests in the same order as `payloads`."""
    return tuple(stage_object(root, payload) for payload in payloads)
