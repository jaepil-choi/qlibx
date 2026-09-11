"""A run's panel is scanned over the run's horizon and holds each numeric field once.

`docs/issues/098`, record `235`. A datamodel run's memory tracked the instrument count and not
its period: the panel was scanned over the registered span whatever the run covered, and held
each numeric field twice (an Arrow copy beside the numpy block). Now the store scans from the
earliest instant any lookback the run declared on that dataset reaches at `start`, up to `end`;
a numeric field is one `(instants x names)` float64 block, `matrix()` a view of its rows, and a
window the panel never read is refused rather than truncated.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
import numpy as np
import pytest

from vqapr.data import store as store_module
from vqapr.data.dataset import DatasetRegistration
from vqapr.data.lookback import CalendarLookback, RowsLookback
from vqapr.data.requirement import DataRequirement
from vqapr.data.source import SourceSpec
from vqapr.data.store import DuckDbObservationStore
from vqapr.data.window import ModelWindow
from vqapr.public import register_dataset
from vqapr.workspace.registry import Workspace

KST = ZoneInfo("Asia/Seoul")
DATASET = "prices_typed"


def _at(day: int, hour: int = 15, minute: int = 30) -> datetime:
    return datetime(2024, 3, day, hour, minute, tzinfo=KST)


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    """Five sessions, two names; B has no row on the 6th; `shares` is null for A on the 5th."""
    parquet = tmp_path / "prices.parquet"
    duckdb.connect().execute(
        "COPY (SELECT available_at, instrument, close::DOUBLE AS close, "
        "shares::BIGINT AS shares, sector FROM (VALUES "
        "(TIMESTAMPTZ '2024-03-04 15:30:00+09', 'A', 100.0, 1000, 'tech'), "
        "(TIMESTAMPTZ '2024-03-05 15:30:00+09', 'A', 101.0, NULL, 'tech'), "
        "(TIMESTAMPTZ '2024-03-06 15:30:00+09', 'A', 102.0, 1200, 'tech'), "
        "(TIMESTAMPTZ '2024-03-07 15:30:00+09', 'A', 103.0, 1300, 'tech'), "
        "(TIMESTAMPTZ '2024-03-08 15:30:00+09', 'A', 104.0, 1400, 'tech'), "
        "(TIMESTAMPTZ '2024-03-04 15:30:00+09', 'B', 50.0, 500, 'bank'), "
        "(TIMESTAMPTZ '2024-03-05 15:30:00+09', 'B', 51.0, 510, 'bank'), "
        "(TIMESTAMPTZ '2024-03-07 15:30:00+09', 'B', 53.0, 530, 'bank'), "
        "(TIMESTAMPTZ '2024-03-08 15:30:00+09', 'B', 54.0, 540, 'bank')"
        ") AS t(available_at, instrument, close, shares, sector)) "
        f"TO '{parquet.as_posix()}' (FORMAT PARQUET)"
    )
    register_dataset(
        tmp_path,
        DatasetRegistration.of(
            DATASET,
            "prices-source",
            instrument_field="instrument",
            available_at="available_at",
            key_fields=("available_at", "instrument"),
            fields={"close": "close", "shares": "shares", "sector": "sector"},
            field_types={"close": "DOUBLE", "shares": "INTEGER", "sector": "VARCHAR"},
            grain="instrument_instant",
        ),
        SourceSpec.of("prices-source", parquet),
    )
    return Workspace.open(tmp_path)


@pytest.fixture
def scans(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    issued: list[dict[str, object]] = []
    original = store_module.scan.observation_table

    def counting(spec, **kwargs):
        issued.append(dict(kwargs))
        return original(spec, **kwargs)

    monkeypatch.setattr(store_module.scan, "observation_table", counting)
    return issued


CALENDAR = DataRequirement.of(
    DATASET, "close", lookback=CalendarLookback(days=2, timezone="Asia/Seoul")
)
ROWS = DataRequirement.of(DATASET, "close", lookback=RowsLookback(rows=3))
SHARES = DataRequirement.of(DATASET, "shares", lookback=RowsLookback(rows=3))
SECTOR = DataRequirement.of(DATASET, "sector", lookback=RowsLookback(rows=3))
START, END = _at(7, 16, 0), _at(8, 16, 0)


def _window(store: DuckDbObservationStore, at: datetime, *allowed: DataRequirement) -> ModelWindow:
    return ModelWindow(
        evaluation_time=at,
        instruments=("A", "B"),
        store=store,
        allowed_requirements=allowed or (CALENDAR, ROWS, SHARES, SECTOR),
        consumer_id="probe",
    )


def test_the_scan_is_the_runs_horizon_not_the_registered_span(
    workspace: Workspace, scans: list[dict[str, object]]
) -> None:
    """One scan from the earliest bound any declared lookback reaches at `start`, up to `end`."""
    store = DuckDbObservationStore(
        workspace, horizon=(START, END), requirements=(CALENDAR, ROWS, SHARES)
    )

    first = _window(store, START).panel((CALENDAR,), "close")
    second = _window(store, END).panel((ROWS,), "close")

    assert len(scans) == 1, "two aliases on one dataset, one bound, one scan"
    # The calendar bound at start (the 5th, 00:00 KST) is earlier than the rows bound (the
    # third instant back from start, the 5th at 15:30), so the calendar bound wins.
    assert scans[0]["lower_bound"] == _at(5, 0, 0)
    assert scans[0]["evaluation_time"] == END
    assert first.panel is second.panel
    assert first.panel.bounds == (_at(5, 0, 0), END)
    assert [instant.day for instant in first.panel.instants] == [5, 6, 7, 8], "the 4th was not read"
    assert [instant.day for instant in first.instants] == [5, 6, 7]
    assert [instant.day for instant in second.instants] == [6, 7, 8]


def test_without_a_horizon_the_scan_is_the_registered_span(
    workspace: Workspace, scans: list[dict[str, object]]
) -> None:
    store = DuckDbObservationStore(workspace)

    window = _window(store, START).panel((CALENDAR,), "close")

    span = workspace.dataset(DATASET).span
    assert span is not None
    assert (scans[0]["lower_bound"], scans[0]["evaluation_time"]) == span
    assert window.panel.bounds is None
    assert [instant.day for instant in window.panel.instants] == [4, 5, 6, 7, 8]


def test_a_window_outside_the_panels_bounds_is_refused(workspace: Workspace) -> None:
    """The rows are not there; a shorter window than the lookback named would be a silent hole."""
    store = DuckDbObservationStore(workspace, horizon=(START, END), requirements=(CALENDAR,))
    panel = _window(store, START).panel((CALENDAR,), "close").panel

    with pytest.raises(RuntimeError, match="scanned up to"):
        panel.window("close", evaluation_time=END + timedelta(days=1), lookback=CALENDAR.lookback)
    with pytest.raises(RuntimeError, match="scanned from"):
        panel.window(
            "close",
            evaluation_time=START,
            lookback=CalendarLookback(days=10, timezone="Asia/Seoul"),
        )
    # Inside the bounds, at the run's end, with the declared lookback: served.
    assert len(panel.window("close", evaluation_time=END, lookback=CALENDAR.lookback)) == 3


def test_a_numeric_field_is_held_once_and_the_matrix_is_a_view(workspace: Workspace) -> None:
    store = DuckDbObservationStore(workspace, horizon=(START, END), requirements=(CALENDAR,))
    window = _window(store, START).panel((CALENDAR,), "close")
    panel = window.panel

    assert "close" in panel.blocks and "close" not in panel.columns, "no Arrow copy beside it"
    assert panel.block("close").dtype == np.float64
    assert np.shares_memory(window.matrix(), panel.block("close")), "a view, not a copy"
    expected = np.array([[101.0, 51.0], [102.0, np.nan], [103.0, 53.0]])
    np.testing.assert_array_equal(window.matrix(), expected)
    assert window.values["B"] == (51.0, None, 53.0), "NaN in the block is None at the door"
    assert window.counts() == {"A": 3, "B": 2}
    assert dict(window.current()) == {"A": 103.0, "B": 53.0}
    assert dict(window.latest()) == {"A": 103.0, "B": 53.0}


def test_an_integer_field_rides_in_the_block_and_comes_back_as_int(workspace: Workspace) -> None:
    store = DuckDbObservationStore(workspace, horizon=(START, END), requirements=(SHARES,))
    window = _window(store, START).panel((SHARES,), "shares")

    assert window.matrix().dtype == np.float64
    assert window.values["A"] == (None, 1200, 1300)
    assert all(isinstance(cell, int) for cell in window.values["A"] if cell is not None)
    assert dict(window.current()) == {"A": 1300, "B": 530}
    assert all(isinstance(cell, int) for cell in window.current().values())
    assert isinstance(window.latest()["B"], int)


def test_a_string_field_stays_arrow_and_the_matrix_refuses_it(workspace: Workspace) -> None:
    store = DuckDbObservationStore(workspace, horizon=(START, END), requirements=(SECTOR,))
    window = _window(store, START).panel((SECTOR,), "sector")

    assert "sector" in window.panel.columns and "sector" not in window.panel.blocks
    assert window.values["B"] == ("bank", None, "bank")
    assert dict(window.current()) == {"A": "tech", "B": "bank"}
    assert window.counts() == {"A": 3, "B": 2}
    with pytest.raises(TypeError, match="not numeric"):
        window.matrix()
