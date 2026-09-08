"""The shapes data takes have names, and they live below everything (record `183`).

A cross-section is still a mapping -- an author's `weights["A"]` and `weights == {...}` mean
what they meant when it was a dict -- and it now carries an instant and the operations its
consumers used to re-write. A series is a column of a panel. The grain lives beside them.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from vqapr import authoring, public
from vqapr.domain.shapes import CrossSection, Grain, Observation, Panel, Series
from vqapr.domain.shapes import Grain as ShapesGrain

AT = datetime(2024, 3, 5, 15, 30, tzinfo=UTC)


def test_a_cross_section_is_a_mapping_and_compares_as_one() -> None:
    section = CrossSection({"B": Decimal("2"), "A": Decimal("1")}, at=AT)

    assert section["A"] == Decimal("1")
    assert "B" in section and "C" not in section
    assert list(section) == ["A", "B"], "kept in id order whatever order it was built in"
    assert section == {"A": Decimal("1"), "B": Decimal("2")}
    assert dict(section.items()) == {"A": Decimal("1"), "B": Decimal("2")}
    assert section.at == AT
    assert section.instruments == ("A", "B")


def test_a_cross_section_refuses_a_bad_name_and_a_naive_instant() -> None:
    with pytest.raises(ValueError, match="instrument id"):
        CrossSection({"a b": Decimal("1")})
    with pytest.raises(ValueError, match="timezone-aware"):
        CrossSection({"A": Decimal("1")}, at=datetime(2024, 3, 5))


def test_elementwise_is_what_merging_bounds_does() -> None:
    lower_a = CrossSection({"A": Decimal("0"), "B": Decimal("-1")})
    lower_b = CrossSection({"A": Decimal("0.1"), "B": Decimal("-0.5")})

    merged = lower_a.elementwise(max, lower_b)

    assert merged == {"A": Decimal("0.1"), "B": Decimal("-0.5")}
    with pytest.raises(ValueError, match="same instruments"):
        lower_a.elementwise(max, CrossSection({"A": Decimal("0")}))


def test_map_where_and_total() -> None:
    weights = CrossSection({"A": Decimal("0.3"), "B": Decimal("-0.2")}, at=AT)

    sizes = weights.map(abs)
    assert sizes == {"A": Decimal("0.3"), "B": Decimal("0.2")}
    assert sizes.at == AT, "a mapped cross-section is the same instant's"
    assert weights.where(lambda value: value < 0) == ("B",)
    assert weights.total(Decimal(0)) == Decimal("0.1")


def test_a_series_is_a_column_with_nulls_where_the_name_had_nothing() -> None:
    series = Series("A", (AT, AT.replace(day=6), AT.replace(day=7)), (1.0, None, 3.0))

    assert len(series) == 3
    assert list(series) == [1.0, None, 3.0]
    assert series.latest() == 3.0
    assert series.present() == (1.0, 3.0)
    assert Series("A", (AT,), (None,)).latest() is None
    with pytest.raises(ValueError, match="one cell per instant"):
        Series("A", (AT,), (1.0, 2.0))


def test_the_grain_and_the_observation_are_domain_facts() -> None:
    assert ShapesGrain is Grain
    assert public.Grain is Grain, "the public door keeps the one enum"
    assert authoring.Observation is Observation, "the author surface re-exports the long row"
    assert {member.value for member in Grain} == {"instrument_instant", "instant", "rows"}
    assert not hasattr(Grain, "POINT"), "a point read is a way of reading, not a grain"


def test_the_public_door_names_the_shapes_an_author_receives() -> None:
    assert public.CrossSection is CrossSection
    assert public.Series is Series
    assert isinstance(Panel, type)
