"""Weighting is pure, so every property here is checkable from the values alone."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest

from vqapr.portfolio.optimize import QUANTUM
from vqapr.portfolio.weights import (
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


def test_proportional_weight_keeps_the_signal_strength(closes: dict[str, Decimal]) -> None:
    """A signal twice as strong gets twice the weight for the same panel entry."""
    names = sorted(closes)[:2]
    panel = dict.fromkeys(names, Decimal("100"))
    weights = proportional_weight({names[0]: Decimal("3"), names[1]: Decimal("1")}, panel)

    assert weights[names[0]] == weights[names[1]] * 3


def test_proportional_weight_reduces_to_signal_weight_on_a_uniform_panel(
    closes: dict[str, Decimal],
) -> None:
    """The panel scales the signal; it does not replace it.

    Collapsing onto ``equal_weight`` here would make the function a duplicate of one that
    already exists, and would silently discard the strength the caller supplied.
    """
    signal = {"A": Decimal("3"), "B": Decimal("-1"), "C": Decimal("1")}
    uniform = dict.fromkeys(signal, Decimal("100"))

    assert proportional_weight(signal, uniform) == signal_weight(signal)


def test_proportional_weight_takes_direction_only_from_a_sign_reduced_signal(
    closes: dict[str, Decimal],
) -> None:
    """Direction-only sizing stays available by composing, not by a hidden rule."""
    signal = {"A": Decimal("3"), "B": Decimal("-1"), "C": Decimal("1")}
    panel = {"A": Decimal("300"), "B": Decimal("100"), "C": Decimal("50")}
    sign_only = {
        name: (Decimal(0) if value == 0 else Decimal(1).copy_sign(value))
        for name, value in signal.items()
    }

    weights = proportional_weight(sign_only, panel)

    gross = sum(panel.values(), Decimal(0))
    assert weights["A"] == panel["A"] / gross
    assert weights["B"] == -panel["B"] / gross


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


GRID = Decimal("0.01")


def _on_grid(value: Decimal, grid: Decimal = GRID) -> bool:
    return value == value.quantize(grid)


def test_rescale_on_a_grid_is_both_on_the_grid_and_exactly_on_budget() -> None:
    """The pair is the point: either alone is already available, both together were not."""
    signal = {name: Decimal("1") for name in "ABC"} | {name: Decimal("-1") for name in "DEF"}
    raw = equal_weight(signal)

    weights = rescale(raw, long=Decimal("1"), short=Decimal("-1"), grid=GRID)

    assert sum(value for value in weights.values() if value > 0) == Decimal("1")
    assert sum(value for value in weights.values() if value < 0) == Decimal("-1")
    assert sum(weights.values()) == 0
    for name, value in weights.items():
        assert _on_grid(value), f"{name} is off the grid at {value}"


def test_quantizing_after_rescale_is_what_the_grid_argument_replaces() -> None:
    """Quantizing afterwards re-breaks the total rescale just matched.

    That is the whole reason the argument exists: a caller who quantizes the returned weights has
    to settle a second time by hand to get the declared budget back.
    """
    raw = equal_weight({name: Decimal("1") for name in "ABC"})

    exact = rescale(raw, long=Decimal("1"), short=Decimal("0"))
    quantized_afterwards = {name: value.quantize(GRID) for name, value in exact.items()}

    assert sum(exact.values()) == Decimal("1"), "the exact result is on budget"
    assert sum(quantized_afterwards.values()) == Decimal("0.99"), "quantizing broke it again"

    on_grid = rescale(raw, long=Decimal("1"), short=Decimal("0"), grid=GRID)

    assert sum(on_grid.values()) == Decimal("1")
    assert all(_on_grid(value) for value in on_grid.values())


def test_rescale_on_a_grid_settles_the_residual_on_the_largest_member() -> None:
    raw = signal_weight({"A": Decimal("3"), "B": Decimal("1"), "C": Decimal("1")})

    weights = rescale(raw, long=Decimal("1"), short=Decimal("0"), grid=GRID)

    # 0.6, 0.2, 0.2 land on the grid exactly, so a residual only appears where division does not
    # terminate; the coarse grid below makes one.
    coarse = rescale(
        equal_weight({"A": Decimal("1"), "B": Decimal("1"), "C": Decimal("1")}),
        long=Decimal("1"),
        short=Decimal("0"),
        grid=GRID,
    )

    assert weights == {"A": Decimal("0.60"), "B": Decimal("0.20"), "C": Decimal("0.20")}
    # Every member quantizes to 0.33, so the tie is broken by name and the last one carries it.
    assert coarse == {"A": Decimal("0.33"), "B": Decimal("0.33"), "C": Decimal("0.34")}


def test_rescale_on_a_grid_is_order_independent() -> None:
    forwards = {"A": Decimal("1"), "B": Decimal("1"), "C": Decimal("1")}
    backwards = {"C": Decimal("1"), "B": Decimal("1"), "A": Decimal("1")}

    assert rescale(
        equal_weight(forwards), long=Decimal("1"), short=Decimal("0"), grid=GRID
    ) == rescale(equal_weight(backwards), long=Decimal("1"), short=Decimal("0"), grid=GRID)


def test_rescale_without_a_grid_keeps_the_exact_ratio() -> None:
    """Not passing a grid still returns ratios, not rounded weights."""
    raw = equal_weight({"A": Decimal("1"), "B": Decimal("1"), "C": Decimal("1")})

    weights = rescale(raw, long=Decimal("1"), short=Decimal("0"))

    assert weights["A"] == Decimal(1) / Decimal(3), "the ratio survives, unrounded"
    assert not _on_grid(weights["A"]), "which means it is not on any coarse grid"
    assert sum(weights.values()) == Decimal("1")


def test_rescale_refuses_a_grid_finer_than_the_canonical_one() -> None:
    raw = equal_weight({"A": Decimal("1"), "B": Decimal("1")})

    with pytest.raises(WeightingRefusal, match="finer than the canonical grid"):
        rescale(raw, long=Decimal("1"), short=Decimal("0"), grid=QUANTUM.scaleb(-1))


def test_rescale_refuses_a_budget_that_is_not_on_the_grid() -> None:
    """Weights on a grid cannot sum to a total that is not."""
    raw = equal_weight({"A": Decimal("1"), "B": Decimal("1")})

    with pytest.raises(WeightingRefusal, match="not a multiple of grid"):
        rescale(raw, long=Decimal("1.005"), short=Decimal("0"), grid=GRID)


@pytest.mark.parametrize("grid", [Decimal("0"), Decimal("-0.01")])
def test_rescale_refuses_a_grid_that_is_not_a_positive_step(grid: Decimal) -> None:
    raw = equal_weight({"A": Decimal("1"), "B": Decimal("1")})

    with pytest.raises(WeightingRefusal, match="positive finite step"):
        rescale(raw, long=Decimal("1"), short=Decimal("0"), grid=grid)


def test_rescale_refuses_a_float_grid() -> None:
    raw = equal_weight({"A": Decimal("1"), "B": Decimal("1")})

    with pytest.raises(WeightingRefusal, match="grid must be a Decimal"):
        rescale(raw, long=Decimal("1"), short=Decimal("0"), grid=0.01)


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
