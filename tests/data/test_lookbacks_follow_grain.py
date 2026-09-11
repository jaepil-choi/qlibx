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

from vqapr.data.dataset import DatasetRegistration, lookback_fits_grain
from vqapr.data.lookback import CalendarLookback, InstantsLookback, RowsLookback
from vqapr.data.requirement import DataRequirement
from vqapr.data.source import SourceSpec
from vqapr.data.store import DuckDbObservationStore
from vqapr.data.window import ModelWindow
from vqapr.project.store import Workspace
from vqapr.public import register_dataset

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
        # A decimal literal is a DECIMAL to duckdb; the dataset declares DOUBLE, so write one.
        f"COPY (SELECT available_at, instrument, close::DOUBLE AS close "
        f"FROM (VALUES {rows}) AS t(available_at, instrument, close)) "
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
            field_types={"close": "DOUBLE"},
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
    from vqapr.data.dataset import Grain

    assert lookback_fits_grain(RowsLookback(1), Grain.INSTRUMENT_INSTANT) is None
    assert lookback_fits_grain(CalendarLookback(days=1), Grain.INSTANT) is None
    assert lookback_fits_grain(InstantsLookback(1), Grain.ROWS) is None
    assert "InstantsLookback" in lookback_fits_grain(RowsLookback(1), Grain.ROWS)
    assert "RowsLookback" in lookback_fits_grain(InstantsLookback(1), Grain.INSTANT)


@pytest.fixture(scope="module")
def vendor_grain_parquet(tmp_path_factory) -> Path:
    """The `053` shape: one name, four instants, three account codes -- three rows per instant.

    `close` is null on every row of the 2nd, so the per-field null-skipping has an instant to skip.
    """
    out = tmp_path_factory.mktemp("vendor") / "statements.parquet"
    rows = ", ".join(
        f"(TIMESTAMPTZ '2024-03-{day:02d} 15:30:00+09', 'A', '{code}', "
        + ("NULL" if day == 2 else f"{day * 10 + index}.0")
        + ")"
        for day in range(1, 5)
        for index, code in enumerate("xyz")
    )
    duckdb.connect().execute(
        f"COPY (SELECT available_at, instrument, code, close::DOUBLE AS close "
        f"FROM (VALUES {rows}) AS t(available_at, instrument, code, close)) "
        f"TO '{out.as_posix()}' (FORMAT PARQUET)"
    )
    return out


def test_an_instants_lookback_counts_instants_not_rows_on_a_vendor_grain_table(
    tmp_path: Path, vendor_grain_parquet: Path
) -> None:
    """`docs/issues/053`: `InstantsLookback(2)` on three rows per instant is two instants, six rows.

    The version that counted rows returned the newest instant's first two rows and called them two
    instants; nothing refused it, and a model believing it reached two statements reached one.
    """
    register_dataset(
        tmp_path,
        DatasetRegistration.of(
            "statements",
            "src",
            instrument_field="instrument",
            available_at="available_at",
            key_fields=("available_at", "instrument", "code"),
            fields={"close": "close"},
            field_types={"close": "DOUBLE"},
            grain="rows",
        ),
        SourceSpec.of("src", vendor_grain_parquet),
    )
    workspace = Workspace.open(tmp_path)
    rows = _read(workspace, DataRequirement.of("statements", "close", lookback=InstantsLookback(2)))

    assert sorted({row["available_at"].day for row in rows}) == [3, 4]
    assert len(rows) == 6, "every row of an admitted instant comes back, not the first n rows"

    # An instant on which the field is null everywhere is not one of the name's instants for that
    # field: three instants back lands on the 1st, 3rd and 4th, and the 2nd's rows do not come.
    rows = _read(workspace, DataRequirement.of("statements", "close", lookback=InstantsLookback(3)))
    assert sorted({row["available_at"].day for row in rows}) == [1, 3, 4]
    assert len(rows) == 9
