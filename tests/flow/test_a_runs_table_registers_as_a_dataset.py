"""A run's recorded table is a parquet directory, and it registers as a dataset as-is.

One-shape campaign Step 4 (`docs/refactoring/2026-09-04-the-one-shape-campaign.md` §1.4). The
publication machinery in `flow/materialize.py` existed to hand one strategy's output to another
strategy as a dataset. Record `146` made a run's tables parquet, and this is the third path that
made the first two redundant: register the directory. Pinned here so the path stays open after the
publishing one is gone -- the four ensemble showcases stand on it.

Two things the registration must say, because a record does not: `available_at` is `event_time`
(the decision instant the row was written at), and a `Decimal` is stored as text, so a numeric
field is `CAST`. `DECIMAL(38, 12)` is exact for a weight the optimiser placed on the `1e-12` grid.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from vqapr.data.store import DuckDbObservationStore
from vqapr.flow.record import RunRecordWriter
from vqapr.public import (
    DataRequirement,
    DatasetRegistration,
    ModelWindow,
    RowsLookback,
    SourceSpec,
    register_dataset,
)
from vqapr.workspace import Workspace

T1 = datetime(2024, 3, 5, 15, 30, tzinfo=UTC)
T2 = T1 + timedelta(days=1)


def _member_run(project: Path) -> Path:
    """Two sessions of `vqapr.weight`, written the way a run with a store writes them."""
    writer = RunRecordWriter(project / ".vqapr", "member", "rev@abcdef12")
    writer.open()
    writer.append(
        "vqapr.weight",
        [
            {"instrument": "A", "weight": Decimal("0.5"), "event_time": T1},
            {"instrument": "B", "weight": Decimal("0.5"), "event_time": T1},
        ],
    )
    writer.append(
        "vqapr.weight",
        [
            {"instrument": "A", "weight": Decimal("0.25"), "event_time": T2},
            {"instrument": "B", "weight": Decimal("0.75"), "event_time": T2},
        ],
    )
    writer.release()
    return (
        project / ".vqapr" / "runs" / "member" / "strategies" / "rev@abcdef12" / "tables"
        / "vqapr.weight"
    )


def _read(project: Path, at: datetime) -> dict[str, object]:
    requirement = DataRequirement.of("member_weights", "weight", lookback=RowsLookback(2))
    window = ModelWindow(
        evaluation_time=at,
        instruments=("A", "B"),
        store=DuckDbObservationStore(Workspace.open(project)),
        allowed_requirements=(requirement,),
        consumer_id="ensemble",
    )
    return window.panel([requirement], "weight").latest()


def test_a_runs_weight_table_is_read_by_the_next_run_point_in_time(tmp_path: Path) -> None:
    Workspace.create(tmp_path)
    directory = _member_run(tmp_path)

    registered = register_dataset(
        tmp_path,
        DatasetRegistration.of(
            "member_weights",
            "member-weights",
            instrument_field="instrument",
            available_at="event_time",
            key_fields=("event_time", "instrument"),
            fields={"weight": "CAST(weight AS DECIMAL(38, 12))"},
            grain="instrument_instant",
        ),
        SourceSpec.of("member-weights", directory),
    )

    assert registered is True
    # The newest decision, exactly as the member made it -- a Decimal, not a float.
    assert _read(tmp_path, T2 + timedelta(hours=1)) == {"A": Decimal("0.25"), "B": Decimal("0.75")}
    # And nothing from the second session is visible before it happened.
    assert _read(tmp_path, T1 + timedelta(hours=1)) == {"A": Decimal("0.5"), "B": Decimal("0.5")}
    assert _read(tmp_path, T1 - timedelta(hours=1)) == {}


def test_a_column_that_was_null_in_an_early_part_reads_with_its_later_type(tmp_path: Path) -> None:
    """The record writer's stated contract, held by the package's own reader.

    `run_records._arrow_table` writes a column that is all-null in a session as `null`-typed in
    that part and with its real type once a value appears, and says "every reader unions with the
    later type". `vqapr.account` does this on every run: `price` and `quantity` are null on the
    `_ACCOUNT` row, so a session with no position writes a `null`-typed part. The package's scan
    read the schema off whichever part sorted first, so the same directory registered or was
    refused by part order -- three of the four ensemble showcases hit it on first contact.
    """
    Workspace.create(tmp_path)
    writer = RunRecordWriter(tmp_path / ".vqapr", "member", "rev@abcdef12")
    writer.open()
    writer.append("vqapr.account", [{"instrument": "_ACCOUNT", "price": None, "event_time": T1}])
    writer.append(
        "vqapr.account",
        [
            {"instrument": "_ACCOUNT", "price": None, "event_time": T2},
            {"instrument": "A", "price": Decimal("100"), "event_time": T2},
        ],
    )
    writer.release()
    directory = (
        tmp_path / ".vqapr" / "runs" / "member" / "strategies" / "rev@abcdef12" / "tables"
        / "vqapr.account"
    )

    assert register_dataset(
        tmp_path,
        DatasetRegistration.of(
            "member_account",
            "member-account",
            instrument_field="instrument",
            available_at="event_time",
            key_fields=("event_time", "instrument"),
            fields={"price": "CAST(price AS DECIMAL(38, 12))"},
            grain="instrument_instant",
        ),
        SourceSpec.of("member-account", directory),
    ) is True

    requirement = DataRequirement.of("member_account", "price", lookback=RowsLookback(2))
    window = ModelWindow(
        evaluation_time=T2 + timedelta(hours=1),
        instruments=("A", "_ACCOUNT"),
        store=DuckDbObservationStore(Workspace.open(tmp_path)),
        allowed_requirements=(requirement,),
        consumer_id="ensemble",
    )
    assert window.panel([requirement], "price").latest() == {"A": Decimal("100")}
