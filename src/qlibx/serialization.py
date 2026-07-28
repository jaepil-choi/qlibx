"""Canonical serialization, hashing, and name primitives shared by stateful services.

Every durable identity in qlibx (research records, artifacts, registrations, skill and
instruction plans) is derived from these functions. Keeping one implementation keeps
those identities comparable across modules.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

READ_BLOCK_SIZE = 1024 * 1024
NAME_ALPHABET = frozenset("abcdefghijklmnopqrstuvwxyz0123456789_")


def canonical_bytes(value: Any) -> bytes:
    """Serialize to stable, sorted, separator-free UTF-8 JSON."""
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def digest_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def digest_value(value: Any) -> str:
    return digest_bytes(canonical_bytes(value))


def digest_text(value: str) -> str:
    return digest_bytes(value.encode("utf-8"))


def digest_file(path: Path) -> str:
    """Digest a file in bounded blocks so large Parquet payloads stay streamable."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(READ_BLOCK_SIZE), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_name(name: str, *, kind: str = "artifact") -> str:
    """Require a lowercase, filesystem-safe identifier for stored payload names."""
    if not name or any(character not in NAME_ALPHABET for character in name):
        raise ValueError(f"invalid {kind} name: {name}")
    return name


__all__ = [
    "canonical_bytes",
    "digest_bytes",
    "digest_file",
    "digest_text",
    "digest_value",
    "validate_name",
]
