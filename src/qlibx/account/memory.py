"""Legacy Strategy memory snapshot schema for v2/v3 checkpoint loading."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MemorySnapshot:
    strategy_id: str
    version: int
    value: object | None
    feedback_cursor: int
    commit_id: str | None = None


__all__ = ["MemorySnapshot"]
