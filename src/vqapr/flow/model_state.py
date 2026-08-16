"""Committed Model-memory storage used by the Flow invocation boundary."""

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


class InMemoryModelStateStore:
    """Deterministic test/local store; committed snapshots are detached from Model objects."""

    def __init__(self) -> None:
        self._states: dict[ModelStateRef, ModelMemory] = {}
        self._commit_count = 0

    @property
    def commit_count(self) -> int:
        return self._commit_count

    def prepare(self, memory: object) -> PreparedModelState:
        """Serialize and detach state without making its reference loadable."""
        normalized = normalize_memory(memory)
        encoded = json.dumps(
            normalized,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        ref = ModelStateRef(hashlib.sha256(encoded).hexdigest())
        return PreparedModelState(ref=ref, memory=normalized)

    def publish(self, candidate: PreparedModelState) -> ModelStateRef:
        """Publish a previously prepared state for the legacy standalone store."""
        if not isinstance(candidate, PreparedModelState):
            raise TypeError("candidate must be a PreparedModelState")
        self._states[candidate.ref] = normalize_memory(candidate.memory)
        self._commit_count += 1
        return candidate.ref

    def commit(self, memory: object) -> ModelStateRef:
        """Prepare then publish for existing non-atomic callers."""
        return self.publish(self.prepare(memory))

    def load(self, ref: ModelStateRef) -> ModelMemory:
        if not isinstance(ref, ModelStateRef):
            raise TypeError("ref must be a ModelStateRef")
        try:
            memory = self._states[ref]
        except KeyError as exc:
            raise KeyError(f"unknown ModelStateRef: {ref.digest}") from exc
        return normalize_memory(memory)
