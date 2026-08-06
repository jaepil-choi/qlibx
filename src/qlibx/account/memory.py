"""Committed Strategy memory authority."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MemorySnapshot:
    strategy_id: str
    version: int
    value: object | None
    feedback_cursor: int


class StrategyMemoryStore:
    """CAS store kept separate from actual investment state."""

    def __init__(self) -> None:
        self._snapshots: dict[str, MemorySnapshot] = {}

    def snapshot(self, strategy_id: str) -> MemorySnapshot:
        return self._snapshots.get(
            strategy_id,
            MemorySnapshot(strategy_id=strategy_id, version=0, value=None, feedback_cursor=0),
        )

    def commit(
        self,
        *,
        strategy_id: str,
        value: object,
        feedback_cursor: int,
        expected_version: int,
    ) -> MemorySnapshot:
        current = self.snapshot(strategy_id)
        if current.version != expected_version:
            raise ValueError("stale Strategy memory version")
        if feedback_cursor < current.feedback_cursor:
            raise ValueError("Strategy memory feedback cursor cannot move backwards")
        updated = MemorySnapshot(
            strategy_id=strategy_id,
            version=current.version + 1,
            value=value,
            feedback_cursor=feedback_cursor,
        )
        self._snapshots[strategy_id] = updated
        return updated
