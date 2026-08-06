"""Committed Strategy memory authority."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MemorySnapshot:
    strategy_id: str
    version: int
    value: object | None
    feedback_cursor: int
    commit_id: str | None = None


class StrategyMemoryStore:
    """CAS store kept separate from actual investment state."""

    def __init__(self) -> None:
        self._snapshots: dict[str, MemorySnapshot] = {}

    def snapshot(self, strategy_id: str) -> MemorySnapshot:
        return self._snapshots.get(
            strategy_id,
            MemorySnapshot(strategy_id=strategy_id, version=0, value=None, feedback_cursor=0),
        )

    def checkpoint(self) -> tuple[MemorySnapshot, ...]:
        """Return a deterministic, portable snapshot of every committed strategy."""

        return tuple(self._snapshots[key] for key in sorted(self._snapshots))

    @classmethod
    def from_checkpoint(
        cls,
        snapshots: tuple[MemorySnapshot, ...],
    ) -> "StrategyMemoryStore":
        """Restore Memory CAS authority without fabricating unconfirmed feedback."""

        restored = cls()
        for snapshot in snapshots:
            if snapshot.strategy_id in restored._snapshots:
                raise ValueError("duplicate Strategy memory checkpoint")
            if snapshot.version < 0 or snapshot.feedback_cursor < 0:
                raise ValueError("invalid Strategy memory checkpoint")
            restored._snapshots[snapshot.strategy_id] = snapshot
        return restored

    def commit(
        self,
        *,
        strategy_id: str,
        value: object,
        feedback_cursor: int,
        expected_version: int,
        commit_id: str | None = None,
    ) -> MemorySnapshot:
        current = self.snapshot(strategy_id)
        if commit_id is not None and current.commit_id == commit_id:
            if current.value != value or current.feedback_cursor != feedback_cursor:
                raise ValueError("Strategy memory commit identity has conflicting content")
            return current
        if current.version != expected_version:
            raise ValueError("stale Strategy memory version")
        if feedback_cursor < current.feedback_cursor:
            raise ValueError("Strategy memory feedback cursor cannot move backwards")
        updated = MemorySnapshot(
            strategy_id=strategy_id,
            version=current.version + 1,
            value=value,
            feedback_cursor=feedback_cursor,
            commit_id=commit_id,
        )
        self._snapshots[strategy_id] = updated
        return updated
