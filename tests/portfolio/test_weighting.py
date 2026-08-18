"""Weighting is pure, so every property here is checkable from the values alone."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest

from vqapr.portfolio.weighting import (
    WeightingRefusal,
    equal_weight,
    proportional_weight,
    rescale,
    signal_weight,
)

FIXTURE = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "real"


@pytest.fixture(scope="module")
def closes() -> dict[str, Decimal]:
    """One real session of committed closes, used as a magnitude panel."""
    manifest = json.loads((FIXTURE / "fixture.json").read_text(encoding="utf-8"))
    path = FIXTURE / str(manifest["observation_path"])
    con = duckdb.connect()
    try:
        session = con.execute(f"SELECT min(available_at) FROM read_parquet('{path.as_posix()}')")
        rows = con.execute(
            f"SELECT instrument, close FROM read_parquet('{path.as_posix()}')"
            " WHERE available_at = ? ORDER BY instrument",
            [session.fetchone()[0]],
        ).fetchall()
    finally:
        con.close()
    return dict(rows)


ULP = Decimal("1E-27")


def _gross(weights: dict[str, Decimal]) -> Decimal:
    return sum((abs(value) for value in weights.values()), Decimal(0))


def test_signal_weight_sizes_by_signal_strength() -> None:
    weights = signal_weight({"A": Decimal("3"), "B": Decimal("1"), "C": Decimal("-2")})

    assert abs(_gross(weights) - Decimal(1)) < ULP
    assert weights["A"] == Decimal(3) / Decimal(6)
    # Ratios are exact; gross is one only to the precision a Decimal can hold.
    assert abs(weights["A"] - weights["B"] * 3) < ULP
    assert weights["C"] < 0, "the sign comes from the input"


def test_equal_weight_takes_only_direction_from_the_signal() -> None:
    weights = equal_weight({"A": Decimal("9"), "B": Decimal("1"), "C": Decimal("-4")})

    assert abs(_gross(weights) - Decimal(1)) < ULP
    assert abs(weights["A"]) == abs(weights["B"]) == abs(weights["C"]), "equal means equal"
    assert weights["C"] < 0


def test_equal_weight_does_not_select_a_zero_signal() -> None:
    weights = equal_weight({"A": Decimal("1"), "B": Decimal("0"), "C": Decimal("-1")})

    assert weights["B"] == 0, "a zero signal is not a pick"
    assert abs(weights["A"]) == Decimal("0.5")


def test_signal_weight_keeps_a_zero_signal_visible() -> None:
    """Carried at zero rather than dropped, so the universe stays readable."""
    weights = signal_weight({"A": Decimal("1"), "B": Decimal("0")})

    assert set(weights) == {"A", "B"}
    assert weights["B"] == 0


def test_proportional_weight_sizes_by_the_supplied_panel(closes: dict[str, Decimal]) -> None:
    signal = {name: Decimal(1) for name in closes}

    weights = proportional_weight(signal, closes)

    assert abs(_gross(weights) - Decimal(1)) < ULP
    ranked_by_price = sorted(closes, key=lambda name: closes[name])
    ranked_by_weight = sorted(weights, key=lambda name: weights[name])
    assert ranked_by_price == ranked_by_weight, "a bigger magnitude gets a bigger weight"


def test_proportional_weight_takes_direction_from_the_signal_not_the_panel(
    closes: dict[str, Decimal],
) -> None:
    names = sorted(closes)
    signal = {
        name: (Decimal(1) if index % 2 == 0 else Decimal(-1)) for index, name in enumerate(names)
    }

    weights = proportional_weight(signal, closes)

    for index, name in enumerate(names):
        assert (weights[name] > 0) is (index % 2 == 0)


def test_proportional_weight_refuses_a_panel_that_carries_direction() -> None:
    with pytest.raises(WeightingRefusal, match="must be positive"):
        proportional_weight({"A": Decimal("1")}, {"A": Decimal("-100")})


def test_proportional_weight_refuses_incomplete_coverage() -> None:
    with pytest.raises(WeightingRefusal, match="does not cover"):
        proportional_weight({"A": Decimal("1"), "B": Decimal("1")}, {"A": Decimal("100")})


def test_rescale_makes_a_dollar_neutral_book() -> None:
    raw = signal_weight({"A": Decimal("3"), "B": Decimal("1"), "C": Decimal("-2")})

    weights = rescale(raw, long=Decimal("1"), short=Decimal("-1"))

    assert sum(value for value in weights.values() if value > 0) == Decimal(1)
    assert sum(value for value in weights.values() if value < 0) == Decimal(-1)
    assert sum(weights.values()) == 0
    assert abs(weights["A"] - weights["B"] * 3) < ULP, "relative sizes survive rescaling"


def test_rescale_makes_a_fully_invested_long_only_book() -> None:
    raw = equal_weight({"A": Decimal("1"), "B": Decimal("1"), "C": Decimal("1")})

    weights = rescale(raw, long=Decimal("1"), short=Decimal("0"))

    # The declared total is exact; the residual lands on one member, which is the trade-off.
    assert sum(weights.values()) == Decimal(1)
    for value in weights.values():
        assert abs(value - Decimal(1) / Decimal(3)) < ULP


def test_rescale_scales_each_side_independently() -> None:
    raw = signal_weight({"A": Decimal("1"), "B": Decimal("-1")})

    weights = rescale(raw, long=Decimal("2"), short=Decimal("-0.5"))

    assert weights["A"] == Decimal(2)
    assert weights["B"] == Decimal("-0.5")


def test_rescale_accepts_already_scaled_long_short_weights() -> None:
    """Taking an existing signed book and re-budgeting it is the same call."""
    existing = {"A": Decimal("0.6"), "B": Decimal("0.4"), "C": Decimal("-1.0")}

    weights = rescale(existing, long=Decimal("1.5"), short=Decimal("-1.5"))

    assert sum(value for value in weights.values() if value > 0) == Decimal("1.5")
    assert sum(value for value in weights.values() if value < 0) == Decimal("-1.5")
    assert weights["A"] / weights["B"] == Decimal("0.6") / Decimal("0.4")


def test_rescale_refuses_to_invent_a_side_that_does_not_exist() -> None:
    long_only = equal_weight({"A": Decimal("1"), "B": Decimal("1")})

    with pytest.raises(WeightingRefusal, match="holds no short position"):
        rescale(long_only, long=Decimal("1"), short=Decimal("-1"))


def test_rescale_refuses_to_delete_a_side() -> None:
    signed = signal_weight({"A": Decimal("1"), "B": Decimal("-1")})

    with pytest.raises(WeightingRefusal, match="removes positions"):
        rescale(signed, long=Decimal("1"), short=Decimal("0"))


def test_rescale_refuses_a_side_target_with_the_wrong_sign() -> None:
    signed = signal_weight({"A": Decimal("1"), "B": Decimal("-1")})

    with pytest.raises(WeightingRefusal, match="long must not be negative"):
        rescale(signed, long=Decimal("-1"), short=Decimal("-1"))
    with pytest.raises(WeightingRefusal, match="short must not be positive"):
        rescale(signed, long=Decimal("1"), short=Decimal("1"))


def test_a_flexible_book_is_simply_the_unrescaled_result() -> None:
    """Not calling rescale is how a Strategy declares a flexible budget.

    The sizing functions must not quietly fill a budget, so an unrescaled book stays at unit gross
    and a Strategy that narrows it further keeps whatever it chose.
    """
    raw = signal_weight({"A": Decimal("1"), "B": Decimal("-1")})
    narrowed = {name: value * Decimal("0.4") for name, value in raw.items()}

    assert abs(_gross(raw) - Decimal(1)) < ULP
    assert abs(_gross(narrowed) - Decimal("0.4")) < ULP
    assert rescale(narrowed, long=Decimal("1"), short=Decimal("-1")) == rescale(
        raw, long=Decimal("1"), short=Decimal("-1")
    ), "rescaling erases the narrowing, which is exactly why it has to be a separate call"


@pytest.mark.parametrize("builder", [signal_weight, equal_weight])
def test_an_all_zero_signal_is_refused(builder) -> None:
    with pytest.raises(WeightingRefusal, match="nothing to weight"):
        builder({"A": Decimal("0"), "B": Decimal("0")})


@pytest.mark.parametrize("builder", [signal_weight, equal_weight])
def test_an_empty_signal_is_refused(builder) -> None:
    with pytest.raises(WeightingRefusal, match="non-empty"):
        builder({})


@pytest.mark.parametrize("builder", [signal_weight, equal_weight])
def test_a_float_signal_is_refused(builder) -> None:
    with pytest.raises(WeightingRefusal, match="must be a Decimal"):
        builder({"A": 1.0})


def test_weighting_is_pure(closes: dict[str, Decimal]) -> None:
    """Same input, same output, and the caller's mapping is never touched."""
    signal = {name: Decimal(1) for name in closes}
    before = dict(signal)

    first = proportional_weight(signal, closes)
    second = proportional_weight(signal, closes)

    assert first == second
    assert signal == before
