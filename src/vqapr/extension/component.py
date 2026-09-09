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
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType

from pydantic import BaseModel, ConfigDict, field_serializer, field_validator

from vqapr.domain.identifiers import ComponentId, component_id
from vqapr.domain.values import ModelMemory, normalize_memory


class ComponentKind(StrEnum):
    DATA_MODEL = "data_model"
    STRATEGY_MODEL = "strategy_model"
    EXCHANGE = "exchange"
    COMPLIANCE = "compliance"


class ComponentRef(BaseModel):
    """A registered component: where the code is, what it is, and its fingerprint.

    Also `components.<component_id>` of `workspace.yaml`, read and written as-is (one-shape
    campaign Step 5): the field order below is the stored key order, `component_id` is the key
    the entry sits under and is excluded on dump, `kind` is stored as the enum's value and
    `path` as the string it was registered with. `config` is read-only once built, so a
    reference handed out by the workspace cannot be edited underneath a frozen run (record
    `145` stopped copying references on every read; the object itself keeps the promise).
    """

    model_config = ConfigDict(
        extra="forbid", frozen=True, strict=False, arbitrary_types_allowed=True
    )

    component_id: ComponentId
    kind: ComponentKind
    path: Path
    object_name: str
    config: Mapping[str, ModelMemory] = MappingProxyType({})
    fingerprint: str

    @field_validator("component_id", mode="before")
    @classmethod
    def _clean_id(cls, value: object) -> object:
        return component_id(value) if isinstance(value, str) else value

    @field_validator("object_name")
    @classmethod
    def _named(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("object_name must be a non-empty string")
        return value

    @field_validator("fingerprint")
    @classmethod
    def _hex_digest(cls, value: str) -> str:
        if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
            raise ValueError("fingerprint must be a lowercase SHA-256 hex digest")
        return value

    @field_validator("config", mode="before")
    @classmethod
    def _normalized(cls, value: object) -> object:
        normalized = normalize_memory(dict(value or {}))  # type: ignore[arg-type]
        if not isinstance(normalized, dict):  # pragma: no cover - dict construction guarantees it
            raise TypeError("config must normalize to an object")
        return normalized

    @field_validator("config", mode="after")
    @classmethod
    def _read_only(cls, value: Mapping[str, ModelMemory]) -> Mapping[str, ModelMemory]:
        # After, not before: pydantic rebuilds a `Mapping` field as a plain dict once it has
        # validated it, which is exactly the mutable copy record `145` removed. Wrapping here is
        # what keeps `workspace.component(id).config["x"] = 1` a TypeError and a frozen run
        # detached from the workspace without copying on every read.
        return MappingProxyType(dict(value))

    @field_serializer("path")
    def _path_as_written(self, path: Path) -> str:
        return str(path)

    @field_serializer("config")
    def _config_as_dict(self, config: Mapping[str, ModelMemory]) -> dict[str, ModelMemory]:
        return dict(config)

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
        # Raw values in, the `mode="before"` validators above make them the fields' types.
        return cls.model_validate(
            {
                "component_id": raw_component_id,
                "kind": kind,
                "path": Path(path),
                "object_name": object_name,
                "config": config or {},
                "fingerprint": fingerprint,
            }
        )
