"""Canonical serialization, hashing, and name primitives shared by stateful services.

Every durable identity in qlibx (research records, artifacts, registrations, skill and
instruction plans, frozen strategy invocations) is derived from these functions. Keeping
one implementation keeps those identities comparable across modules.

Two canonical forms exist because they answer different questions:

- ``digest_document`` hashes JSON-shaped metadata -- manifests, configs, plans. Anything
  it cannot encode falls back to ``str``, which is fine for provenance text.
- ``digest_dataset`` hashes values that carry pandas structure. It encodes index,
  columns, dtypes and missingness explicitly so two frames that merely *print* the same
  do not collide. Use it for reproducibility identities over data.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pandas as pd

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


def digest_document(value: Any) -> str:
    """Digest JSON-shaped metadata: manifests, configs, publication plans."""
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


def normalize_dataset(value: Any) -> Any:
    """Describe a value structurally so equal-looking pandas objects hash differently.

    Index, columns, dtypes and missingness are encoded explicitly; missing values of
    every flavour collapse to ``None`` so ``NaN``/``pd.NA`` compare equal.
    """
    if isinstance(value, pd.DataFrame):
        return {
            "type": "dataframe",
            "columns": [normalize_dataset(item) for item in value.columns.tolist()],
            "index": [normalize_dataset(item) for item in value.index.tolist()],
            "dtypes": [str(item) for item in value.dtypes.tolist()],
            "values": [
                [normalize_dataset(item) for item in row]
                for row in value.astype(object).where(value.notna(), None).values.tolist()
            ],
        }
    if isinstance(value, pd.Series):
        return {
            "type": "series",
            "name": normalize_dataset(value.name),
            "index": [normalize_dataset(item) for item in value.index.tolist()],
            "dtype": str(value.dtype),
            "values": [
                normalize_dataset(item) for item in value.astype(object).where(value.notna(), None)
            ],
        }
    if isinstance(value, Mapping):
        return {str(key): normalize_dataset(item) for key, item in sorted(value.items(), key=str)}
    if isinstance(value, (tuple, list)):
        return [normalize_dataset(item) for item in value]
    if hasattr(value, "__dataclass_fields__"):
        fields = value.__dataclass_fields__
        return {name: normalize_dataset(getattr(value, name)) for name in fields}
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item") and callable(value.item):
        try:
            return value.item()
        except ValueError:
            pass
    if isinstance(value, float) and pd.isna(value):
        return None
    if value is pd.NA:
        return None
    return value


def digest_dataset(value: Any) -> str:
    """Digest a value carrying pandas structure: decision contexts, strategy results."""
    return digest_bytes(
        json.dumps(
            normalize_dataset(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def validate_name(name: str, *, kind: str = "artifact") -> str:
    """Require a lowercase, filesystem-safe identifier for stored payload names."""
    if not name or any(character not in NAME_ALPHABET for character in name):
        raise ValueError(f"invalid {kind} name: {name}")
    return name


__all__ = [
    "canonical_bytes",
    "digest_bytes",
    "digest_dataset",
    "digest_document",
    "digest_file",
    "digest_text",
    "normalize_dataset",
    "validate_name",
]
