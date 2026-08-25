"""The bridge from a declared alias to the real point-in-time store.

`agent_first` takes an injected resolver so the invocation boundary stays testable without
a database. `StoreResolver` is what fills that injection point in production, so these
tests pin the translation itself: lookback kinds map across the public/private boundary,
declared fields are carried exactly, and a declaration the store cannot serve raises
rather than quietly producing a thin result.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from vqapr._internal.pit_bridge import engine_lookback, observation_rows, requirement_for
from vqapr.authoring import CalendarLookback, DatasetInput, RowsLookback

EVALUATION_TIME = datetime(2024, 3, 15, 16, tzinfo=UTC)


def _rows():
    return (
        {
            "instrument": "A005930",
            "available_at": datetime(2024, 3, 15, 6, 30, tzinfo=UTC),
            "ret": Decimal("-0.026918"),
            "market_cap": Decimal("431615278365000"),
        },
        {
            "instrument": "A000660",
            "available_at": datetime(2024, 3, 15, 6, 30, tzinfo=UTC),
            "ret": Decimal("-0.004324"),
            "market_cap": Decimal("117353981238000"),
        },
    )


# --- lookback translation ------------------------------------------------------------------


def test_a_rows_lookback_translates_without_widening():
    translated = engine_lookback(RowsLookback(rows=3))
    assert translated.rows == 3


def test_a_calendar_lookback_carries_every_component():
    translated = engine_lookback(
        CalendarLookback(years=1, months=2, days=3, timezone="Asia/Seoul")
    )
    assert translated.years == 1
    assert translated.months == 2
    assert translated.days == 3
    assert translated.timezone == "Asia/Seoul"


def test_an_unknown_lookback_kind_is_refused():
    with pytest.raises(TypeError, match=r"authoring\.RowsLookback or authoring\.CalendarLookback"):
        engine_lookback("three rows")


def test_the_public_and_engine_lookbacks_are_genuinely_distinct_types():
    """If these ever became the same class the translation would be dead code."""
    from vqapr.data.lookback import RowsLookback as EngineRows

    assert RowsLookback is not EngineRows
    assert not isinstance(RowsLookback(rows=1), EngineRows)


# --- requirement translation ---------------------------------------------------------------


def test_a_declared_alias_becomes_an_engine_requirement():
    declaration = DatasetInput(
        dataset_id="stock_daily", fields=("ret", "market_cap"), lookback=RowsLookback(rows=2)
    )
    requirement = requirement_for("consumer-a", declaration)

    assert str(requirement.dataset_id) == "stock_daily"
    assert requirement.fields == ("ret", "market_cap")
    assert requirement.lookback.rows == 2


def test_requirement_for_refuses_a_non_declaration():
    with pytest.raises(TypeError, match=r"authoring\.DatasetInput"):
        requirement_for("consumer-a", {"dataset_id": "stock_daily"})


# --- row projection ------------------------------------------------------------------------


def test_rows_project_onto_typed_observations_carrying_only_declared_fields():
    observations = observation_rows(
        _rows(),
        instrument_field="instrument",
        available_at_field="available_at",
        fields=("ret",),
    )

    assert len(observations) == 2
    assert observations[0].instrument_id == "A005930"
    assert observations[0].available_at == datetime(2024, 3, 15, 6, 30, tzinfo=UTC)
    # `market_cap` was present in the row but not declared, so it must not leak through.
    assert set(observations[0].values) == {"ret"}


def test_a_missing_declared_field_raises_rather_than_thinning_the_result():
    with pytest.raises(KeyError, match="missing the declared field"):
        observation_rows(
            _rows(),
            instrument_field="instrument",
            available_at_field="available_at",
            fields=("ret", "never_present"),
        )


def test_a_missing_instrument_or_availability_column_is_a_schema_error():
    rows = ({"available_at": datetime(2024, 3, 15, tzinfo=UTC), "ret": Decimal(1)},)
    with pytest.raises(KeyError, match="missing the instrument field"):
        observation_rows(
            rows,
            instrument_field="instrument",
            available_at_field="available_at",
            fields=("ret",),
        )

    rows = ({"instrument": "A005930", "ret": Decimal(1)},)
    with pytest.raises(KeyError, match="missing the availability field"):
        observation_rows(
            rows,
            instrument_field="instrument",
            available_at_field="available_at",
            fields=("ret",),
        )


def test_a_naive_availability_stamp_is_refused():
    rows = (
        {
            "instrument": "A005930",
            "available_at": datetime(2024, 3, 15, 6, 30),
            "ret": Decimal(1),
        },
    )
    with pytest.raises((TypeError, ValueError)):
        observation_rows(
            rows,
            instrument_field="instrument",
            available_at_field="available_at",
            fields=("ret",),
        )


def test_a_non_datetime_availability_value_is_refused():
    rows = ({"instrument": "A005930", "available_at": "2024-03-15", "ret": Decimal(1)},)
    with pytest.raises(TypeError, match="timezone-aware datetime"):
        observation_rows(
            rows,
            instrument_field="instrument",
            available_at_field="available_at",
            fields=("ret",),
        )


def test_no_rows_projects_to_no_observations():
    assert (
        observation_rows(
            (), instrument_field="instrument", available_at_field="available_at", fields=("ret",)
        )
        == ()
    )


# --- CatalogResolver: the supported reader ------------------------------------------------


def _price_parquet(tmp_path):
    import duckdb

    target = tmp_path / "price.parquet"
    connection = duckdb.connect()
    connection.execute(
        f"""COPY (SELECT * FROM (VALUES
        ('A', TIMESTAMPTZ '2024-03-05 16:00:00+00', 100.0),
        ('A', TIMESTAMPTZ '2024-03-06 16:00:00+00', 103.0),
        ('A', TIMESTAMPTZ '2024-03-07 16:00:00+00', 105.0),
        ('B', TIMESTAMPTZ '2024-03-06 16:00:00+00', 50.0)
        ) AS t(instrument, available_at, close))
        TO '{target.as_posix()}' (FORMAT PARQUET)"""
    )
    connection.close()
    return target


def _registered_project(tmp_path):
    import vqapr
    from vqapr.project import DatasetDeclaration

    project = vqapr.open(tmp_path / "project")
    project.register(
        DatasetDeclaration(
            dataset_id="price_daily",
            path=_price_parquet(tmp_path),
            hive_partitioned=False,
            instrument_field="instrument",
            available_at_field="available_at",
            key_fields=("available_at", "instrument"),
            fields={"close": "close"},
        )
    )
    return project


def test_the_resolver_honours_the_point_in_time_cutoff(tmp_path):
    project = _registered_project(tmp_path)
    resolver = project.resolver(instruments=("A", "B"))
    declaration = DatasetInput(
        dataset_id="price_daily", fields=("close",), lookback=RowsLookback(rows=5)
    )
    cutoff = datetime(2024, 3, 6, 16, tzinfo=UTC)

    observations = resolver("prices", declaration, cutoff)

    assert observations, "expected observations at the cutoff"
    # Compare instants, never calendar days: duckdb renders these in the session zone,
    # so a day-number assertion would test the local timezone rather than the cutoff.
    assert all(o.available_at <= cutoff for o in observations)
    later = datetime(2024, 3, 7, 16, tzinfo=UTC)
    assert all(o.available_at != later for o in observations)


def test_the_resolver_trims_to_the_declared_lookback(tmp_path):
    project = _registered_project(tmp_path)
    resolver = project.resolver(instruments=("A", "B"))
    declaration = DatasetInput(
        dataset_id="price_daily", fields=("close",), lookback=RowsLookback(rows=2)
    )

    observations = resolver("prices", declaration, datetime(2024, 3, 7, 16, tzinfo=UTC))

    for instrument in ("A", "B"):
        window = [o for o in observations if o.instrument_id == instrument]
        assert len(window) <= 2
        # Oldest first, and the most recent rows are the ones kept.
        assert window == sorted(window, key=lambda o: o.available_at)
    a_window = [o.available_at for o in observations if o.instrument_id == "A"]
    assert a_window == [
        datetime(2024, 3, 6, 16, tzinfo=UTC),
        datetime(2024, 3, 7, 16, tzinfo=UTC),
    ]


def test_the_resolver_serves_only_the_requested_instruments(tmp_path):
    project = _registered_project(tmp_path)
    resolver = project.resolver(instruments=("A",))
    declaration = DatasetInput(
        dataset_id="price_daily", fields=("close",), lookback=RowsLookback(rows=5)
    )

    observations = resolver("prices", declaration, datetime(2024, 3, 7, 16, tzinfo=UTC))
    assert {o.instrument_id for o in observations} == {"A"}


def test_the_resolver_refuses_an_empty_instrument_set(tmp_path):
    import vqapr

    project = vqapr.open(tmp_path)
    with pytest.raises(ValueError, match="non-empty"):
        project.resolver(instruments=())
