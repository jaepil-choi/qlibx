"""Turn an authored extension class into the engine's registered component.

The engine reaches a strategy, data model or constraint through a `ComponentRef`: an id,
a kind, a source file, an object name, a config and a fingerprint. The public
`ExtensionDeclaration` carries the class itself instead, because an author should hand
over the thing they wrote rather than a description of where it lives.

Recovering a file path and object name from a class is therefore this module's job, and it
is deliberately strict about it. A class defined in a REPL, inside a function, or in a
module whose source cannot be read has no stable location, so it cannot be registered.
Refusing that up front is the whole point: a component whose source cannot be re-read is a
component whose fingerprint cannot be re-verified before a callback, and silent drift is
the failure this identity contract exists to prevent.
"""

from __future__ import annotations

import inspect
from collections.abc import Mapping
from pathlib import Path
from typing import Any

__all__ = ("component_ref_for", "extension_kind_for", "register_extension")


def extension_kind_for(cls: type) -> Any:
    """Classify an authored class by which authoring contract it implements."""
    from vqapr.authoring import Constraint, DataModel, StrategyModel
    from vqapr.extension.identity import ExtensionKind

    if issubclass(cls, StrategyModel):
        return ExtensionKind.STRATEGY_MODEL
    if issubclass(cls, DataModel):
        return ExtensionKind.DATA_MODEL
    if issubclass(cls, Constraint):
        return ExtensionKind.CONSTRAINT
    raise TypeError(
        f"{cls.__name__} implements no authoring contract; expected a subclass of "
        "vqapr.authoring.DataModel, StrategyModel, or Constraint"
    )


def _stable_location(cls: type) -> tuple[Path, str]:
    """The source file and object name a component can be re-read from.

    Rejects anything whose source cannot be re-read later: the fingerprint is recomputed
    from module bytes immediately before each callback, so a class without a stable file
    would make that check impossible rather than merely inconvenient.
    """
    qualname = cls.__qualname__
    if "<locals>" in qualname or "<lambda>" in qualname:
        raise ValueError(
            f"{qualname} is defined inside another scope and has no stable import "
            "location; define it at module level to register it"
        )
    try:
        source = inspect.getsourcefile(cls)
    except TypeError as error:
        raise ValueError(f"{qualname} has no readable source file") from error
    if not source:
        raise ValueError(f"{qualname} has no readable source file")
    path = Path(source)
    if not path.is_file():
        raise ValueError(f"{qualname} resolves to {source!r}, which is not a regular file")
    return path, qualname


def component_ref_for(
    cls: type,
    *,
    component_id: str,
    config: Mapping[str, object] | None = None,
    kind: Any | None = None,
) -> Any:
    """Build the engine's `ComponentRef` for one class.

    `kind` is normally derived from the authoring contract the class implements. An
    already-adapted, legacy-shaped class implements none of them, so its caller passes the
    kind explicitly rather than defeating the check that exists to catch a genuinely
    unregisterable class.
    """
    from vqapr.extension.component import ComponentKind, ComponentRef
    from vqapr.extension.fingerprint import fingerprint_component

    if not isinstance(cls, type):
        raise TypeError("cls must be a class")
    if not isinstance(component_id, str) or not component_id:
        raise ValueError("component_id must be a non-empty string")

    component_kind = kind if kind is not None else ComponentKind(extension_kind_for(cls).value)
    path, object_name = _stable_location(cls)

    # Deliberately the same function the loader re-verifies with. Computing identity here
    # by any other route would register a digest the loader then rejects as drift - which
    # is exactly the failure that surfaced when this used `identify` instead.
    fingerprint = fingerprint_component(
        path,
        kind=component_kind,
        object_name=object_name,
        config=config,
    )

    return ComponentRef.of(
        component_id,
        component_kind,
        path,
        object_name,
        config=dict(config) if config else None,
        fingerprint=fingerprint,
    )


def register_extension(
    root: Path, declaration: Any, *, component_id: str | None = None
) -> Any:
    """Register one `ExtensionDeclaration` with the engine and return its `ComponentRef`.

    `component_id` defaults to the declaration's human name, which is diagnostics text and
    never enters identity - identity comes from the class's own source bytes and canonical
    config, so two declarations naming the same class with the same config are the same
    component regardless of what they are called.
    """
    from vqapr.public import register_component

    reference = component_ref_for(
        declaration.extension,
        component_id=component_id or declaration.name,
        config=declaration.config,
    )
    register_component(root, reference)
    return reference
