"""Content fingerprints for project-local extension components.

This module is the extension fingerprint authority, and `vqapr.component.fingerprint` is where
it lives.

**It was not always.** Until record `110` the implementation sat in
`vqapr._internal.extensions.fingerprint`
with a four-line forwarding shim at this path, whose docstring promised deletion "when the
internal-transition closes". That promise was made in a file marked temporary and was still true six
months later, by which point a boundary test pinned the shim's existence. Record `110` discharged it
the other way: the shim's path became the real module's path, so no caller changed a line and the
temporary file stopped existing rather than being renewed. See
`docs/design/agent-first-surface.md` for the surface ruling this serves.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path

from vqapr.component.reference import ComponentKind
from vqapr.domain.memory import normalize_memory


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
