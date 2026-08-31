"""Frozen references to validated project-local components.

This module is the extension component-reference authority, and `vqapr.extension.component` is
where it lives.

**It was not always.** Until record `110` the implementation sat in
`vqapr._internal.extensions.component`
with a four-line forwarding shim at this path, whose docstring promised deletion "when the
internal-transition closes". That promise was made in a file marked temporary and was still true six
months later, by which point a boundary test pinned the shim's existence. Record `110` discharged it
the other way: the shim's path became the real module's path, so no caller changed a line and the
temporary file stopped existing rather than being renewed. See
`docs/design/agent-first-surface.md` for the surface ruling this serves.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from vqapr.domain.identifiers import ComponentId, component_id
from vqapr.models.memory import ModelMemory, normalize_memory


class ComponentKind(StrEnum):
    DATA_MODEL = "data_model"
    STRATEGY_MODEL = "strategy_model"
    EXCHANGE = "exchange"
    CONSTRAINT = "constraint"


@dataclass(frozen=True, slots=True)
class ComponentRef:
    component_id: ComponentId
    kind: ComponentKind
    path: Path
    object_name: str
    config: Mapping[str, ModelMemory]
    fingerprint: str

    @classmethod
    def of(
        cls,
        raw_component_id: str,
        kind: ComponentKind,
        path: str | Path,
        object_name: str,
        *,
        config: Mapping[str, object] | None = None,
        fingerprint: str,
    ) -> ComponentRef:
        if not isinstance(kind, ComponentKind):
            raise TypeError("kind must be a ComponentKind")
        if not isinstance(object_name, str) or not object_name.strip():
            raise ValueError("object_name must be a non-empty string")
        if (
            not isinstance(fingerprint, str)
            or len(fingerprint) != 64
            or any(char not in "0123456789abcdef" for char in fingerprint)
        ):
            raise ValueError("fingerprint must be a lowercase SHA-256 hex digest")
        normalized = normalize_memory(dict(config or {}))
        if not isinstance(normalized, dict):  # pragma: no cover - dict construction guarantees it
            raise TypeError("config must normalize to an object")
        return cls(
            component_id(raw_component_id),
            kind,
            Path(path),
            object_name,
            normalized,
            fingerprint,
        )
