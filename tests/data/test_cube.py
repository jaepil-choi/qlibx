"""A cube is the panel over every instrument, baked once and mapped by every worker.

`docs/issues/098`, record `236`. A `--jobs` batch bakes each panel-grain dataset it reads into
one memory-mappable matrix per numeric field over every instrument the source holds; a worker
takes its panel as a slice of those files -- a view when the run declared the whole universe, a
gather otherwise -- and the panel it gets is the panel a scan would have built, cell for cell.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
import numpy as np
import pytest

from vqapr.data import cube as cube_module
from vqapr.data import store as store_module
from vqapr.data.dataset import DatasetRegistration
from vqapr.data.lookback import CalendarLookback
from vqapr.data.panel import Panel
from vqapr.data.requirement import DataRequirement
from vqapr.data.source import SourceSpec
from vqapr.data.store import DuckDbObservationStore
from vqapr.data.window import ModelWindow
from vqapr.project.store import Workspace
from vqapr.public import register_dataset

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


def _bake(workspace: Workspace, root: Path, fields: tuple[str, ...]) -> cube_module.Cube | None:
    registration = workspace.dataset(DATASET)
    source = workspace.source(str(registration.source))
    return cube_module.bake(
        root,
        registration=registration,
        source=source,
        source_digest=workspace.source_digest(source),
        fields=fields,
    )


CLOSE = DataRequirement.of(
    DATASET, "close", lookback=CalendarLookback(days=2, timezone="Asia/Seoul")
)
SHARES = DataRequirement.of(
    DATASET, "shares", lookback=CalendarLookback(days=2, timezone="Asia/Seoul")
)
START, END = _at(7, 16, 0), _at(8, 16, 0)


def _read(store: DuckDbObservationStore, at: datetime, names: tuple[str, ...], field: str):
    window = ModelWindow(
        evaluation_time=at,
        instruments=names,
        store=store,
        allowed_requirements=(CLOSE, SHARES),
        consumer_id="probe",
    )
    return window.panel((CLOSE if field == "close" else SHARES,), field)


def test_bake_writes_one_matrix_per_numeric_field_over_every_instrument(
    workspace: Workspace, tmp_path: Path
) -> None:
    root = tmp_path / "cubes"

    cube = _bake(workspace, root, ("close", "shares", "sector"))

    assert cube is not None
    directory = root / DATASET
    assert sorted(path.name for path in directory.iterdir()) == [
        "close.npy",
        "cube.json",
        "instants.npy",
        "instruments.json",
        "present.npy",
        "shares.npy",
    ], "one matrix per numeric field; the string field is not baked"
    assert cube.instruments == ("A", "B") and cube.fields == ("close", "shares")
    assert [instant.day for instant in cube.instants] == [4, 5, 6, 7, 8]
    assert cube.instants[0] == _at(4)
    close = cube.field("close")
    assert isinstance(close, np.memmap) and close.shape == (5, 2)
    np.testing.assert_array_equal(close[:, 0], [100.0, 101.0, 102.0, 103.0, 104.0])
    assert np.isnan(close[2, 1]), "B has no row on the 6th"
    assert not cube.present()[2, 1] and cube.present()[1, 0], "present says where a row existed"
    assert np.isnan(cube.field("shares")[1, 0]), "a null cell is NaN in the block"
    assert cube.source_digest == workspace.source_digest(workspace.source("prices-source"))
    reopened = cube_module.open_cube(root, DATASET)
    assert reopened is not None and reopened.instants == cube.instants
    assert cube_module.open_cube(root, "nothing-baked") is None


def test_nothing_is_baked_for_a_string_field_or_an_unverified_registration(
    workspace: Workspace, tmp_path: Path
) -> None:
    assert _bake(workspace, tmp_path / "strings", ("sector",)) is None
    unverified = DatasetRegistration.of(
        DATASET,
        "prices-source",
        instrument_field="instrument",
        available_at="available_at",
        key_fields=("available_at", "instrument"),
        fields={"close": "close"},
        field_types={"close": "DOUBLE"},
        grain="instrument_instant",
    )
    assert unverified.span is None
    assert (
        cube_module.bake(
            tmp_path / "unverified",
            registration=unverified,
            source=workspace.source("prices-source"),
            source_digest="",
            fields=("close",),
        )
        is None
    )


@pytest.mark.parametrize(
    "names",
    [("A", "B"), ("B",), ("B", "Z"), ("A",)],
    ids=["the whole universe", "a subset with a missing instant", "a name the source lacks", "A"],
)
def test_a_panel_from_the_cube_is_the_panel_a_scan_builds(
    workspace: Workspace, tmp_path: Path, names: tuple[str, ...]
) -> None:
    """Cell for cell and instant for instant, however the run's names relate to the cube's."""
    root = tmp_path / "cubes"
    _bake(workspace, root, ("close", "shares"))
    scanned = DuckDbObservationStore(workspace, horizon=(START, END), requirements=(CLOSE, SHARES))
    mapped = DuckDbObservationStore(
        workspace, horizon=(START, END), requirements=(CLOSE, SHARES), cubes=root
    )

    for field in ("close", "shares"):
        expected = _read(scanned, START, names, field)
        actual = _read(mapped, START, names, field)
        assert isinstance(actual.panel, Panel) and actual.panel is not expected.panel
        assert actual.panel.instants == expected.panel.instants
        np.testing.assert_array_equal(actual.panel.block(field), expected.panel.block(field))
        assert actual.instants == expected.instants
        assert dict(actual.values) == dict(expected.values)
        assert dict(actual.current()) == dict(expected.current())
        assert dict(actual.latest()) == dict(expected.latest())
        assert actual.counts() == expected.counts()
        assert actual.panel.bounds == expected.panel.bounds
    close = _read(mapped, START, names, "close").panel.block("close")
    if names == ("A", "B"):
        assert isinstance(close, np.memmap), "the whole universe is a view of the file"
    else:
        assert not isinstance(close, np.memmap), "a subset is a gather the size of the run"


def test_the_store_takes_the_cube_and_scans_nothing(
    workspace: Workspace, tmp_path: Path, scans: list[dict[str, object]]
) -> None:
    root = tmp_path / "cubes"
    _bake(workspace, root, ("close", "shares"))
    baked = len(scans)
    assert baked == 1, "the bake is the one scan"
    store = DuckDbObservationStore(
        workspace, horizon=(START, END), requirements=(CLOSE, SHARES), cubes=root
    )

    window = _read(store, START, ("A", "B"), "close")
    _read(store, END, ("A", "B"), "shares")

    assert len(scans) == baked, "every read is a slice of the cube"
    assert window.values["B"] == (51.0, None, 53.0)


def test_a_cube_over_other_bytes_or_missing_a_field_is_passed_over_for_a_scan(
    workspace: Workspace, tmp_path: Path, scans: list[dict[str, object]]
) -> None:
    root = tmp_path / "cubes"
    _bake(workspace, root, ("close",))
    baked = len(scans)
    meta_path = root / DATASET / cube_module.CUBE_META
    meta = json.loads(meta_path.read_text(encoding="utf-8"))

    # A field the cube does not carry: the alias scans as it does outside a batch.
    store = DuckDbObservationStore(
        workspace, horizon=(START, END), requirements=(SHARES,), cubes=root
    )
    _read(store, START, ("A", "B"), "shares")
    assert len(scans) == baked + 1

    # A cube baked from other bytes: the digest does not match, and the store scans.
    meta_path.write_text(json.dumps({**meta, "source_digest": "not these bytes"}), encoding="utf-8")
    store = DuckDbObservationStore(
        workspace, horizon=(START, END), requirements=(CLOSE,), cubes=root
    )
    _read(store, START, ("A", "B"), "close")
    assert len(scans) == baked + 2
