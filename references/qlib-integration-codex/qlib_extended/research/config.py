from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class UniqueKeyLoader(yaml.SafeLoader):
    """같은 YAML mapping의 duplicate key를 거부합니다."""


def _construct_unique_mapping(
    loader: UniqueKeyLoader,
    node: yaml.MappingNode,
    deep: bool = False,
) -> dict[Any, Any]:
    loader.flatten_mapping(node)
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            source = getattr(loader.stream, "name", "<yaml>")
            raise ValueError(f"Duplicate YAML key in {source}: {key!r}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def read_yaml_mapping(path: Path) -> dict[str, Any]:
    """YAML fragment를 mapping으로 읽고 shape가 다르면 실패합니다."""

    if not path.is_file():
        raise FileNotFoundError(f"Missing config fragment: {path}")
    with path.open("r", encoding="utf-8") as file:
        value = yaml.load(file, Loader=UniqueKeyLoader) or {}
    if not isinstance(value, dict):
        raise ValueError(f"Config fragment must be a mapping: {path}")
    return value


def require_mapping(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not value:
        raise ValueError(f"{path} must be a non-empty mapping.")
    return value


def require_string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path} must be a non-empty string.")
    return value


def require_string_list(value: Any, path: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{path} must be a non-empty list.")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"{path} must contain only non-empty strings.")
    return value


def optional_string(value: Any, path: str) -> str | None:
    if value is None:
        return None
    return require_string(value, path)
