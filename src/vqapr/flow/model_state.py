"""Canonical detached Model state candidates owned by the run-state root."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from vqapr.domain.references import ModelStateRef
from vqapr.models.memory import ModelMemory, normalize_memory


@dataclass(frozen=True, slots=True)
class PreparedModelState:
    """A detached state candidate with no visibility until its root is published."""

    ref: ModelStateRef
    memory: ModelMemory
    payload: bytes


def prepare_model_state(memory: object, payload: bytes) -> PreparedModelState:
    """Detach one exact memory/payload envelope without making it visible."""
    if not isinstance(payload, bytes):
        raise TypeError("payload must be bytes")
    normalized = normalize_memory(memory)
    memory_bytes = json.dumps(
        normalized,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    envelope = (
        len(memory_bytes).to_bytes(8, "big")
        + memory_bytes
        + len(payload).to_bytes(8, "big")
        + payload
    )
    return PreparedModelState(
        ref=ModelStateRef(hashlib.sha256(envelope).hexdigest()),
        memory=normalized,
        payload=bytes(payload),
    )
