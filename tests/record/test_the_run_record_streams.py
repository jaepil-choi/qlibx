"""A run with a store writes its rows as each event is accepted, and keeps none on the heap.

Campaign Step 3; the testbed's A4. `freeze_record` used to walk `final_state.recorder_rows`
after `flow.run()` returned, so a 2.6M-row table was 2.6M dicts on the heap until the end and a
killed run left nothing. The writer had always appended in chunks (`run-record-layout.md`); what
was missing was a caller that streamed. `RunStateRepository(sink=...)` is that caller's seam:
accepted rows go to the sink at the swap and no root retains them.

Two properties, asserted directly:

- each event's rows leave the roots at publish and the final state retains none; since
  `docs/issues/archive/087` the writer holds them as Arrow tables and writes once when the run ends,
  so the disk is untouched while the run executes;
- the peak heap of a streamed run is a fraction of the same run kept in memory -- measured with
  `tracemalloc`, not inferred from a row count. A columnar buffer is that fraction; the rows as
  Python dicts on the roots are the whole.

Without a sink nothing changes: rows stay in the roots and every in-memory reader sees them.
"""

from __future__ import annotations

import tracemalloc
from datetime import date, time, timedelta
from decimal import Decimal
from pathlib import Path

from vqapr.component.reference import ComponentRef
from vqapr.data.lookback import RowsLookback
from vqapr.data.requirement import DataRequirement
from vqapr.data.store import DuckDbObservationStore
from vqapr.data.window import ModelWindow
from vqapr.domain.account import Account, AccountMode, AccountSnapshot, AccountState
from vqapr.domain.instants import LocalInstantDeclaration
from vqapr.domain.schedule import ScheduledEvent
from vqapr.domain.wiring import Role
from vqapr.public import (
    Hold,
    StrategyModel,
    TableSpec,
)
from vqapr.record import TABLES_DIRECTORY, RunRecordWriter, read_table
from vqapr.run.engine.loop import RunLoop, strategy_loop
from vqapr.run.engine.run_state import RunStateRepository
from vqapr.run.preflight.frozen import FrozenRun, FrozenSchedule, FrozenStrategy
from vqapr.workspace.run_definition import ComplianceSet, StrategyConfig

ROWS_PER_OCCURRENCE = 200
PADDING = "x" * 100


class RecordsEveryEvent(StrategyModel):
    """Holds every time, and writes a fat chunk to its own table every time."""

    def tables(self) -> tuple[TableSpec, ...]:
        return (TableSpec("probe", ("n", "padding")),)

    def decide(self, call) -> Hold:
        count = int((self.memory or {}).get("count", 0)) + 1
        self.memory = {"count": count}
        assert self.recorder is not None
        self.recorder.append_batch(
            "probe",
            [
                {"n": count * ROWS_PER_OCCURRENCE + i, "padding": PADDING}
                for i in range(ROWS_PER_OCCURRENCE)
            ],
        )
        return Hold(reason="probe")


class _Catalog:
    def dataset(self, raw_dataset_id: str) -> object:
        raise AssertionError(f"unexpected dataset read: {raw_dataset_id}")

    def source(self, raw_source_id: str) -> object:
        raise AssertionError(f"unexpected source read: {raw_source_id}")


class _Exchange:
    def execute(self, *args: object) -> object:
        raise AssertionError("Hold callbacks must not execute orders")


def _component(raw_id: str, kind: Role) -> ComponentRef:
    return ComponentRef.of(raw_id, kind, Path("component.py"), "Component", fingerprint="0" * 64)


def _events(count: int) -> tuple[ScheduledEvent, ...]:
    first = date(2024, 1, 1)
    return tuple(
        ScheduledEvent(
            f"strategy-{number}",
            LocalInstantDeclaration(
                first + timedelta(days=number), time(4, 0), "Asia/Seoul", 0, "+09:00"
            ),
        )
        for number in range(1, count + 1)
    )


def _state(sink=None) -> RunStateRepository:
    return RunStateRepository(
        initial_account=AccountState(AccountSnapshot(0, Decimal(1), {})),
        sink=sink,
    )


def _flow(
    state: RunStateRepository, events: tuple[ScheduledEvent, ...], on_progress=None
) -> RunLoop:
    requirement = DataRequirement.of("prices", "close", lookback=RowsLookback(1))
    frozen = FrozenRun(
        run_id="test",
        strategy=FrozenStrategy(
                config=StrategyConfig(
                    _component("strategy", Role.STRATEGY_MODEL),
                    "strategy",
                ),
                compliance=ComplianceSet(()),
                schedule=FrozenSchedule("strategy", events),
            ),
        start=events[0].evaluation_time,
        end=events[-1].evaluation_time,
        initial_account_snapshot=AccountSnapshot(0, Decimal(1), {}),
        initial_account_mode=AccountMode.LONG_ONLY,
        instruments=("A",),
        writes="test-weights",
    )

    def window_for_event(event: ScheduledEvent) -> ModelWindow:
        return ModelWindow(
            evaluation_time=event.evaluation_time,
            instruments=("A",),
            store=DuckDbObservationStore(_Catalog()),
            allowed_requirements=(requirement,),
            consumer_id="test-consumer",
        )

    return strategy_loop(
        frozen,
        RecordsEveryEvent(),
        state,
        strategy_window_for_event=window_for_event,
        account=Account(mode=AccountMode.LONG_ONLY),
        exchange=_Exchange(),
        on_progress=on_progress,
    )


def test_rows_leave_the_roots_at_each_accepted_event_and_land_once_at_the_end(
    tmp_path: Path,
) -> None:
    """The sink takes each event's rows at publish and the roots keep none; the writer
    holds them typed in memory and writes one file per table when the run ends
    (`docs/issues/archive/087` -- record `146` wrote one file per event, a physical write per loop)."""
    writer = RunRecordWriter(tmp_path, "streamed")
    writer.open()
    table = writer.directory / TABLES_DIRECTORY / "probe"
    sizes: list[int] = []

    def observe() -> None:
        sizes.append(len(list(table.glob("*.parquet"))) if table.exists() else 0)

    state = _state(sink=writer.append_chunk)
    result = _flow(state, _events(3), on_progress=observe).run()

    assert len(sizes) == 3
    assert sizes == [0, 0, 0], "nothing reaches the disk while the run is executing"
    assert result.final_state.recorder_rows == {}, "a streamed run retains no rows on its roots"
    assert writer.counts()["probe"] == {"rows": 3 * ROWS_PER_OCCURRENCE, "instants": 3}

    writer.release()

    assert [path.name for path in table.iterdir()] == ["all.parquet"]
    assert sum(1 for _ in read_table(tmp_path, "streamed", "probe")) == 3 * ROWS_PER_OCCURRENCE


def test_without_a_sink_rows_stay_on_the_roots_as_before() -> None:
    result = _flow(_state(), _events(3)).run()

    assert len(result.final_state.recorder_rows["probe"]) == 3 * ROWS_PER_OCCURRENCE


def _peak_bytes(run) -> int:
    tracemalloc.start()
    try:
        run()
        return tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


def test_a_streamed_run_s_peak_heap_is_a_fraction_of_the_same_run_kept_in_memory(
    tmp_path: Path,
) -> None:
    """Measured, not inferred. Ratio, not a number: the floor is whatever the roots cost."""
    events = _events(40)

    in_memory = _peak_bytes(lambda: _flow(_state(), events).run())

    writer = RunRecordWriter(tmp_path, "streamed")
    writer.open()
    streamed = _peak_bytes(lambda: _flow(_state(sink=writer.append_chunk), events).run())

    assert streamed * 2 < in_memory, (
        f"streaming should remove the rows from the heap: {streamed} bytes streamed vs "
        f"{in_memory} bytes in memory"
    )
