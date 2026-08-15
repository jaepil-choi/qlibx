"""Portable references to committed framework-managed state and artifacts."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ModelStateRef:
    digest: str

    def __post_init__(self) -> None:
        if len(self.digest) != 64 or any(c not in "0123456789abcdef" for c in self.digest):
            raise ValueError("ModelStateRef digest must be a lowercase SHA-256 hex digest")
