"""The bridge from a declared alias to the real point-in-time store.

`agent_first` takes an injected resolver so the invocation boundary stays testable without
a database. `strategy_bridge` fills that point in production using these three translations,
so these tests pin the translation itself: lookback kinds map across the public/private
boundary, declared fields are carried exactly, and a declaration the store cannot serve
raises rather than quietly producing a thin result.

**The resolver tests that stood below are gone with record `124`.** They drove
`project.resolver(...)`, and both resolver classes -- the catalog-backed one and the
store-backed one no module ever imported -- went with the Project cluster. What they read
through is exercised for real by every run in `tests/flow/`.
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
