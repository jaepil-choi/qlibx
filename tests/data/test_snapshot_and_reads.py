"""Reading a dataset, and reading one moment of it.

Two capabilities the framework had but did not hand over.

`Workspace.instruments()` / `.evaluation_times()` — the ability existed in `data/scan.py` and was
absent from the public surface, so the first external user resolved dataset -> source -> path and
opened parquet directly, in seven files. That binds user code to a storage decision the framework
declares is not part of its contract.

`ModelWindow.snapshot()` — a lookback returns a window, not a line. Even `RowsLookback(1)` returns
each instrument's own most recent row, and those rows do not share a date. Reading that window as
if it were one moment mixes dates silently, which is how a benchmark once summed above 1.0.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from vqapr.data.store import DuckDbObservationStore
from vqapr.data.windows import ModelWindow
from vqapr.public import (
    DataRequirement,
    DatasetRegistration,
    RowsLookback,
    SourceSpec,
    Workspace,
    register_dataset,
)

SESSIONS = tuple(datetime(2024, 1, day, 6, 30, tzinfo=UTC) for day in range(1, 6))
LEFT_AFTER = 2
"""GONE stops publishing after this many sessions, like a name leaving an index."""


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    rows: list[dict[str, object]] = []
    for index, stamp in enumerate(SESSIONS):
        rows.append({"available_at": stamp, "instrument": "LIVE", "weight": Decimal("0.6")})
        if index < LEFT_AFTER:
            # Its last published weight stays positive -- that is what makes the trap quiet.
            rows.append({"available_at": stamp, "instrument": "GONE", "weight": Decimal("0.4")})
    source = tmp_path / "benchmark.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            rows,
            schema=pa.schema(
                [
                    ("available_at", pa.timestamp("us", tz="UTC")),
                    ("instrument", pa.string()),
                    ("weight", pa.decimal128(18, 4)),
                ]
            ),
        ),
        source,
    )
    # Registered through the public entry point, which measures the span persistence requires.
    register_dataset(
        tmp_path,
        DatasetRegistration.of(
            "benchmark",
            "benchmark-source",
            instrument_field="instrument",
            available_at="available_at",
            key_fields=("available_at", "instrument"),
            fields={"weight": "weight"},
        ),
        SourceSpec.of("benchmark-source", source),
    )
    return Workspace.open(tmp_path)


def _window(space: Workspace, requirement: DataRequirement, at: datetime) -> ModelWindow:
    return ModelWindow(
        evaluation_time=at,
        instruments=("GONE", "LIVE"),
        store=DuckDbObservationStore(space),
        allowed_requirements=(requirement,),
        consumer_id="test-consumer",
    )


def test_a_dataset_reports_its_instruments_without_naming_a_file(workspace: Workspace) -> None:
    assert workspace.instruments("benchmark") == ("GONE", "LIVE")


def test_a_dataset_reports_its_evaluation_times(workspace: Workspace) -> None:
    """What an agenda should be built from: the sessions the data actually has."""
    assert workspace.evaluation_times("benchmark") == SESSIONS


def test_an_unregistered_dataset_is_refused_by_name(workspace: Workspace) -> None:
    from vqapr.domain.errors import VqaprError

    with pytest.raises(VqaprError, match="must be registered"):
        workspace.instruments("absent")


def test_a_lookback_window_carries_rows_from_different_dates(workspace: Workspace) -> None:
    """The trap itself, stated before the fix that closes it.

    GONE last published on session 2 and LIVE on session 5. A one-row lookback returns both,
    because each instrument's newest row is its own. Summing this reads a departed name's final
    weight as if it were current.
    """
    requirement = DataRequirement.of("weight", lookback=RowsLookback(1))

    batch = _window(workspace, requirement, SESSIONS[-1]).observations(requirement)

    dates = {str(row["instrument"]): row["available_at"] for row in batch.rows}
    assert dates["GONE"] == SESSIONS[LEFT_AFTER - 1]
    assert dates["LIVE"] == SESSIONS[-1]
    assert sum(row["weight"] for row in batch.rows) == Decimal("1.0000")


def test_a_snapshot_is_one_moment_and_drops_what_stopped_publishing(
    workspace: Workspace,
) -> None:
    """Same requirement, same window: only the newest cross-section survives."""
    requirement = DataRequirement.of("weight", lookback=RowsLookback(1))

    batch = _window(workspace, requirement, SESSIONS[-1]).snapshot(requirement)

    assert [str(row["instrument"]) for row in batch.rows] == ["LIVE"]
    assert sum(row["weight"] for row in batch.rows) == Decimal("0.6000")


def test_a_snapshot_keeps_every_name_that_published_at_the_same_moment(
    workspace: Workspace,
) -> None:
    """It is a cross-section, not a filter: evaluated early, both names are current."""
    requirement = DataRequirement.of("weight", lookback=RowsLookback(1))

    batch = _window(workspace, requirement, SESSIONS[LEFT_AFTER - 1]).snapshot(requirement)

    assert [str(row["instrument"]) for row in batch.rows] == ["GONE", "LIVE"]


def test_a_snapshot_still_records_the_access_it_made(workspace: Workspace) -> None:
    """Lineage does not change because the caller asked for one moment."""
    requirement = DataRequirement.of("weight", lookback=RowsLookback(1))
    window = _window(workspace, requirement, SESSIONS[-1])

    window.snapshot(requirement)

    assert len(window.accesses) == 1
    assert window.accesses[0].dataset_id == "benchmark"


def test_a_snapshot_refuses_an_undeclared_requirement(workspace: Workspace) -> None:
    """The declared-requirement boundary is the same one `observations` enforces."""
    from vqapr.domain.errors import VqaprError

    declared = DataRequirement.of("weight", lookback=RowsLookback(1))
    undeclared = DataRequirement.of("weight", lookback=RowsLookback(3))

    with pytest.raises(VqaprError, match="undeclared"):
        _window(workspace, declared, SESSIONS[-1]).snapshot(undeclared)
