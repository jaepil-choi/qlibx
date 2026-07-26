from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path
from typing import Any, Callable, Mapping


def stable_hash(value: Any) -> str:
    payload = json.dumps(
        _json_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def deterministic_run_id(kind: str, definition: Mapping[str, Any]) -> str:
    return f"{kind}-{stable_hash(definition)[:32]}"


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def callable_fingerprint(callable_object: Callable[..., Any]) -> str:
    module = inspect.getmodule(callable_object)
    source_path = inspect.getsourcefile(callable_object)
    return stable_hash(
        {
            "module": None if module is None else module.__name__,
            "qualname": getattr(callable_object, "__qualname__", repr(callable_object)),
            "source_hash": None if source_path is None else file_hash(Path(source_path)),
        }
    )


def _json_value(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)
