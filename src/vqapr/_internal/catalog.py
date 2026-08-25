"""The transactional catalog: a detached immutable value plus its read-only view.

`Catalog` replaces `Workspace` as the state root a `Project` reads and CAS-commits. It carries
no I/O of its own — see `catalog_store.py` for the file-backed non-mutating read and CAS commit.
Every mapping a `Catalog` exposes is deeply read-only so a caller can never mutate committed
state through an aliased reference.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from types import MappingProxyType

CATALOG_SCHEMA = "vqapr.catalog/v1"

_BINDING_KINDS = ("datasets", "execution_inputs", "extensions", "publications")
_SINGULAR = {
    "datasets": "dataset",
    "execution_inputs": "execution input",
    "extensions": "extension",
    "publications": "publication",
}


def _has_whitespace(value: str) -> bool:
    return any(character.isspace() for character in value)


def _validate_binding_key(key: object, kind: str) -> str:
    if not isinstance(key, str):
        raise TypeError(f"{kind} key must be a str, got {type(key).__name__}")
    if not key:
        raise ValueError(f"{kind} key must not be empty")
    if _has_whitespace(key):
        raise ValueError(f"{kind} key {key!r} must not contain whitespace")
    return key


def _is_valid_digest(digest: object) -> bool:
    return (
        isinstance(digest, str)
        and len(digest) == 64
        and all(character in "0123456789abcdef" for character in digest)
    )


def _deep_freeze(value: object) -> object:
    """Recursively replace every mapping/sequence with a read-only, detached equivalent."""
    if isinstance(value, Mapping):
        return MappingProxyType({key: _deep_freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_deep_freeze(item) for item in value)
    return value


def _to_jsonable(value: object) -> object:
    """Undo `_deep_freeze` for serialization: MappingProxyType -> dict, tuple -> list."""
    if isinstance(value, Mapping):
        return {key: _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_to_jsonable(item) for item in value]
    return value


@dataclass(frozen=True, slots=True, kw_only=True)
class Catalog:
    """A detached, immutable snapshot of everything a project has committed.

    `generation` and the root digest of `canonical_bytes(self)` together form the CAS token a
    writer must present unchanged to commit a candidate built from this snapshot.
    """

    schema: str
    generation: int
    datasets: Mapping[str, Mapping[str, object]]
    execution_inputs: Mapping[str, Mapping[str, object]]
    extensions: Mapping[str, Mapping[str, object]]
    publications: Mapping[str, Mapping[str, object]]
    object_digests: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.schema != CATALOG_SCHEMA:
            raise ValueError(f"catalog schema must be {CATALOG_SCHEMA!r}, got {self.schema!r}")
        if isinstance(self.generation, bool) or not isinstance(self.generation, int):
            raise TypeError("generation must be a non-negative int")
        if self.generation < 0:
            raise ValueError("generation must be non-negative")

        for kind in _BINDING_KINDS:
            raw = getattr(self, kind)
            if not isinstance(raw, Mapping):
                raise TypeError(f"{kind} must be a mapping, got {type(raw).__name__}")
            frozen: dict[str, object] = {}
            for key, binding_value in raw.items():
                checked_key = _validate_binding_key(key, kind)
                if not isinstance(binding_value, Mapping):
                    raise TypeError(f"{kind}[{checked_key!r}] value must be a mapping")
                frozen[checked_key] = _deep_freeze(binding_value)
            object.__setattr__(self, kind, MappingProxyType(dict(sorted(frozen.items()))))

        digests = self.object_digests
        if not isinstance(digests, (tuple, list, set, frozenset)):
            raise TypeError("object_digests must be a sequence of content digests")
        seen: set[str] = set()
        for digest in digests:
            if not _is_valid_digest(digest):
                raise ValueError(f"invalid content digest: {digest!r}")
            if digest in seen:
                raise ValueError(f"duplicate content digest: {digest!r}")
            seen.add(digest)
        object.__setattr__(self, "object_digests", tuple(sorted(seen)))

    @classmethod
    def empty(cls) -> Catalog:
        return cls(
            schema=CATALOG_SCHEMA,
            generation=0,
            datasets={},
            execution_inputs={},
            extensions={},
            publications={},
            object_digests=(),
        )

    def with_binding(self, kind: str, key: str, value: Mapping[str, object]) -> Catalog:
        """Return a NEW catalog with `key` bound to `value` under `kind`.

        Registering the identical canonical value for an already-bound key is idempotent
        (returns an equal catalog, `self` itself). Registering a different value for an
        already-bound key raises `ValueError` — bindings never silently overwrite.
        """
        if kind not in _BINDING_KINDS:
            raise ValueError(f"kind must be one of {_BINDING_KINDS!r}, got {kind!r}")
        checked_key = _validate_binding_key(key, kind)
        if not isinstance(value, Mapping):
            raise TypeError(f"{kind} value must be a mapping, got {type(value).__name__}")
        frozen_value = _deep_freeze(value)

        current = getattr(self, kind)
        existing = current.get(checked_key)
        if existing is not None:
            if existing == frozen_value:
                return self
            raise ValueError(
                f"{_SINGULAR[kind]} {checked_key!r} is already registered with a different value"
            )

        updated = dict(current)
        updated[checked_key] = frozen_value
        return replace(self, **{kind: updated})

    def with_objects(self, digests: object) -> Catalog:
        """Return a new catalog referencing `digests` in addition to those already referenced."""
        if not isinstance(digests, (list, tuple, set, frozenset)):
            raise TypeError("digests must be a sequence of content digests")
        combined = set(self.object_digests) | set(digests)
        return replace(self, object_digests=tuple(combined))


class CatalogView:
    """The only interface private validation/scan/loader/preflight code may receive.

    Wraps one `Catalog` snapshot with lookup-only access. There is deliberately no method here
    that can mutate the wrapped catalog or the view itself.
    """

    __slots__ = ("_catalog",)

    def __init__(self, catalog: Catalog) -> None:
        if not isinstance(catalog, Catalog):
            raise TypeError(f"CatalogView requires a Catalog, got {type(catalog).__name__}")
        object.__setattr__(self, "_catalog", catalog)

    @property
    def generation(self) -> int:
        return self._catalog.generation

    def dataset(self, dataset_id: str) -> Mapping[str, object]:
        return self._lookup("datasets", dataset_id)

    def execution_input(self, execution_input_id: str) -> Mapping[str, object]:
        return self._lookup("execution_inputs", execution_input_id)

    def extension(self, extension_id: str) -> Mapping[str, object]:
        return self._lookup("extensions", extension_id)

    def publication(self, publication_id: str) -> Mapping[str, object]:
        return self._lookup("publications", publication_id)

    def has_object(self, digest: str) -> bool:
        return digest in self._catalog.object_digests

    def _lookup(self, kind: str, key: str) -> Mapping[str, object]:
        bindings = getattr(self._catalog, kind)
        try:
            return bindings[key]
        except KeyError:
            raise KeyError(
                f"no {_SINGULAR[kind]} registered for id {key!r}"
            ) from None


def canonical_bytes(catalog: Catalog) -> bytes:
    """Deterministic UTF-8 JSON for `catalog`, independent of any binding insertion order.

    Keys are sorted at every level (Python's `str` ordering matches UTF-8 byte order because
    UTF-8 is designed to preserve codepoint ordering), and there is no insignificant whitespace.
    """
    if not isinstance(catalog, Catalog):
        raise TypeError(f"canonical_bytes requires a Catalog, got {type(catalog).__name__}")
    document = {
        "schema": catalog.schema,
        "generation": catalog.generation,
        "datasets": _to_jsonable(catalog.datasets),
        "execution_inputs": _to_jsonable(catalog.execution_inputs),
        "extensions": _to_jsonable(catalog.extensions),
        "publications": _to_jsonable(catalog.publications),
        "object_digests": list(catalog.object_digests),
    }
    return json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def root_digest(catalog: Catalog) -> str:
    return hashlib.sha256(canonical_bytes(catalog)).hexdigest()


EMPTY_V1 = root_digest(Catalog.empty())
"""The canonical root digest of the empty catalog — the CAS token a fresh project starts from."""
