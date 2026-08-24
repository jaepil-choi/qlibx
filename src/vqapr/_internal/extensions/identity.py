"""Schema-versioned identity for `vqapr` extension components.

Two schemas are implemented here, both versioned so a future incompatible change gets a new
name instead of silently reinterpreting old bytes:

- `vqapr.config/v1` — a canonical, type-tagged JSON encoding for extension config values. Every
  scalar and collection is tagged with its kind so `1`, `True`, `"1"`, and `Decimal("1")` never
  collide, mappings are recursively key-sorted by UTF-8 byte order, and list/tuple are distinct
  tagged arrays. `float`, `Path`, callables, `set`/`frozenset`, `bytes`, non-finite `Decimal`,
  and naive `datetime` are refused; nothing is silently coerced.
- `vqapr-extension-fingerprint/v1` — a fixed byte preimage built from eight-byte big-endian
  length-delimited fields, in order: extension kind, installed `vqapr` package version, full
  unmodified source-module bytes, qualname, and canonical config bytes. The fingerprint is the
  SHA-256 hex digest of that preimage. Human component name and filesystem path never
  participate, so renaming or relocating a component does not change its identity.

The opaque authority ID derived from a fingerprint is `extension/v1/<kind>/<full-lowercase-
digest>`; it carries no caller-supplied suffix and no digest truncation.

`stable_source_bytes` is the one place that decides whether a class is fingerprintable at all: it
requires an importable, module-level class backed by a real file on disk, and refuses a class
defined in a REPL, an `exec`/`eval` string, a local/nested scope, or a module with no source.
`verify_no_drift` re-derives a class's identity and raises if source, config, or the installed
package version has moved since the identity was captured — the check this module exists to make
possible right before a registered extension's callback runs.

Nothing in this module is part of the public `vqapr` API.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import struct
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from enum import StrEnum
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _distribution_version
from pathlib import Path
from typing import Final

_FINGERPRINT_SCHEMA: Final[str] = "vqapr-extension-fingerprint/v1"
_CONFIG_SCHEMA: Final[str] = "vqapr.config/v1"
_PACKAGE_NAME: Final[str] = "vqapr"


class ExtensionKind(StrEnum):
    """The three extension kinds the `v1` fingerprint schema covers."""

    DATA_MODEL = "data_model"
    STRATEGY_MODEL = "strategy_model"
    CONSTRAINT = "constraint"


@dataclass(frozen=True, slots=True, kw_only=True)
class ExtensionIdentity:
    """A captured `vqapr-extension-fingerprint/v1` identity for one extension class."""

    kind: ExtensionKind
    fingerprint: str
    authority_id: str


# --------------------------------------------------------------------------------------
# vqapr.config/v1 — canonical, type-tagged config encoding
# --------------------------------------------------------------------------------------


def _sort_key(key: str) -> bytes:
    return key.encode("utf-8")


def _encode_decimal(value: Decimal) -> dict[str, object]:
    if not value.is_finite():
        raise ValueError(f"{_CONFIG_SCHEMA} Decimal values must be finite, got {value!r}")
    sign, digits, exponent = value.as_tuple()
    if not isinstance(exponent, int):  # pragma: no cover - is_finite() already excludes this
        raise ValueError(f"{_CONFIG_SCHEMA} Decimal values must be finite, got {value!r}")
    magnitude = int("".join(str(digit) for digit in digits) or "0")
    coefficient = -magnitude if sign and magnitude != 0 else magnitude
    return {"t": "decimal", "v": [str(coefficient), exponent]}


def _encode_mapping(value: Mapping[object, object]) -> dict[str, object]:
    if any(not isinstance(key, str) for key in value):
        raise TypeError(f"{_CONFIG_SCHEMA} mapping keys must be strings")
    ordered = sorted(value.items(), key=lambda item: _sort_key(item[0]))
    return {"t": "map", "v": {key: _encode_value(item) for key, item in ordered}}


def _encode_value(value: object) -> object:
    if value is None:
        return None
    if isinstance(value, bool):
        return {"t": "bool", "v": value}
    if isinstance(value, int):
        return {"t": "int", "v": str(value)}
    if isinstance(value, Decimal):
        return _encode_decimal(value)
    if isinstance(value, str):
        return {"t": "str", "v": value}
    if isinstance(value, datetime):
        if value.utcoffset() is None:
            raise ValueError(f"{_CONFIG_SCHEMA} datetime values must be timezone-aware")
        return {"t": "datetime", "v": value.isoformat()}
    if isinstance(value, date):
        return {"t": "date", "v": value.isoformat()}
    if isinstance(value, time):
        return {"t": "time", "v": value.isoformat()}
    if isinstance(value, float):
        raise TypeError(f"{_CONFIG_SCHEMA} does not accept float values; use Decimal")
    if isinstance(value, Path):
        raise TypeError(f"{_CONFIG_SCHEMA} does not accept Path values")
    if isinstance(value, (bytes, bytearray)):
        raise TypeError(f"{_CONFIG_SCHEMA} does not accept bytes values")
    if isinstance(value, (set, frozenset)):
        raise TypeError(f"{_CONFIG_SCHEMA} does not accept set values")
    if isinstance(value, tuple):
        return {"t": "tuple", "v": [_encode_value(item) for item in value]}
    if isinstance(value, list):
        return {"t": "list", "v": [_encode_value(item) for item in value]}
    if isinstance(value, Mapping):
        return _encode_mapping(value)
    if callable(value):
        raise TypeError(f"{_CONFIG_SCHEMA} does not accept callable values")
    raise TypeError(f"{_CONFIG_SCHEMA} does not accept {type(value).__name__} values")


def canonical_config_bytes(config: Mapping[str, object] | None) -> bytes:
    """Encode `config` as canonical `vqapr.config/v1` UTF-8 JSON bytes.

    `config` must be a mapping with string keys; `None` encodes the same as an empty mapping.
    """
    payload = {} if config is None else config
    if not isinstance(payload, Mapping):
        raise TypeError(f"config must be a mapping, got {type(payload).__name__}")
    encoded = _encode_mapping(payload)
    return json.dumps(encoded, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode(
        "utf-8"
    )


# --------------------------------------------------------------------------------------
# stable source loading
# --------------------------------------------------------------------------------------


def stable_source_bytes(cls: type) -> bytes:
    """Read the full, unmodified source bytes of the module defining an importable top-level class.

    Refuses a class defined in a REPL, an `exec`/`eval` string, a local/nested scope, or a module
    with no file backing on disk — none of those can be re-read the same way on the next load, so
    none of them can produce a fingerprint stable across a process restart.
    """
    if not isinstance(cls, type):
        raise TypeError(f"stable_source_bytes requires a class, got {type(cls).__name__}")
    if "<locals>" in cls.__qualname__:
        raise ValueError(
            f"{cls.__qualname__} must be a module-level class, not one defined inside a "
            "function or method"
        )
    if cls.__qualname__ != cls.__name__:
        raise ValueError(
            f"{cls.__qualname__} must be a top-level class in its module, not nested in "
            "another class"
        )
    module = inspect.getmodule(cls)
    if module is None:
        raise ValueError(f"{cls.__qualname__} has no resolvable, importable defining module")
    module_file = getattr(module, "__file__", None)
    if not module_file:
        raise ValueError(
            f"{module.__name__} has no source file; a REPL, dynamically executed, or built-in "
            "module is not fingerprintable"
        )
    path = Path(module_file)
    try:
        return path.read_bytes()
    except OSError as error:
        raise ValueError(f"{module.__name__} source at {path} is not readable: {error}") from error


def installed_package_version(package: str = _PACKAGE_NAME) -> str:
    """The installed distribution version of `package` (default: `vqapr` itself)."""
    try:
        return _distribution_version(package)
    except PackageNotFoundError as error:
        raise ValueError(
            f"the {package!r} distribution must be installed to compute an extension fingerprint"
        ) from error


# --------------------------------------------------------------------------------------
# vqapr-extension-fingerprint/v1
# --------------------------------------------------------------------------------------


def _field(data: bytes) -> bytes:
    return struct.pack(">Q", len(data)) + data


def compute_fingerprint(
    *,
    kind: ExtensionKind,
    module_bytes: bytes,
    qualname: str,
    config: Mapping[str, object] | None = None,
    package_version: str | None = None,
) -> str:
    """Hash the v1 byte preimage and return its lowercase hexadecimal digest."""
    if not isinstance(kind, ExtensionKind):
        raise TypeError("kind must be an ExtensionKind")
    if not isinstance(module_bytes, (bytes, bytearray)):
        raise TypeError("module_bytes must be bytes")
    if not isinstance(qualname, str) or not qualname.strip():
        raise ValueError("qualname must be a non-empty string")
    version = package_version if package_version is not None else installed_package_version()
    canonical_config = canonical_config_bytes(config)
    digest = hashlib.sha256()
    digest.update(_field(kind.value.encode("ascii")))
    digest.update(_field(version.encode("utf-8")))
    digest.update(_field(bytes(module_bytes)))
    digest.update(_field(qualname.encode("utf-8")))
    digest.update(_field(canonical_config))
    return digest.hexdigest()


def authority_id(kind: ExtensionKind, fingerprint: str) -> str:
    """Derive the opaque `extension/v1/<kind>/<full-lowercase-digest>` authority ID.

    Human component name and filesystem path never contribute; two components with identical
    kind, source, qualname, config, and package version always derive the same authority ID.
    """
    if not isinstance(kind, ExtensionKind):
        raise TypeError("kind must be an ExtensionKind")
    if (
        not isinstance(fingerprint, str)
        or len(fingerprint) != 64
        or any(char not in "0123456789abcdef" for char in fingerprint)
    ):
        raise ValueError("fingerprint must be a lowercase SHA-256 hex digest")
    return f"extension/v1/{kind.value}/{fingerprint}"


def identify(
    cls: type,
    *,
    kind: ExtensionKind,
    config: Mapping[str, object] | None = None,
) -> ExtensionIdentity:
    """Fingerprint an importable, module-level class and derive its opaque authority ID."""
    module_bytes = stable_source_bytes(cls)
    fingerprint = compute_fingerprint(
        kind=kind, module_bytes=module_bytes, qualname=cls.__qualname__, config=config
    )
    return ExtensionIdentity(
        kind=kind, fingerprint=fingerprint, authority_id=authority_id(kind, fingerprint)
    )


def verify_no_drift(
    cls: type,
    identity: ExtensionIdentity,
    *,
    config: Mapping[str, object] | None = None,
) -> None:
    """Re-derive `cls`'s identity and raise if source, config, or package version has moved.

    Call this immediately before invoking a registered extension's callback so a source edit or
    package upgrade made between registration and the callback is caught before it can run,
    rather than silently executing under a fingerprint that no longer describes it.
    """
    current = identify(cls, kind=identity.kind, config=config)
    if current.fingerprint != identity.fingerprint:
        raise ValueError(
            f"{cls.__qualname__} fingerprint drift: registered={identity.fingerprint}, "
            f"current={current.fingerprint}"
        )
