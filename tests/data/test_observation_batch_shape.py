"""What an `ObservationBatch` holds, pinned as a promise rather than left to be measured.

`docs/issues/031`. `ModelWindow.observations(requirement)` is the only method a DataModel author
can call to see any data at all, and its return type was:

* not importable -- `hasattr(vqapr.public, "ObservationBatch")` was `False`;
* undocumented -- no docstring on the class or on `observations`;
* unmentioned by the skill, along with `.rows`.

So three questions an author must answer before writing a single line had no answer on the public
surface: does a row carry its own `available_at`, are rows ordered by time, and are they grouped by
instrument or interleaved. The reporting journey answered them by registering a throwaway DataModel
whose `compute` printed `sorted(rows[0].keys())` -- a full register-materialize-show cycle spent on
one type's field names -- and then noted the residual risk in their own words: the ordering was
confirmed on one window of three names at one instant, **and every residual in the run depended on
it**.

The docstring now states the guarantee. This is what makes it a guarantee: `scan.observation_rows`
pushes `ORDER BY available_at, <key fields>` into SQL for both lookback shapes, and a change that
drops it fails here rather than in someone's factor.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

import vqapr.public as public
from vqapr.data.datasets import DatasetRegistration
from vqapr.data.lookback import CalendarLookback, RowsLookback
from vqapr.data.requirements import DataRequirement
from vqapr.data.sources import SourceSpec
from vqapr.data.store import DuckDbObservationStore, ObservationBatch
from vqapr.data.windows import ModelWindow
from vqapr.workspace import Workspace

KST = ZoneInfo("Asia/Seoul")
EVALUATED_AT = datetime(2024, 3, 7, 16, tzinfo=KST)


def _window(tmp_path: Path, parquet: Path, requirement: DataRequirement) -> ModelWindow:
    source = SourceSpec.of("prices", parquet)
    public.register_dataset(
        tmp_path,
        DatasetRegistration.of(
            "price_daily",
            "prices",
            instrument_field="instrument",
            available_at="available_at",
            grain="instrument_instant",
            key_fields=("available_at", "instrument"),
            fields={"close": "close", "volume": "volume"},
            field_types={"close": "DOUBLE", "volume": "DOUBLE"},
        ),
        source,
    )
    return ModelWindow(
        evaluation_time=EVALUATED_AT,
        instruments=("A", "B"),
        store=DuckDbObservationStore(Workspace.open(tmp_path)),
        allowed_requirements=(requirement,),
        consumer_id="test-consumer",
    )


def test_the_type_is_reachable_from_the_documented_surface() -> None:
    """The whole of the reporter's finding, as one assertion.

    `vqapr.public` is the surface the skill and every scaffold name. A type an author is required
    to consume, and cannot import from there, sends them into installed source.
    """
    assert public.ObservationBatch is ObservationBatch
    assert "ObservationBatch" in public.__all__
    assert ObservationBatch.__doc__, "the type an author must consume has to say what it holds"


@pytest.mark.parametrize(
    "lookback",
    [RowsLookback(3), CalendarLookback(days=3, timezone="Asia/Seoul")],
    ids=["rows", "calendar"],
)
def test_rows_are_ordered_by_available_at_for_either_lookback(
    tmp_path: Path, model_price_parquet: Path, lookback: object
) -> None:
    """Ascending `available_at`, and both lookback shapes take the same guarantee.

    The scaffold computes `values[-1] / values[0] - 1` and calls it a trailing return, which is
    true only if this holds -- stated by arithmetic, in emitted code, and by nothing else.
    """
    requirement = DataRequirement.of("price_daily", "close", lookback=lookback)
    batch = _window(tmp_path, model_price_parquet, requirement).observations(requirement)

    stamps = [row["available_at"] for row in batch.rows]
    assert stamps == sorted(stamps), "rows must arrive ascending in available_at"
    assert all(stamp <= EVALUATED_AT for stamp in stamps), "and never past the evaluation time"


def test_a_row_carries_its_own_instant_its_name_and_the_declared_aliases(
    tmp_path: Path, model_price_parquet: Path
) -> None:
    """The keys, which were the reporter's first question.

    `available_at` per row rather than per batch is what makes a cross-section constructible: the
    rows of one instant are the ones sharing it, and a name that stopped publishing carries an
    older stamp instead of a missing row.
    """
    requirement = DataRequirement.of("price_daily", "close", lookback=RowsLookback(2))
    batch = _window(tmp_path, model_price_parquet, requirement).observations(requirement)

    assert sorted(batch.rows[0]) == ["available_at", "close", "instrument"], (
        "available_at, instrument, and one key per declared field -- under the requirement's own "
        "alias, not the physical column name"
    )
    assert isinstance(batch.rows[0]["available_at"], datetime)
    assert batch.rows[0]["available_at"].tzinfo is not None
    # The reporter recorded "values arrive as float, not Decimal", measured on their own source.
    # Since `docs/issues/088` that is a property of the DECLARATION: the field is registered as
    # DOUBLE, registration checked the file agrees, and a DOUBLE reaches a model as `float`.
    assert isinstance(batch.rows[0]["close"], float)
    assert batch.rows[0]["close"] == 103.0


def test_a_decimal_column_cannot_become_a_field(tmp_path: Path) -> None:
    """A DOUBLE column reaches a model as `float`; a DECIMAL one is refused at registration.

    This used to prove the opposite -- `float` and `Decimal` in the same row, "both are legal" --
    and `docs/issues/088` reversed it: a model does arithmetic in one numeric type, so the type a
    field arrives as is declared, and a column that cannot be declared cannot be a field.
    """
    import duckdb

    from vqapr.domain.errors import VqaprError

    parquet = tmp_path / "mixed.parquet"
    connection = duckdb.connect()
    try:
        connection.execute(
            f"""COPY (SELECT * FROM (VALUES
              (TIMESTAMPTZ '2024-03-05 15:30:00+09', 'A',
               CAST(100.0 AS DOUBLE), CAST(1.5 AS DECIMAL(10,4)))
            ) AS t(available_at, instrument, as_double, as_decimal))
            TO '{parquet.as_posix()}' (FORMAT PARQUET)"""
        )
    finally:
        connection.close()

    def registration(fields: dict[str, str]) -> DatasetRegistration:
        return DatasetRegistration.of(
            "mixed",
            "mixed-source",
            instrument_field="instrument",
            available_at="available_at",
            grain="instrument_instant",
            key_fields=("available_at", "instrument"),
            fields=fields,
            field_types=dict.fromkeys(fields, "DOUBLE"),
        )

    with pytest.raises(VqaprError) as refused:
        public.register_dataset(
            tmp_path,
            registration({"as_double": "as_double", "as_decimal": "as_decimal"}),
            SourceSpec.of("mixed-source", parquet),
        )
    (failure,) = refused.value.failures
    assert failure.code == "dataset.field_decimal"
    assert "DECIMAL(10,4)" in (failure.observed or "")

    public.register_dataset(
        tmp_path, registration({"as_double": "as_double"}), SourceSpec.of("mixed-source", parquet)
    )
    requirement = DataRequirement.of("mixed", "as_double", lookback=RowsLookback(1))
    window = ModelWindow(
        evaluation_time=EVALUATED_AT,
        instruments=("A",),
        store=DuckDbObservationStore(Workspace.open(tmp_path)),
        allowed_requirements=(requirement,),
        consumer_id="types",
    )

    assert isinstance(window.observations(requirement).rows[0]["as_double"], float)


def test_instruments_interleave_within_an_instant_rather_than_grouping(
    tmp_path: Path, model_price_parquet: Path
) -> None:
    """The third question, and the one a per-instrument reduction hides.

    A model that assumes grouping -- accumulate until the name changes -- produces a well-formed
    wrong answer here rather than an error. Both names appear at every instant, in key order.
    """
    requirement = DataRequirement.of("price_daily", "close", lookback=RowsLookback(2))
    batch = _window(tmp_path, model_price_parquet, requirement).observations(requirement)

    pairs = [(row["available_at"], row["instrument"]) for row in batch.rows]
    assert pairs == sorted(pairs), "ordered by available_at, then the registered key fields"
    assert [name for _, name in pairs] != sorted(name for _, name in pairs), (
        "if this ever sorts by name the batch has become grouped, and the docstring is wrong"
    )

    newest = max(stamp for stamp, _ in pairs)
    cross_section = {row["instrument"] for row in batch.rows if row["available_at"] == newest}
    assert cross_section == {"A", "B"}, "one instant's rows are the cross-section at that instant"
