"""The projection must be exact, not approximately exact.

Every assertion here is about a property the milestone actually promises: the budget identity holds
under the caller's own decimal context, frozen names survive bit for bit, cash is the only residual
sink, and precision finer than the canonical grid is refused rather than silently rounded.
"""

from __future__ import annotations

import json
from decimal import Decimal, localcontext
from pathlib import Path
from uuid import UUID

import pytest

from vqapr.portfolio.budgets import Budget, PortfolioDirection
from vqapr.portfolio.intents import (
    EconomicPortfolioIntent,
    PortfolioTarget,
    validate_economic_intent,
)
from vqapr.portfolio.optimize import (
    QUANTIZATION_EXPONENT,
    QUANTUM,
    OptimizeRefusal,
    optimize,
)

FIXTURE = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "real"


@pytest.fixture(scope="module")
def benchmark() -> dict[str, Decimal]:
    """One real session of committed index weights."""
    import duckdb

    manifest = json.loads((FIXTURE / "fixture.json").read_text(encoding="utf-8"))
    path = FIXTURE / str(manifest["benchmark_path"])
    con = duckdb.connect()
    try:
        session = con.execute(
            f"SELECT min(available_at) FROM read_parquet('{path.as_posix()}')"
        ).fetchone()[0]
        rows = con.execute(
            f"""
            SELECT instrument, benchmark_weight FROM read_parquet('{path.as_posix()}')
            WHERE available_at = ? ORDER BY instrument
            """,
            [session],
        ).fetchall()
    finally:
        con.close()
    return {row[0]: row[1] for row in rows}


def _bounds(names, low: str, high: str) -> tuple[dict, dict]:
    return {n: Decimal(low) for n in names}, {n: Decimal(high) for n in names}


def test_scale_zero_reproduces_the_benchmark_exactly(benchmark: dict[str, Decimal]) -> None:
    """With s = 0 the desired portfolio is the benchmark, so nothing may move."""
    lower, upper = _bounds(benchmark, "0", "1")
    result = optimize(
        desired=benchmark,
        current={},
        lower=lower,
        upper=upper,
        cash_range=(Decimal("0"), Decimal("1")),
    )

    for instrument, weight in benchmark.items():
        # Decimal equality, deliberately: the benchmark is committed at the vendor scale while the
        # result lands on the canonical grid, so the two agree in value and differ in str().
        assert result.weights[instrument] == weight
    assert sum(result.weights.values()) + result.cash == Decimal(1)
    assert result.binding_lower == ()
    assert result.binding_upper == ()


def test_cash_absorbs_a_binding_cap_rather_than_another_instrument(
    benchmark: dict[str, Decimal],
) -> None:
    cap = Decimal("0.25")
    lower, upper = _bounds(benchmark, "0", str(cap))
    unaffected = {name for name, weight in benchmark.items() if weight < cap}

    result = optimize(
        desired=benchmark,
        current={},
        lower=lower,
        upper=upper,
        cash_range=(Decimal("0"), Decimal("1")),
    )

    assert set(result.binding_upper) == {name for name, w in benchmark.items() if w >= cap}
    for name in unaffected:
        assert result.weights[name] == benchmark[name], "clipping must not redistribute"
    assert all(weight <= cap for weight in result.weights.values())
    assert sum(result.weights.values()) + result.cash == Decimal(1)


def test_a_fully_invested_book_solves_for_a_nonzero_multiplier() -> None:
    desired = {"A": Decimal("0.6"), "B": Decimal("0.6")}
    lower, upper = _bounds(desired, "0", "1")

    result = optimize(
        desired=desired,
        current={},
        lower=lower,
        upper=upper,
        cash_range=(Decimal("0"), Decimal("0")),
    )

    assert result.multiplier == Decimal("0.1")
    assert result.weights == {"A": Decimal("0.5"), "B": Decimal("0.5")}
    assert result.cash == 0
    assert sum(result.weights.values()) + result.cash == Decimal(1)


def test_frozen_weight_is_returned_verbatim() -> None:
    held = Decimal("0.123456789012")
    result = optimize(
        desired={"A": Decimal("0.5"), "B": Decimal("0.5")},
        current={"B": held},
        lower={"A": Decimal("0"), "B": Decimal("0")},
        upper={"A": Decimal("1"), "B": Decimal("1")},
        frozen=frozenset({"B"}),
        cash_range=(Decimal("0"), Decimal("1")),
    )

    assert result.weights["B"] == held
    assert result.weights["B"].as_tuple() == held.as_tuple(), "frozen must survive bit for bit"


def test_the_budget_identity_holds_in_the_callers_own_context() -> None:
    """The reviewer-mandated check: the identity is verified where the validator actually runs.

    ``optimize`` assembles under its own working precision, but ``validate_economic_intent`` runs in
    whatever context the caller happens to be in. Asserting inside a ``localcontext`` would prove
    nothing, so this constructs a real intent in the ambient context.
    """
    held = Decimal("0.099700000000")
    result = optimize(
        desired={"A": Decimal("0.4"), "B": Decimal("0.4"), "C": Decimal("0.4")},
        current={"C": held},
        lower={"A": Decimal("0"), "B": Decimal("0"), "C": Decimal("0")},
        upper={"A": Decimal("1"), "B": Decimal("1"), "C": Decimal("1")},
        frozen=frozenset({"C"}),
        cash_range=(Decimal("0"), Decimal("0.5")),
    )

    targets = tuple(
        PortfolioTarget(name, weight=weight) for name, weight in sorted(result.weights.items())
    )
    intent = EconomicPortfolioIntent(
        UUID(int=7),
        "strategy",
        targets,
        result.cash,
        Budget(
            PortfolioDirection.LONG_ONLY,
            Decimal("0"),
            Decimal("1"),
            Decimal("0"),
            Decimal("1"),
        ),
        (),
        0,
        None,
    )

    # No localcontext here on purpose.
    assert validate_economic_intent(intent) is intent


def test_every_returned_weight_lands_on_the_canonical_grid() -> None:
    result = optimize(
        desired={"A": Decimal("0.333333333333333"), "B": Decimal("0.5")},
        current={},
        lower={"A": Decimal("0"), "B": Decimal("0")},
        upper={"A": Decimal("1"), "B": Decimal("1")},
        cash_range=(Decimal("0"), Decimal("1")),
    )

    for weight in result.weights.values():
        assert weight.as_tuple().exponent >= QUANTIZATION_EXPONENT
    assert result.cash.as_tuple().exponent >= QUANTIZATION_EXPONENT


@pytest.mark.parametrize(
    ("field", "kwargs"),
    [
        ("lower", {"lower": {"A": Decimal("0.0000000000001")}}),
        ("upper", {"upper": {"A": Decimal("0.9999999999999")}}),
        ("cash_range", {"cash_range": (Decimal("0.0000000000001"), Decimal("1"))}),
    ],
)
def test_inputs_finer_than_the_grid_are_refused_by_name(field: str, kwargs: dict) -> None:
    base = {
        "desired": {"A": Decimal("0.5")},
        "current": {},
        "lower": {"A": Decimal("0")},
        "upper": {"A": Decimal("1")},
        "cash_range": (Decimal("0"), Decimal("1")),
    }
    with pytest.raises(OptimizeRefusal, match="finer than the canonical grid"):
        optimize(**{**base, **kwargs})


def test_a_frozen_holding_finer_than_the_grid_is_refused_at_the_entrance() -> None:
    """Guard the input rather than rounding the output, so frozen invariance stays exact."""
    with pytest.raises(OptimizeRefusal, match=r"current\['B'\]"):
        optimize(
            desired={"A": Decimal("0.5"), "B": Decimal("0.5")},
            current={"B": Decimal("0.0997000000000001")},
            lower={"A": Decimal("0"), "B": Decimal("0")},
            upper={"A": Decimal("1"), "B": Decimal("1")},
            frozen=frozenset({"B"}),
            cash_range=(Decimal("0"), Decimal("1")),
        )


def test_an_unreachable_budget_is_refused_before_any_result() -> None:
    with pytest.raises(OptimizeRefusal, match="infeasible"):
        optimize(
            desired={"A": Decimal("0.5")},
            current={},
            lower={"A": Decimal("0")},
            upper={"A": Decimal("0.1")},
            cash_range=(Decimal("0"), Decimal("0")),
        )


def test_the_solve_is_deterministic_and_order_independent() -> None:
    desired = {"A": Decimal("0.4"), "B": Decimal("0.35"), "C": Decimal("0.3")}
    lower, upper = _bounds(desired, "0", "0.38")
    kwargs = {
        "current": {},
        "lower": lower,
        "upper": upper,
        "cash_range": (Decimal("0"), Decimal("0.05")),
    }

    first = optimize(desired=desired, **kwargs)
    reversed_input = dict(reversed(list(desired.items())))
    second = optimize(desired=reversed_input, **kwargs)

    assert first.weights == second.weights
    assert first.cash == second.cash
    assert first.multiplier == second.multiplier


def test_no_solver_package_is_imported() -> None:
    import sys

    optimize(
        desired={"A": Decimal("0.6"), "B": Decimal("0.6")},
        current={},
        lower={"A": Decimal("0"), "B": Decimal("0")},
        upper={"A": Decimal("1"), "B": Decimal("1")},
        cash_range=(Decimal("0"), Decimal("0")),
    )

    for module in ("cvxpy", "osqp", "quadprog", "scipy.optimize"):
        assert module not in sys.modules, f"{module} must not be needed for a closed-form solve"
    assert Decimal("1E-12") == QUANTUM


def test_the_working_precision_does_not_leak_to_the_caller() -> None:
    """The declared precision owns assembly inside optimize only (Architecture 5.3)."""
    with localcontext() as context:
        context.prec = 9
        before = context.prec
        # A non-zero multiplier is essential here: quantizing zero needs one digit, so an input
        # that solves at lam = 0 would leave this test inert against the very leak it pins.
        result = optimize(
            desired={"A": Decimal("0.6"), "B": Decimal("0.6")},
            current={},
            lower={"A": Decimal("0"), "B": Decimal("0")},
            upper={"A": Decimal("1"), "B": Decimal("1")},
            cash_range=(Decimal("0"), Decimal("0")),
        )
        assert result.multiplier == Decimal("0.1")
        assert sum(result.weights.values()) + result.cash == Decimal(1)
        assert context.prec == before


def test_the_solve_targets_the_near_band_edge_not_the_far_one() -> None:
    """Regression: targeting the far edge still balances the budget but is not the minimiser."""
    desired = {"A": Decimal("0.40"), "B": Decimal("0.35"), "C": Decimal("0.30")}
    lower, upper = _bounds(desired, "0", "0.38")

    result = optimize(
        desired=desired,
        current={},
        lower=lower,
        upper=upper,
        cash_range=(Decimal("0"), Decimal("0.05")),
    )

    objective = sum((result.weights[name] - desired[name]) ** 2 for name in desired)
    assert objective == Decimal("0.000850000000000000000000")
    assert sum(result.weights.values()) + result.cash == Decimal(1)


def test_a_feasible_problem_inside_a_widened_cash_range_is_not_refused() -> None:
    """Regression: the far-edge target made this feasible input raise a false refusal."""
    result = optimize(
        desired={"A": Decimal("0.6"), "B": Decimal("0.6")},
        current={},
        lower={"A": Decimal("0.48"), "B": Decimal("0.48")},
        upper={"A": Decimal("1"), "B": Decimal("1")},
        cash_range=(Decimal("0"), Decimal("0.05")),
    )

    assert result.weights == {"A": Decimal("0.5"), "B": Decimal("0.5")}
    assert sum(result.weights.values()) + result.cash == Decimal(1)


def test_a_frozen_holding_outside_its_own_bound_is_refused() -> None:
    """A freeze and a box are a conjunction; a holding that breaks the box cannot be honoured."""
    with pytest.raises(OptimizeRefusal, match="outside its declared bound"):
        optimize(
            desired={"A": Decimal("0"), "B": Decimal("0")},
            current={"B": Decimal("0.83")},
            lower={"A": Decimal("-1"), "B": Decimal("-0.93")},
            upper={"A": Decimal("1"), "B": Decimal("0.29")},
            frozen=frozenset({"B"}),
            cash_range=(Decimal("-1"), Decimal("1")),
        )


def test_every_free_name_stays_inside_its_box_across_many_shapes() -> None:
    """Property sweep: every shape that solves must respect its own box and the budget.

    The success counter matters: without it a regression that refused every shape would leave this
    test green with zero assertions executed, which is the exact failure mode it exists to catch.
    """
    solved = 0
    for size in range(1, 6):
        for cap in ("0.2", "0.35", "1"):
            names = [f"n{index}" for index in range(size)]
            desired = {
                name: Decimal("0.5") + Decimal(index) / 10 for index, name in enumerate(names)
            }
            lower, upper = _bounds(names, "0", cap)
            try:
                result = optimize(
                    desired=desired,
                    current={},
                    lower=lower,
                    upper=upper,
                    cash_range=(Decimal("0"), Decimal("1")),
                )
            except OptimizeRefusal:
                continue
            solved += 1
            for name in names:
                assert lower[name] <= result.weights[name] <= upper[name]
            assert sum(result.weights.values()) + result.cash == Decimal(1)
    # All fifteen solve. The one that used to be refused (size 4, cap 0.35) reaches its budget
    # exactly at lam = 23/60, but each repeating third rounds up at twelve decimals, so the
    # quantized total overshot by 1e-12 and cash fell just under its declared floor. That was our
    # grid making a solvable problem look infeasible, and the residual is now absorbed. Pinning the
    # count means a regression that refuses any of them fails here.
    assert solved == 15


def test_a_grid_residual_at_the_cash_floor_is_absorbed_not_refused() -> None:
    """A caller passing the natural cash_range must not be refused by our own rounding.

    This shape's exact optimum reaches the budget precisely, so `cash = 0` is feasible. Rounding
    four repeating thirds up at twelve decimals pushed the total over by 1e-12 and cash under its
    floor. That infeasibility was manufactured by the grid, not posed by the caller.
    """
    names = [f"n{index}" for index in range(4)]
    desired = {name: Decimal("0.5") + Decimal(index) / 10 for index, name in enumerate(names)}
    lower, upper = _bounds(names, "0", "0.35")

    result = optimize(
        desired=desired,
        current={},
        lower=lower,
        upper=upper,
        cash_range=(Decimal("0"), Decimal("1")),
    )

    assert result.cash == Decimal("0")
    assert sum(result.weights.values()) + result.cash == Decimal(1)
    for name in names:
        assert lower[name] <= result.weights[name] <= upper[name]


def test_the_absorbed_residual_never_lands_on_a_name_resting_at_a_bound() -> None:
    """The repair must not push a capped name past the cap it was just clipped to."""
    names = [f"n{index}" for index in range(4)]
    desired = {name: Decimal("0.5") + Decimal(index) / 10 for index, name in enumerate(names)}
    lower, upper = _bounds(names, "0", "0.35")

    result = optimize(
        desired=desired,
        current={},
        lower=lower,
        upper=upper,
        cash_range=(Decimal("0"), Decimal("1")),
    )

    for name in result.binding_upper:
        assert result.weights[name] == upper[name], "a capped name must stay exactly at its cap"
    for name in result.binding_lower:
        assert result.weights[name] == lower[name]


def test_a_shortfall_larger_than_the_grid_budget_is_still_refused() -> None:
    """Absorption is for rounding residue only; a genuinely unreachable budget still refuses."""
    with pytest.raises(OptimizeRefusal, match="infeasible"):
        optimize(
            desired={"A": Decimal("0.5")},
            current={},
            lower={"A": Decimal("0")},
            upper={"A": Decimal("0.1")},
            cash_range=(Decimal("0"), Decimal("0")),
        )
