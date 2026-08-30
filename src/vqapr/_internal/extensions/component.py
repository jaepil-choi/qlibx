"""Frozen references to validated project-local components.

Internal-transition: this is the physical home of the component-reference authority.
`vqapr.extension.component` is a temporary forwarding adapter over this module and is the ONLY door
callers in `src/` use to reach it; do not add new logic to the adapter, and do not import this
module directly from outside `_internal/`. Both halves of that rule, and the conditions the hard
deletion is admitted under, are in `docs/design/agent-first-surface.md`. Stated by document rather
than by goal id: this note pinned the deletion to a goal id until 2026-08-30, by which time that
id named a different, completed goal (`docs/issues/029`).
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
