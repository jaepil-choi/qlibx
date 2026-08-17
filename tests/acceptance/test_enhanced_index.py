"""The seven acceptance criteria, proved end to end on committed real market data.

Each test names the criterion it discharges. Nothing here invents prices or index weights: the
benchmark comes from the committed vendor slice and the alpha is derived from committed closes.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import duckdb
import pytest

from vqapr.constraints.builtin import NoShort, SingleNameCap
from vqapr.constraints.constraint import ConstraintBounds
from vqapr.constraints.evaluation import merged_constraint_bounds, project_constraints
from vqapr.data.datasets import DatasetRegistration
from vqapr.data.requirements import DataRequirement
from vqapr.data.sources import SourceSpec
from vqapr.data.store import DuckDbObservationStore
from vqapr.data.windows import ModelWindow
from vqapr.flow.materialize import AllocationPublicationSpec, publish_run_allocation
from vqapr.portfolio.allocation import (
    AllocationInvariants,
    AllocationSign,
    AllocationViolation,
    validate_allocation,
)
from vqapr.portfolio.budgets import Budget, PortfolioDirection
from vqapr.portfolio.intents import (
    EconomicPortfolioIntent,
    PortfolioTarget,
    validate_economic_intent,
)
from vqapr.portfolio.optimize import QUANTUM, OptimizeRefusal, optimize
from vqapr.workspace import Workspace

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "real"
CAP = Decimal("0.10")


@pytest.fixture(scope="module")
def manifest() -> dict[str, object]:
    return json.loads((FIXTURE / "fixture.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def tolerance(manifest: dict[str, object]) -> Decimal:
    return Decimal(str(manifest["weight_tolerance"]))


@pytest.fixture(scope="module")
def sessions(manifest: dict[str, object]) -> list[datetime]:
    path = FIXTURE / str(manifest["benchmark_path"])
    con = duckdb.connect()
    try:
        rows = con.execute(
            f"SELECT DISTINCT available_at FROM read_parquet('{path.as_posix()}') ORDER BY 1"
        ).fetchall()
    finally:
        con.close()
    return [row[0] for row in rows]


@pytest.fixture(scope="module")
def benchmark(manifest: dict[str, object]) -> dict[datetime, dict[str, Decimal]]:
    """The committed index panel, read as registered data with no synthetic run."""
    path = FIXTURE / str(manifest["benchmark_path"])
    con = duckdb.connect()
    try:
        rows = con.execute(
            f"SELECT available_at, instrument, benchmark_weight"
            f" FROM read_parquet('{path.as_posix()}') ORDER BY 1, 2"
        ).fetchall()
    finally:
        con.close()
    panel: dict[datetime, dict[str, Decimal]] = {}
    for available_at, instrument, weight in rows:
        panel.setdefault(available_at, {})[instrument] = weight
    return panel


@pytest.fixture(scope="module")
def active(manifest: dict[str, object]) -> dict[datetime, dict[str, Decimal]]:
    """A signed active view derived from committed closes, deliberately not long-only."""
    path = FIXTURE / str(manifest["observation_path"])
    con = duckdb.connect()
    try:
        rows = con.execute(
            f"""
            SELECT available_at, instrument,
                   close / (max(close) OVER (PARTITION BY available_at)) - 0.5 AS tilt
            FROM read_parquet('{path.as_posix()}') ORDER BY 1, 2
            """
        ).fetchall()
    finally:
        con.close()
    panel: dict[datetime, dict[str, Decimal]] = {}
    for available_at, instrument, tilt in rows:
        panel.setdefault(available_at, {})[instrument] = Decimal(str(tilt)).quantize(QUANTUM)
    return panel


class _Catalog:
    def __init__(self, registration: DatasetRegistration, source: SourceSpec) -> None:
        self._registration = registration
        self._source = source

    def dataset(self, raw_dataset_id: str) -> DatasetRegistration:
        return self._registration

    def source(self, raw_source_id: str) -> SourceSpec:
        return self._source


def _window(
    manifest: dict[str, object],
    instruments: tuple[str, ...],
    requirement: DataRequirement,
    cutoff: datetime,
) -> ModelWindow:
    registration = DatasetRegistration.of(
        "benchmark_weight_daily",
        "benchmark-source",
        instrument_field="instrument",
        available_at="available_at",
        key_fields=("available_at", "instrument"),
        fields={"benchmark_weight": "benchmark_weight"},
    )
    source = SourceSpec.of("benchmark-source", FIXTURE / str(manifest["benchmark_path"]))
    return ModelWindow(
        evaluation_time=cutoff,
        instruments=instruments,
        store=DuckDbObservationStore(_Catalog(registration, source)),
        allowed_requirements=(requirement,),
    )


def _bounds(
    manifest: dict[str, object],
    benchmark: dict[str, Decimal],
    cutoff: datetime,
    tolerance: Decimal,
) -> ConstraintBounds:
    """Project and intersect the **shipped** constraint set through a real point-in-time window.

    Reimplementing the cap here would let a regression in `SingleNameCap` leave this suite green,
    which would make criterion 4 prove nothing about the code that actually ships.
    """
    instruments = tuple(sorted(benchmark))
    cap = SingleNameCap(
        cap=str(CAP),
        benchmark_dataset_id="benchmark_weight_daily",
        tolerance=str(tolerance),
    )
    window = _window(manifest, instruments, cap.requirements()[0], cutoff)
    return merged_constraint_bounds(project_constraints((NoShort(), cap), window))


@dataclass(frozen=True)
class _Access:
    max_available_at: datetime | None


@dataclass(frozen=True)
class _Evidence:
    run_identity: str
    cutoff: datetime
    strategy_accesses: tuple[_Access, ...]
    decision: object


def _construct(
    manifest: dict[str, object],
    benchmark: dict[str, Decimal],
    active: dict[str, Decimal],
    scale: Decimal,
    tolerance: Decimal,
    cutoff: datetime,
):
    """The canonical construction: desired = bench + s * active, then project."""
    desired = {
        instrument: (weight + scale * active.get(instrument, Decimal(0))).quantize(QUANTUM)
        for instrument, weight in benchmark.items()
    }
    bounds = _bounds(manifest, benchmark, cutoff, tolerance)
    return optimize(
        desired=desired,
        current={},
        lower=dict(bounds.lower),
        upper=dict(bounds.upper),
        cash_range=(Decimal("0"), Decimal("1")),
    )


def test_criterion_3_benchmark_is_consumed_as_registered_data(
    benchmark: dict[datetime, dict[str, Decimal]], sessions: list[datetime]
) -> None:
    """No synthetic run produced this panel; it is committed vendor data read directly."""
    assert len(benchmark) == len(sessions)
    for session in sessions:
        weights = benchmark[session]
        assert weights, "every session must carry index weights"
        assert all(isinstance(weight, Decimal) for weight in weights.values())
        assert sum(weights.values()) < Decimal(1), "a partial index slice never sums to one"


def test_criterion_4_scale_zero_reproduces_the_benchmark_exactly(
    benchmark: dict[datetime, dict[str, Decimal]],
    active: dict[datetime, dict[str, Decimal]],
    sessions: list[datetime],
    tolerance: Decimal,
    manifest: dict[str, object],
) -> None:
    """s = 0 must return the index itself, compared by Decimal equality across a grid change.

    Every committed session, each projecting the shipped constraint set through its own
    point-in-time window, so the identity is proved against real data rather than a sample of it.
    """
    for session in sessions:
        result = _construct(
            manifest, benchmark[session], active.get(session, {}), Decimal(0), tolerance, session
        )
        for instrument, weight in benchmark[session].items():
            assert result.weights[instrument] == weight
        assert sum(result.weights.values()) + result.cash == Decimal(1)


def test_criterion_4_a_signed_tilt_stays_feasible_under_the_constraint_set(
    benchmark: dict[datetime, dict[str, Decimal]],
    active: dict[datetime, dict[str, Decimal]],
    sessions: list[datetime],
    tolerance: Decimal,
    manifest: dict[str, object],
) -> None:
    """A signed active view enters unchanged; long-only emerges from the constraints."""
    session = sessions[0]
    tilt = active[session]
    assert min(tilt.values()) < 0, "the active view must actually be signed"

    bounds = _bounds(manifest, benchmark[session], session, tolerance)
    result = _construct(manifest, benchmark[session], tilt, Decimal("0.5"), tolerance, session)

    for instrument, weight in result.weights.items():
        assert weight >= bounds.lower[instrument] >= Decimal(0)
        assert weight <= bounds.upper[instrument]
    assert sum(result.weights.values()) + result.cash == Decimal(1)


def test_criterion_2_invariant_violations_are_refused_before_mutation(
    benchmark: dict[datetime, dict[str, Decimal]], sessions: list[datetime], tolerance: Decimal
) -> None:
    invariants = AllocationInvariants.of(tolerance=tolerance)
    valid = benchmark[sessions[0]]

    assert validate_allocation(valid, invariants).total < Decimal(1)

    broken = dict(valid)
    broken[next(iter(broken))] = Decimal("-0.01")
    with pytest.raises(AllocationViolation):
        validate_allocation(broken, invariants)

    signed_ok = AllocationInvariants.of(sign=AllocationSign.SIGNED, tolerance=tolerance)
    assert validate_allocation(broken, signed_ok).weights == broken


def test_criterion_5_the_solve_is_deterministic_and_uses_no_solver(
    benchmark: dict[datetime, dict[str, Decimal]],
    active: dict[datetime, dict[str, Decimal]],
    sessions: list[datetime],
    tolerance: Decimal,
    manifest: dict[str, object],
) -> None:
    session = sessions[0]
    first = _construct(
        manifest, benchmark[session], active[session], Decimal("0.5"), tolerance, session
    )
    second = _construct(
        manifest, benchmark[session], active[session], Decimal("0.5"), tolerance, session
    )

    assert first.weights == second.weights
    assert first.cash == second.cash
    assert first.multiplier == second.multiplier
    # cvxpy is a declared project dependency for other work, so the meaningful claim is that this
    # solve path never reaches for it, not that the project has no solver at all. The other three
    # are kept because a future contributor reaching for any of them would be caught here.
    for module in ("cvxpy", "osqp", "quadprog", "scipy.optimize"):
        assert module not in sys.modules


def test_criterion_1_and_6_publish_round_trip_and_point_in_time(
    tmp_path: Path,
    benchmark: dict[datetime, dict[str, Decimal]],
    active: dict[datetime, dict[str, Decimal]],
    sessions: list[datetime],
    tolerance: Decimal,
    manifest: dict[str, object],
) -> None:
    """Publish a real constructed allocation, then read it back exactly and check PIT."""
    Workspace.create(tmp_path)
    session = sessions[0]
    result = _construct(
        manifest, benchmark[session], active[session], Decimal("0.5"), tolerance, session
    )

    intent = EconomicPortfolioIntent(
        UUID(int=21),
        "enhanced-index",
        tuple(PortfolioTarget(n, weight=w) for n, w in sorted(result.weights.items())),
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
    assert validate_economic_intent(intent) is intent

    published = publish_run_allocation(
        tmp_path,
        AllocationPublicationSpec.of("enhanced_index_allocation"),
        [_Evidence("run-ei", session, (_Access(session),), intent)],
    )

    con = duckdb.connect()
    try:
        table = f"read_parquet('{published.output_path.as_posix()}')"
        rows = con.execute(f"SELECT instrument, weight FROM {table} ORDER BY 1").fetchall()
        before = con.execute(
            f"SELECT count(*) FROM {table} WHERE available_at <= ?",
            [session - timedelta(seconds=1)],
        ).fetchone()[0]
    finally:
        con.close()

    by_instrument = dict(rows)
    for target in intent.targets:
        # Criterion 1: exact equality against the accepted intent weight.
        assert by_instrument[target.instrument_id] == target.weight
    assert before == 0, "criterion 6: nothing is visible before the derived stamp"

    lineage = json.loads(published.lineage_path.read_text(encoding="utf-8"))
    assert lineage["run"]["run_identity"] == ["run-ei"]
    assert lineage["operation"] == "strategy.allocation"


def test_criterion_7_a_frozen_holding_survives_into_a_validated_intent(
    benchmark: dict[datetime, dict[str, Decimal]],
    sessions: list[datetime],
    tolerance: Decimal,
    manifest: dict[str, object],
) -> None:
    """The reviewer-mandated check, run in the ambient context outside any localcontext."""
    session = sessions[0]
    weights = benchmark[session]
    held = next(iter(sorted(weights)))
    holding = Decimal("0.099700000000")
    bounds = _bounds(manifest, weights, session, tolerance)

    result = optimize(
        desired={k: v for k, v in weights.items()},
        current={held: holding},
        lower=dict(bounds.lower),
        upper=dict(bounds.upper),
        frozen=frozenset({held}),
        cash_range=(Decimal("0"), Decimal("1")),
    )

    assert result.weights[held] == holding
    assert result.weights[held].as_tuple() == holding.as_tuple()

    intent = EconomicPortfolioIntent(
        UUID(int=22),
        "enhanced-index",
        tuple(PortfolioTarget(n, weight=w) for n, w in sorted(result.weights.items())),
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
    assert validate_economic_intent(intent) is intent


def test_a_frozen_holding_finer_than_the_grid_is_refused(
    benchmark: dict[datetime, dict[str, Decimal]],
    sessions: list[datetime],
    tolerance: Decimal,
    manifest: dict[str, object],
) -> None:
    session = sessions[0]
    weights = benchmark[session]
    held = next(iter(sorted(weights)))
    bounds = _bounds(manifest, weights, session, tolerance)

    with pytest.raises(OptimizeRefusal, match="finer than the canonical grid"):
        optimize(
            desired=dict(weights),
            current={held: Decimal("0.0997000000000001")},
            lower=dict(bounds.lower),
            upper=dict(bounds.upper),
            frozen=frozenset({held}),
            cash_range=(Decimal("0"), Decimal("1")),
        )
