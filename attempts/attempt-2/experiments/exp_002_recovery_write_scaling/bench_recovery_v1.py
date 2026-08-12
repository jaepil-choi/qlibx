from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta

from qlibx.account import AccountCheckpoint, JournalEntry
from qlibx.flow.recovery import SimulationRecoveryPointV1


def point(session_count: int) -> SimulationRecoveryPointV1:
    started = datetime(2024, 1, 1, tzinfo=UTC)
    journal = tuple(
        JournalEntry(
            cursor=index,
            event_id=f"session-{index:08d}",
            as_of=started + timedelta(days=index),
            change_type="MarkBatch",
        )
        for index in range(1, session_count + 1)
    )
    checkpoint = AccountCheckpoint(
        account_id="scaling-account",
        base_currency="KRW",
        cash=1_000_000.0,
        instrument_ids=(),
        positions=(),
        version=session_count,
        applied_events=tuple(entry.event_id for entry in journal),
        journal=journal,
        as_of=journal[-1].as_of,
    )
    return SimulationRecoveryPointV1(
        run_id="scaling-v1",
        request_fingerprint="request",
        config_fingerprint="config",
        profile_fingerprint="profile",
        registry_fingerprint="registry",
        strategy_id="scaling-strategy",
        sequence=session_count,
        last_event_time=journal[-1].as_of,
        last_event_priority=20,
        last_event_name="MARK",
        account_checkpoint=checkpoint,
        event_trace=tuple(f"trace-{index:08d}" for index in range(1, session_count + 1)),
        completed_decision_ids=tuple(
            f"decision-{index:08d}" for index in range(1, session_count + 1)
        ),
    )


def benchmark(session_count: int) -> dict[str, float | int]:
    points = tuple(point(index) for index in range(1, session_count + 1))
    started = time.perf_counter()
    payloads = tuple(item.model_dump_json().encode("utf-8") for item in points)
    elapsed = time.perf_counter() - started
    return {
        "sessions": session_count,
        "last_point_bytes": len(payloads[-1]),
        "total_bytes": sum(map(len, payloads)),
        "serialization_seconds": elapsed,
    }


if __name__ == "__main__":
    print(json.dumps([benchmark(count) for count in (10, 25, 50, 100)], indent=2))
