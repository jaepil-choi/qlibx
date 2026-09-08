"""A panel is built once per run and every window is a slice of it.

`docs/design/the-panel-the-surface-and-the-run.md` §2.3, §2.5; record `137`. What a panel-grain
alias is read as: `read(alias, field)` returns `instants` x `instruments`, a slice of the panel
the store built the first time anything read that alias, by arithmetic on the instant axis and
without a query. `rows(alias)` is the `rows`-grain verb and refuses a panel grain by name;
`read` refuses a `rows` grain the same way. `docs/issues/035` closes here: the panel is columnar
by construction, so "expose column arrays" is exposing the panel.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from vqapr.authoring import DatasetInput, RowsLookback
from vqapr.authoring.context import DataModelContext, requirements_for
from vqapr.data import store as store_module
from vqapr.data.datasets import DatasetRegistration
from vqapr.data.lookback import CalendarLookback
from vqapr.data.panel import NO_INSTRUMENT, PanelWindow
from vqapr.data.sources import SourceSpec
from vqapr.data.store import DuckDbObservationStore
from vqapr.data.windows import ModelWindow
from vqapr.public import register_dataset
from vqapr.project.store import Workspace

KST = ZoneInfo("Asia/Seoul")


def _at(day: int) -> datetime:
    return datetime(2024, 3, day, 16, tzinfo=KST)


def _workspace(root: Path, parquet: Path, grain: str = "instrument_instant") -> Workspace:
    register_dataset(
        root,
        DatasetRegistration.of(
            "price_daily",
            "prices",
            instrument_field="instrument",
            available_at="available_at",
            key_fields=("available_at", "instrument"),
            fields={"close": "close", "volume": "volume"},
            field_types={"close": "DOUBLE", "volume": "DOUBLE"},
            grain=grain,
        ),
        SourceSpec.of("prices", parquet),
    )
    return Workspace.open(root)


@pytest.fixture
def scans(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, str]]:
    issued: list[dict[str, str]] = []
    original = store_module.scan.observation_rows

    def counting(spec, **kwargs):
        issued.append(dict(kwargs["fields"]))
        return original(spec, **kwargs)

    monkeypatch.setattr(store_module.scan, "observation_rows", counting)
    return issued


ALIAS = DatasetInput(
    dataset_id="price_daily", fields=("close", "volume"), lookback=RowsLookback(rows=2)
)


def _context(
    store: DuckDbObservationStore, day: int, consumer: str = "reversal"
) -> DataModelContext:
    window = ModelWindow(
        evaluation_time=_at(day),
        instruments=("A", "B"),
        store=store,
        allowed_requirements=requirements_for(ALIAS),
        consumer_id=consumer,
    )
    return DataModelContext(window=window, reads={"prices": ALIAS})


def test_read_returns_a_window_of_instants_by_instruments(
    tmp_path: Path, model_price_parquet: Path
) -> None:
    store = DuckDbObservationStore(_workspace(tmp_path, model_price_parquet))

    window = _context(store, 7).read("prices", "close")

    assert isinstance(window, PanelWindow)
    assert [instant.day for instant in window.instants] == [6, 7]
    assert window.instruments == ("A", "B")
    assert window.values["A"] == (103.0, 105.0)
    assert window.latest()["A"] == 105.0
    assert len(window) == 2


def test_values_converts_one_column_per_name_asked_for(
    tmp_path: Path, model_price_parquet: Path
) -> None:
    """`docs/issues/061`: `values[name]` is that column, not every column and then one of them."""
    store = DuckDbObservationStore(_workspace(tmp_path, model_price_parquet))
    window = _context(store, 7).read("prices", "close")

    assert window.values["A"] == (103.0, 105.0)
    assert set(window._values) == {"A"}, "B was not asked for, so B was not converted"
    assert "B" in window.values and len(window.values) == 2
    assert dict(window.values) == {"A": (103.0, 105.0), "B": window.series("B").cells}
    # `latest()` and `counts()` do not convert columns either.
    fresh = _context(store, 7).read("prices", "close")
    assert fresh.latest()["A"] == 105.0
    assert fresh.counts() == {"A": 2, "B": 2}
    assert fresh._values == {}


def test_a_null_stays_a_null_and_latest_skips_it(tmp_path: Path, model_price_parquet: Path) -> None:
    store = DuckDbObservationStore(_workspace(tmp_path, model_price_parquet))

    window = _context(store, 7).read("prices", "volume")

    assert window.values["A"] == (None, 12.0), "volume is null on the 6th; that is not a zero"
    assert _context(store, 6).read("prices", "volume").latest()["A"] == 10.0


def test_the_panel_is_built_once_and_every_later_read_is_a_slice(
    tmp_path: Path, model_price_parquet: Path, scans: list[dict[str, str]]
) -> None:
    """Two fields, three cutoffs, two consumers: one scan for the run."""
    store = DuckDbObservationStore(_workspace(tmp_path, model_price_parquet))

    first = _context(store, 5).read("prices", "close")
    _context(store, 6).read("prices", "volume")
    later = _context(store, 7, consumer="momentum").read("prices", "close")

    assert len(scans) == 1, scans
    assert set(scans[0]) == {"close", "volume"}, "the alias's fields are scanned together"
    assert later.panel is first.panel, "two consumers in one run share one panel object"
    assert first.panel.identity == later.panel.identity


def test_a_window_shares_the_panels_buffers(tmp_path: Path, model_price_parquet: Path) -> None:
    store = DuckDbObservationStore(_workspace(tmp_path, model_price_parquet))
    window = _context(store, 7).read("prices", "close")

    column = window.panel.columns["close"]["A"]
    sliced = column.slice(window.start, window.stop - window.start)
    assert sliced.buffers()[1] is not None
    assert sliced.buffers()[1].address == column.buffers()[1].address, "a slice, not a copy"


def test_a_calendar_lookback_is_a_slice_from_its_bound(
    tmp_path: Path, model_price_parquet: Path
) -> None:
    alias = DatasetInput(
        dataset_id="price_daily",
        fields=("close",),
        lookback=CalendarLookback(days=1, timezone="Asia/Seoul"),
    )
    store = DuckDbObservationStore(_workspace(tmp_path, model_price_parquet))
    window = ModelWindow(
        evaluation_time=_at(7),
        instruments=("A", "B"),
        store=store,
        allowed_requirements=requirements_for(alias),
        consumer_id="reversal",
    )

    read = DataModelContext(window=window, reads={"prices": alias}).read("prices", "close")

    assert [instant.day for instant in read.instants] == [6, 7]
    assert window.accesses[0].lower_bound == read.instants[0]
    assert window.accesses[0].actual_rows == {"A": {"close": 2}, "B": {"close": 2}}


def test_the_read_is_recorded_as_an_access_like_any_other(
    tmp_path: Path, model_price_parquet: Path
) -> None:
    store = DuckDbObservationStore(_workspace(tmp_path, model_price_parquet))
    context = _context(store, 7)

    context.read("prices", "close")

    (access,) = context.window.accesses
    assert access.fields == ("close",)
    assert access.consumer_id == "reversal"
    assert access.max_available_at == _at(7).replace(hour=15, minute=30)


def test_rows_on_a_panel_grain_and_read_on_a_rows_grain_are_refused_by_name(
    tmp_path: Path, model_price_parquet: Path
) -> None:
    panel_store = DuckDbObservationStore(_workspace(tmp_path / "panel", model_price_parquet))
    with pytest.raises(TypeError, match=r"read\('prices', <field>\)"):
        _context(panel_store, 7).rows("prices")

    from vqapr.data.lookback import InstantsLookback

    rows_alias = DatasetInput(
        dataset_id="price_daily", fields=("close",), lookback=InstantsLookback(instants=2)
    )
    rows_store = DuckDbObservationStore(_workspace(tmp_path / "rows", model_price_parquet, "rows"))
    window = ModelWindow(
        evaluation_time=_at(7),
        instruments=("A", "B"),
        store=rows_store,
        allowed_requirements=requirements_for(rows_alias),
        consumer_id="reversal",
    )
    context = DataModelContext(window=window, reads={"prices": rows_alias})
    with pytest.raises(TypeError, match=r"rows\('prices'\)"):
        context.read("prices", "close")
    assert [row.instrument_id for row in context.rows("prices")][:2] == ["A", "B"]


def test_an_undeclared_field_or_alias_is_refused(tmp_path: Path, model_price_parquet: Path) -> None:
    store = DuckDbObservationStore(_workspace(tmp_path, model_price_parquet))
    context = _context(store, 7)
    with pytest.raises(KeyError, match="not a field of 'prices'"):
        context.read("prices", "open")
    with pytest.raises(KeyError, match="was not declared in inputs"):
        context.read("volumes", "volume")


def test_a_dataset_with_no_instrument_axis_is_a_one_column_panel(tmp_path: Path) -> None:
    import duckdb

    parquet = tmp_path / "rate.parquet"
    duckdb.connect().execute(
        "COPY (SELECT * FROM (VALUES "
        "(TIMESTAMPTZ '2024-03-05 15:30:00+09', 0.031::DOUBLE), "
        "(TIMESTAMPTZ '2024-03-06 15:30:00+09', 0.032::DOUBLE)) AS t(available_at, rf)) "
        f"TO '{parquet.as_posix()}' (FORMAT PARQUET)"
    )
    register_dataset(
        tmp_path,
        DatasetRegistration.of(
            "rate",
            "rate-source",
            available_at="available_at",
            key_fields=("available_at",),
            fields={"rf": "rf"},
            field_types={"rf": "DOUBLE"},
            grain="instant",
        ),
        SourceSpec.of("rate-source", parquet),
    )
    alias = DatasetInput(dataset_id="rate", fields=("rf",), lookback=RowsLookback(rows=1))
    window = ModelWindow(
        evaluation_time=_at(6),
        instruments=("A",),
        store=DuckDbObservationStore(Workspace.open(tmp_path)),
        allowed_requirements=requirements_for(alias),
        consumer_id="reversal",
    )

    read = DataModelContext(window=window, reads={"rate": alias}).read("rate", "rf")

    assert read.instruments == ()
    assert read.values == {NO_INSTRUMENT: (0.032,)}
    assert read.latest()[NO_INSTRUMENT] == read.series()[-1]
    assert dict(read.current()) == dict(read.latest()), "one column, one entry (072)"


def test_current_is_the_cross_section_and_latest_carries_forward(
    tmp_path: Path, model_price_parquet: Path
) -> None:
    """`docs/issues/072`: on a sparse panel `latest()` promotes a stale row; `current()` does not.

    `volume` is null on the 6th for both names. A window ending on the 6th has a volume for A
    from the 5th, which `latest()` returns and `current()` refuses to carry forward.
    """
    store = DuckDbObservationStore(_workspace(tmp_path, model_price_parquet))

    sparse = _context(store, 6).read("prices", "volume")
    assert sparse.latest() == {"A": 10.0, "B": 20.0}, "the newest value per name, from the 5th"
    assert dict(sparse.current()) == {}, "no name has a volume on the 6th"

    dense = _context(store, 7).read("prices", "close")
    assert dict(dense.current()) == {"A": 105.0, "B": 53.0}
    assert dict(dense.current()) == dict(dense.latest()), "on a dense panel the two agree"
    assert dense._values == {}, "current() converts one scalar per name, not a column"

    empty = ModelWindow(
        evaluation_time=_at(1),
        instruments=("A", "B"),
        store=store,
        allowed_requirements=requirements_for(ALIAS),
        consumer_id="reversal",
    )
    before = DataModelContext(window=empty, reads={"prices": ALIAS}).read("prices", "close")
    assert len(before) == 0 and dict(before.current()) == {} and dict(before.latest()) == {}
