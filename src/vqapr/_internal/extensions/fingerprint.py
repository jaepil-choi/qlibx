"""Deterministic project-local component source fingerprinting.

Internal-transition: this is the physical home of the component fingerprint authority.
`vqapr.extension.fingerprint` is a temporary forwarding adapter over this module and is the ONLY
door callers in `src/` use to reach it; do not add new logic to the adapter, and do not import this
module directly from outside `_internal/`. Both halves of that rule, and the conditions the hard
deletion is admitted under, are in `docs/design/agent-first-surface.md`. Stated by document rather
than by goal id: this note pinned the deletion to a goal id until 2026-08-30, by which time that
id named a different, completed goal (`docs/issues/029`).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path

from vqapr._internal.extensions.component import ComponentKind
from vqapr.models.memory import normalize_memory


def fingerprint_component(
    path: str | Path,
    *,
    kind: ComponentKind,
    object_name: str,
    config: Mapping[str, object] | None = None,
) -> str:
    target = Path(path)
    source = target.read_bytes()
    normalized = normalize_memory(dict(config or {}))
    metadata = json.dumps(
        {
            "kind": str(kind),
            "object_name": object_name,
            "config": normalized,
        },
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256()
    digest.update(metadata)
    digest.update(b"\0")
    digest.update(source)
    return digest.hexdigest()
