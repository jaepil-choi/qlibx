from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta

from qlibx.account import JournalEntry
from qlibx.flow.recovery import SimulationRecoveryPoint


def point(sequence: int) -> SimulationRecoveryPoint:
    started = datetime(2024, 1, 1, tzinfo=UTC)
    event_time = started + timedelta(days=sequence)
    entry = JournalEntry(
        cursor=sequence,
        event_id=f"session-{sequence:08d}",
        as_of=event_time,
        change_type="MarkBatch",
    )
    return SimulationRecoveryPoint(
        run_id="scaling-v2",
        request_fingerprint="request",
        config_fingerprint="config",
        profile_fingerprint="profile",
        registry_fingerprint="registry",
        strategy_id="scaling-strategy",
        sequence=sequence,
        previous_recovery_artifact_id=(
            None if sequence == 0 else f"recovery-{sequence - 1:08d}"
        ),
        last_event_time=event_time,
        last_event_priority=20,
        last_event_name="MARK",
        account_id="scaling-account",
        account_base_currency="KRW",
        account_cash=1_000_000.0,
        account_instrument_ids=(),
        account_positions=(),
        account_version=sequence,
        account_as_of=event_time,
        account_journal_delta=(() if sequence == 0 else (entry,)),
        event_trace_delta=(() if sequence == 0 else (f"trace-{sequence:08d}",)),
        completed_decision_ids_delta=(
            () if sequence == 0 else (f"decision-{sequence:08d}",)
        ),
    )


def benchmark(session_count: int) -> dict[str, float | int]:
    points = tuple(point(index) for index in range(session_count + 1))
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
