"""Strict YAML primitives shared by config-driven services."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from qlibx.errors import QlibxError


class UniqueKeyLoader(yaml.SafeLoader):
    pass


def _mapping(loader: UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
    loader.flatten_mapping(node)
    value: dict[Any, Any] = {}
    for key_node, item_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in value:
            raise QlibxError(
                "QLIBX_INVALID_YAML_DUPLICATE_KEY",
                f"Duplicate YAML key: {key!r}",
                action="Keep exactly one definition for each key.",
            )
        value[key] = loader.construct_object(item_node, deep=deep)
    return value


UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def read_yaml(path: str | Path) -> dict[str, Any]:
    selected = Path(path)
    if not selected.is_file():
        raise QlibxError(
            "QLIBX_NOT_FOUND_CONFIG",
            f"Missing YAML config: {selected}",
            action="Create the declared YAML file.",
        )
    try:
        value = yaml.load(selected.read_text(encoding="utf-8"), Loader=UniqueKeyLoader)
    except yaml.YAMLError as error:
        raise QlibxError(
            "QLIBX_INVALID_CONFIG_VALUE",
            f"Invalid YAML in {selected}: {error}",
            action="Fix the YAML syntax.",
        ) from error
    return require_mapping(value, str(selected))


def require_mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise QlibxError(
            "QLIBX_INVALID_CONFIG_MAPPING",
            f"{field} must be a string-keyed mapping",
            action="Use YAML key/value syntax.",
        )
    return value


def require_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise QlibxError(
            "QLIBX_INVALID_CONFIG_STRING",
            f"{field} must be a non-empty string",
            action="Declare the value explicitly.",
        )
    return value


def require_strings(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise QlibxError(
            "QLIBX_INVALID_CONFIG_LIST",
            f"{field} must be a non-empty list",
            action="Declare at least one string entry.",
        )
    return tuple(require_string(item, f"{field}[]") for item in value)
