"""The lookback types follow the grain, and the same number cannot mean two things.

`docs/design/the-panel-the-surface-and-the-run.md` §2.4, §7-1; campaign Step 5 (M5.2).

On a panel grain `RowsLookback(n)` is the table's last n rows -- the same n instants for every
name -- so a name that stopped publishing contributes fewer values inside the window rather than
reaching further back. `InstantsLookback(n)` is each name's own last n reported instants and
belongs to `grain: rows`. The types steer: each is refused on the other grain, at preflight and at
the read, naming the right one. `docs/issues/033` measured the shape this makes impossible: 1,637
names, `rows=313`, a batch spanning 1,865 sessions because a delisted name kept its own last 313.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
import pytest

from vqapr.data.datasets import DatasetRegistration, lookback_fits_grain
from vqapr.data.lookback import CalendarLookback, InstantsLookback, RowsLookback
from vqapr.data.requirements import DataRequirement
from vqapr.data.sources import SourceSpec
from vqapr.data.store import DuckDbObservationStore
from vqapr.data.windows import ModelWindow
from vqapr.public import register_dataset
from vqapr.workspace import Workspace

KST = ZoneInfo("Asia/Seoul")


@pytest.fixture(scope="module")
def sparse_parquet(tmp_path_factory) -> Path:
    """A liquid name (A: ten sessions) beside one that stopped publishing (B: three)."""
    out = tmp_path_factory.mktemp("sparse") / "prices.parquet"
    rows = ", ".join(
        f"(TIMESTAMPTZ '2024-03-{day:02d} 15:30:00+09', 'A', {100 + day}.0)" for day in range(1, 11)
    )
    rows += ", " + ", ".join(
        f"(TIMESTAMPTZ '2024-03-{day:02d} 15:30:00+09', 'B', {50 + day}.0)" for day in range(1, 4)
    )
    duckdb.connect().execute(
        f"COPY (SELECT * FROM (VALUES {rows}) AS t(available_at, instrument, close)) "
        f"TO '{out.as_posix()}' (FORMAT PARQUET)"
    )
    return out


def _workspace(root: Path, parquet: Path, grain: str) -> Workspace:
    register_dataset(
        root,
        DatasetRegistration.of(
            "prices",
            "src",
            instrument_field="instrument",
            available_at="available_at",
            key_fields=("available_at", "instrument"),
            fields={"close": "close"},
            grain=grain,
        ),
        SourceSpec.of("src", parquet),
    )
    return Workspace.open(root)


def _read(workspace: Workspace, requirement: DataRequirement, *, day: int = 10):
    window = ModelWindow(
        evaluation_time=datetime(2024, 3, day, 16, tzinfo=KST),
        instruments=("A", "B"),
        store=DuckDbObservationStore(workspace),
        allowed_requirements=(requirement,),
        consumer_id="test",
    )
    return window.observations(requirement).rows


def _days(rows, instrument: str) -> list[int]:
    return [row["available_at"].day for row in rows if row["instrument"] == instrument]


def test_a_rows_lookback_on_a_panel_grain_is_the_tables_last_n_instants(
    tmp_path: Path, sparse_parquet: Path
) -> None:
    """The 033 shape, now impossible: the stopped name does not drag its own history in."""
    workspace = _workspace(tmp_path, sparse_parquet, "instrument_instant")
    rows = _read(workspace, DataRequirement.of("prices", "close", lookback=RowsLookback(2)))

    assert _days(rows, "A") == [9, 10]
    assert _days(rows, "B") == [], "B stopped on the 3rd; the window is the 9th and 10th"
    assert len({row["available_at"] for row in rows}) == 2, "two instants, whatever the names"


def test_a_rows_lookback_larger_than_the_table_is_everything_up_to_the_cutoff(
    tmp_path: Path, sparse_parquet: Path
) -> None:
    workspace = _workspace(tmp_path, sparse_parquet, "instrument_instant")
    rows = _read(workspace, DataRequirement.of("prices", "close", lookback=RowsLookback(50)), day=5)

    assert _days(rows, "A") == [1, 2, 3, 4, 5]
    assert _days(rows, "B") == [1, 2, 3]


def test_an_instants_lookback_on_a_rows_grain_is_each_names_own_last_n(
    tmp_path: Path, sparse_parquet: Path
) -> None:
    """What RowsLookback used to mean, under the name that says what it counts."""
    workspace = _workspace(tmp_path, sparse_parquet, "rows")
    rows = _read(workspace, DataRequirement.of("prices", "close", lookback=InstantsLookback(2)))

    assert _days(rows, "A") == [9, 10]
    assert _days(rows, "B") == [2, 3], "B reaches back to its own last two"


@pytest.mark.parametrize(
    ("grain", "lookback", "names"),
    [
        ("rows", RowsLookback(2), "InstantsLookback"),
        ("rows", CalendarLookback(days=7), "InstantsLookback"),
        ("instrument_instant", InstantsLookback(2), "RowsLookback"),
    ],
)
def test_the_wrong_kind_of_lookback_is_refused_by_name_at_the_read(
    tmp_path: Path, sparse_parquet: Path, grain: str, lookback, names: str
) -> None:
    workspace = _workspace(tmp_path, sparse_parquet, grain)
    with pytest.raises(TypeError, match=names):
        _read(workspace, DataRequirement.of("prices", "close", lookback=lookback))


def test_the_steering_rule_is_stated_once() -> None:
    from vqapr.data.datasets import Grain

    assert lookback_fits_grain(RowsLookback(1), Grain.INSTRUMENT_INSTANT) is None
    assert lookback_fits_grain(CalendarLookback(days=1), Grain.INSTANT) is None
    assert lookback_fits_grain(InstantsLookback(1), Grain.ROWS) is None
    assert "InstantsLookback" in lookback_fits_grain(RowsLookback(1), Grain.ROWS)
    assert "RowsLookback" in lookback_fits_grain(InstantsLookback(1), Grain.INSTANT)
