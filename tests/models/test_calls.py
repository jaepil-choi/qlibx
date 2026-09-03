"""Turning a declared alias into real point-in-time reads.

**These moved out of `_internal/pit_bridge.py` with record `128`** and the module went with
them. They existed there so `strategy_bridge` could serve an authored `read(alias)` while the
engine served `context.window.observations(requirement)`; now both contexts read through this
code and there is no boundary left for it to sit on.

What they pin is unchanged: declared fields are carried exactly, an alias fans out into one
requirement per field and joins back on `(instant, instrument)`, and a declaration the store
cannot serve raises rather than quietly producing a thin result.

**The resolver tests that stood below are gone with record `124`.** They drove
`project.resolver(...)`, and both resolver classes -- the catalog-backed one and the
store-backed one no module ever imported -- went with the Project cluster. What they read
through is exercised for real by every run in `tests/flow/`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from vqapr.authoring import CalendarLookback, DatasetInput, Observation, RowsLookback
from vqapr.models.calls import observations, requirements_for

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


# --- the lookbacks are one class -----------------------------------------------------------


def test_the_authoring_and_engine_lookbacks_are_the_same_class():
    """The inversion of what stood here, and the reason `engine_lookback` is gone.

    This assertion used to run the other way -- *"If these ever became the same class the
    translation would be dead code"* -- and guarded four tests of a copy constructor that moved
    `rows` from one dataclass to an identical one. Record `126` made them the same class, so the
    sentence came true and the translation went with it.

    Kept as an assertion rather than deleted, because splitting them again would silently
    reintroduce a translation layer, and the first symptom would be a lookback that authored
    correctly and read as a different window.
    """
    from vqapr.data.lookback import CalendarLookback as EngineCalendar
    from vqapr.data.lookback import RowsLookback as EngineRows

    assert RowsLookback is EngineRows
    assert CalendarLookback is EngineCalendar


def test_an_authored_declaration_carries_the_engine_lookback_unchanged():
    """No copy on the way in, so no window can be widened by copying it wrong."""
    declaration = DatasetInput(
        dataset_id="stock_daily", fields=("ret",), lookback=RowsLookback(rows=3)
    )

    assert requirements_for(declaration)[0].lookback is declaration.lookback


def test_the_calendar_form_still_carries_every_component():
    declaration = DatasetInput(
        dataset_id="stock_daily",
        fields=("ret",),
        lookback=CalendarLookback(years=1, months=2, days=3, timezone="Asia/Seoul"),
    )

    lookback = requirements_for(declaration)[0].lookback
    assert (lookback.years, lookback.months, lookback.days) == (1, 2, 3)
    assert lookback.timezone == "Asia/Seoul"


# --- requirement translation ---------------------------------------------------------------


def test_a_declared_alias_becomes_one_engine_requirement_per_field():
    """The engine requirement names one field, so an alias over two fields becomes two."""
    declaration = DatasetInput(
        dataset_id="stock_daily", fields=("ret", "market_cap"), lookback=RowsLookback(rows=2)
    )
    requirements = requirements_for(declaration)

    assert tuple(requirement.field_id for requirement in requirements) == ("ret", "market_cap")
    assert {str(requirement.dataset_id) for requirement in requirements} == {"stock_daily"}
    assert {requirement.lookback.rows for requirement in requirements} == {2}


def test_requirements_for_refuses_a_non_declaration():
    with pytest.raises(TypeError, match=r"authoring\.DatasetInput"):
        requirements_for({"dataset_id": "stock_daily"})


# --- row projection ------------------------------------------------------------------------


def test_rows_project_onto_typed_observations_carrying_only_declared_fields():
    projected = observations(
        _rows(),
        instrument_field="instrument",
        available_at_field="available_at",
        fields=("ret",),
    )

    assert len(projected) == 2
    assert projected[0].instrument_id == "A005930"
    assert projected[0].available_at == datetime(2024, 3, 15, 6, 30, tzinfo=UTC)
    # `market_cap` was present in the row but not declared, so it must not leak through.
    assert set(projected[0].values) == {"ret"}


def test_a_missing_declared_field_raises_rather_than_thinning_the_result():
    with pytest.raises(KeyError, match="missing the declared field"):
        observations(
            _rows(),
            instrument_field="instrument",
            available_at_field="available_at",
            fields=("ret", "never_present"),
        )


def test_a_missing_instrument_or_availability_column_is_a_schema_error():
    rows = ({"available_at": datetime(2024, 3, 15, tzinfo=UTC), "ret": Decimal(1)},)
    with pytest.raises(KeyError, match="missing the instrument field"):
        observations(
            rows,
            instrument_field="instrument",
            available_at_field="available_at",
            fields=("ret",),
        )

    rows = ({"instrument": "A005930", "ret": Decimal(1)},)
    with pytest.raises(KeyError, match="missing the availability field"):
        observations(
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
        observations(
            rows,
            instrument_field="instrument",
            available_at_field="available_at",
            fields=("ret",),
        )


def test_a_non_datetime_availability_value_is_refused():
    rows = ({"instrument": "A005930", "available_at": "2024-03-15", "ret": Decimal(1)},)
    with pytest.raises(TypeError, match="timezone-aware datetime"):
        observations(
            rows,
            instrument_field="instrument",
            available_at_field="available_at",
            fields=("ret",),
        )


def test_a_framework_built_observation_is_the_validated_one_without_the_validation():
    """`docs/issues/054`: the read builds rows through `Observation._framework_row`, which skips
    `__post_init__`. What it builds must be indistinguishable from the validated constructor's
    result -- equal, frozen, values immutable -- because an author holds both kinds."""
    projected = observations(
        _rows(),
        instrument_field="instrument",
        available_at_field="available_at",
        fields=("ret",),
    )
    first = projected[0]
    by_hand = Observation(first.instrument_id, first.available_at, dict(first.values))

    assert first == by_hand
    with pytest.raises(TypeError):
        first.values["ret"] = Decimal(0)  # type: ignore[index]
    with pytest.raises(AttributeError):
        first.instrument_id = "B"  # type: ignore[misc]


def test_no_rows_projects_to_no_observations():
    assert (
        observations(
            (), instrument_field="instrument", available_at_field="available_at", fields=("ret",)
        )
        == ()
    )
