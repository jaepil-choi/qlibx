"""Strict YAML primitives shared by config-driven services.

These helpers are used at four different points of the journey -- registering data, writing
an execution profile, authoring a Strategy manifest, loading a project -- and a malformed
file means something different at each. `for_stage` binds them to the stage the calling
module serves, so a failure sends the agent to the step it was actually working on rather
than to a generic "your YAML is wrong".
"""

from __future__ import annotations

from collections.abc import Callable
from functools import cache, partial
from pathlib import Path
from typing import Any, NamedTuple

import yaml

from qlibx.errors import QlibxError, Stage


class UniqueKeyLoader(yaml.SafeLoader):
    pass


def _mapping(loader: UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
    loader.flatten_mapping(node)
    value: dict[Any, Any] = {}
    for key_node, item_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in value:
            raise QlibxError(
                getattr(loader, "stage", "PROJECT"),
                f"Duplicate YAML key: {key!r}",
                expected="Each key appears exactly once in a project YAML mapping.",
            )
        value[key] = loader.construct_object(item_node, deep=deep)
    return value


UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


@cache
def _loader_for(stage: Stage) -> type[UniqueKeyLoader]:
    """A loader that knows which journey step its file belongs to.

    PyYAML constructs mappings deep inside its own call stack, so the stage cannot be passed
    down as an argument. Binding it to the loader class keeps a duplicate key reported
    against the step the agent was working on.
    """
    name = f"UniqueKeyLoader{stage.title().replace('_', '')}"
    return type(name, (UniqueKeyLoader,), {"stage": stage})


def read_yaml(path: str | Path, *, stage: Stage = "PROJECT") -> dict[str, Any]:
    selected = Path(path)
    if not selected.is_file():
        raise QlibxError(
            stage,
            f"Missing YAML config: {selected}",
            expected="The declared YAML file exists and is readable.",
            context={"path": str(selected)},
        )
    try:
        value = yaml.load(selected.read_text(encoding="utf-8"), Loader=_loader_for(stage))
    except yaml.YAMLError as error:
        raise QlibxError(
            stage,
            f"Invalid YAML in {selected}: {error}",
            expected="The file parses as YAML.",
            context={"path": str(selected), "raised": type(error).__name__},
        ) from error
    return require_mapping(value, str(selected), stage=stage)


def require_mapping(value: Any, field: str, *, stage: Stage = "PROJECT") -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise QlibxError(
            stage,
            f"{field} must be a string-keyed mapping",
            expected="A YAML mapping with string keys.",
            context={"field": field, "observed": type(value).__name__},
        )
    return value


def require_string(value: Any, field: str, *, stage: Stage = "PROJECT") -> str:
    if not isinstance(value, str) or not value.strip():
        raise QlibxError(
            stage,
            f"{field} must be a non-empty string",
            expected="An explicitly declared, non-empty string.",
            context={"field": field, "observed": type(value).__name__},
        )
    return value


def require_strings(value: Any, field: str, *, stage: Stage = "PROJECT") -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise QlibxError(
            stage,
            f"{field} must be a non-empty list",
            expected="A YAML list with at least one string entry.",
            context={"field": field, "observed": type(value).__name__},
        )
    return tuple(require_string(item, f"{field}[]", stage=stage) for item in value)


class YamlReaders(NamedTuple):
    """The YAML primitives, bound to one journey stage."""

    read_yaml: Callable[..., dict[str, Any]]
    require_mapping: Callable[..., dict[str, Any]]
    require_string: Callable[..., str]
    require_strings: Callable[..., tuple[str, ...]]


def for_stage(stage: Stage) -> YamlReaders:
    """Bind the YAML readers to the stage the calling module serves.

    Declared once at the top of a module so every failure it produces names the same step,
    instead of the stage being repeated at each of the dozens of call sites.
    """
    return YamlReaders(
        partial(read_yaml, stage=stage),
        partial(require_mapping, stage=stage),
        partial(require_string, stage=stage),
        partial(require_strings, stage=stage),
    )


__all__ = [
    "UniqueKeyLoader",
    "YamlReaders",
    "for_stage",
    "read_yaml",
    "require_mapping",
    "require_string",
    "require_strings",
]
