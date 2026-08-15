"""Committed Model-memory storage used by the Flow invocation boundary."""

from __future__ import annotations

import hashlib
import json

from vqapr.domain.references import ModelStateRef
from vqapr.models.memory import ModelMemory, normalize_memory


class InMemoryModelStateStore:
    """Deterministic test/local store; committed snapshots are detached from Model objects."""

    def __init__(self) -> None:
        self._states: dict[ModelStateRef, ModelMemory] = {}
        self._commit_count = 0

    @property
    def commit_count(self) -> int:
        return self._commit_count

    def commit(self, memory: object) -> ModelStateRef:
        normalized = normalize_memory(memory)
        encoded = json.dumps(
            normalized,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        ref = ModelStateRef(hashlib.sha256(encoded).hexdigest())
        self._states[ref] = normalize_memory(normalized)
        self._commit_count += 1
        return ref

    def load(self, ref: ModelStateRef) -> ModelMemory:
        if not isinstance(ref, ModelStateRef):
            raise TypeError("ref must be a ModelStateRef")
        try:
            memory = self._states[ref]
        except KeyError as exc:
            raise KeyError(f"unknown ModelStateRef: {ref.digest}") from exc
        return normalize_memory(memory)
