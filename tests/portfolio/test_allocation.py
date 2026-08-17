"""The allocation contract is checked against the committed real benchmark, not invented weights."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest

from vqapr.portfolio.allocation import (
    AllocationInvariants,
    AllocationSign,
    AllocationViolation,
    validate_allocation,
)

FIXTURE = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "real"


@pytest.fixture(scope="module")
def manifest() -> dict[str, object]:
    return json.loads((FIXTURE / "fixture.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def benchmark(manifest: dict[str, object]) -> dict[str, Decimal]:
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


@pytest.fixture(scope="module")
def invariants(manifest: dict[str, object]) -> AllocationInvariants:
    """Tolerance comes from the manifest, never from a package constant."""
    return AllocationInvariants.of(tolerance=Decimal(str(manifest["weight_tolerance"])))


def test_a_real_partial_index_slice_is_accepted(
    benchmark: dict[str, Decimal], invariants: AllocationInvariants
) -> None:
    """The committed slice sums near 0.549; a coverage-scoped invariant must accept it."""
    validated = validate_allocation(benchmark, invariants, label="benchmark")

    assert validated.total < Decimal(1)
    assert validated.uncovered == Decimal(1) - validated.total
    assert validated.uncovered > 0, "the uncovered remainder is cash, not an error"
    assert validated.weights == benchmark


def test_the_uncovered_remainder_is_never_redistributed(
    benchmark: dict[str, Decimal], invariants: AllocationInvariants
) -> None:
    validated = validate_allocation(benchmark, invariants)

    for instrument, weight in benchmark.items():
        assert validated.weights[instrument] == weight, "renormalisation is a rejected option"


def test_overweight_beyond_tolerance_is_refused(invariants: AllocationInvariants) -> None:
    over = {"A": Decimal("0.7"), "B": Decimal("0.4")}

    with pytest.raises(AllocationViolation, match="above the declared"):
        validate_allocation(over, invariants)


def test_a_sum_within_tolerance_is_accepted(manifest: dict[str, object]) -> None:
    tolerance = Decimal(str(manifest["weight_tolerance"]))
    invariants = AllocationInvariants.of(tolerance=tolerance)

    inside = {"A": Decimal("0.5"), "B": Decimal("0.5") + tolerance}
    validated = validate_allocation(inside, invariants)

    assert validated.total == Decimal(1) + tolerance

    outside = {"A": Decimal("0.5"), "B": Decimal("0.5") + tolerance * 2}
    with pytest.raises(AllocationViolation):
        validate_allocation(outside, invariants)


def test_long_only_refuses_a_negative_weight_by_name(invariants: AllocationInvariants) -> None:
    with pytest.raises(AllocationViolation, match="'SHORT'"):
        validate_allocation({"LONG": Decimal("0.4"), "SHORT": Decimal("-0.1")}, invariants)


def test_signed_inputs_are_legal_when_declared(manifest: dict[str, object]) -> None:
    invariants = AllocationInvariants.of(
        sign=AllocationSign.SIGNED,
        weight_sum_upper=Decimal(1),
        tolerance=Decimal(str(manifest["weight_tolerance"])),
    )

    validated = validate_allocation({"LONG": Decimal("0.4"), "SHORT": Decimal("-0.4")}, invariants)

    assert validated.total == 0


def test_missing_required_coverage_is_refused(
    benchmark: dict[str, Decimal], manifest: dict[str, object]
) -> None:
    required = [*sorted(benchmark), "MISSING"]
    invariants = AllocationInvariants.of(
        tolerance=Decimal(str(manifest["weight_tolerance"])), required_coverage=required
    )

    with pytest.raises(AllocationViolation, match="MISSING"):
        validate_allocation(benchmark, invariants)


def test_non_decimal_weights_are_refused(invariants: AllocationInvariants) -> None:
    with pytest.raises(AllocationViolation, match="must be a Decimal"):
        validate_allocation({"A": 0.5}, invariants)  # type: ignore[dict-item]


def test_an_empty_allocation_is_refused(invariants: AllocationInvariants) -> None:
    with pytest.raises(AllocationViolation, match="non-empty"):
        validate_allocation({}, invariants)
