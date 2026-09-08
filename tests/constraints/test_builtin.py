"""The shipped constraints, exercised on all three consumers with real benchmark data."""

from __future__ import annotations

import json
from datetime import UTC, datetime, time
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest

from tests.constraints.support import reading_call, weightless_call
from vqapr.authoring import (
    Constraint,
    ConstraintBounds,
    EconomicAccountView,
)
from vqapr.constraints.builtin import (
    SHIPPED_CONSTRAINTS,
    NoShort,
    SingleNameCap,
    shipped_constraint_path,
)
from vqapr.constraints.evaluation import (
    build_account_view,
    merged_constraint_bounds,
    project_constraints,
)
from vqapr.data.datasets import DatasetRegistration
from vqapr.data.lookback import RowsLookback
from vqapr.data.requirements import DataRequirement
from vqapr.data.sources import SourceSpec
from vqapr.data.store import DuckDbObservationStore
from vqapr.data.windows import ModelWindow
from vqapr.domain.account_state import AccountSnapshot
from vqapr.domain.values import LocalInstantDeclaration, Mark, MarkBatch
from vqapr.portfolio.allocation import AllocationViolation

FIXTURE = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "real"
VENUE = "Asia/Seoul"
@pytest.fixture(scope="module")
def manifest() -> dict[str, object]:
    return json.loads((FIXTURE / "fixture.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def instruments(manifest: dict[str, object]) -> tuple[str, ...]:
    return tuple(sorted(str(row["ticker"]) for row in manifest["universe"]))


class _Catalog:
    def __init__(self, registration: DatasetRegistration, source: SourceSpec) -> None:
        self._registration = registration
        self._source = source

    def dataset(self, raw_dataset_id: str) -> DatasetRegistration:
        return self._registration

    def source(self, raw_source_id: str) -> SourceSpec:
        return self._source


def _benchmark_window(
    manifest: dict[str, object], instruments: tuple[str, ...], requirement: DataRequirement
) -> ModelWindow:
    registration = DatasetRegistration.of(
        "benchmark_weight_daily",
        "benchmark-source",
        instrument_field="instrument",
        available_at="available_at",
        grain="instrument_instant",
        key_fields=("available_at", "instrument"),
        fields={"benchmark_weight": "CAST(benchmark_weight AS DOUBLE)"},
        field_types={"benchmark_weight": "DOUBLE"},
    )
    source = SourceSpec.of("benchmark-source", FIXTURE / str(manifest["benchmark_path"]))
    session = datetime.fromisoformat(str(manifest["last_session"])).date()
    cutoff = LocalInstantDeclaration(session, time(16, 0), VENUE, 0, "+09:00").instant
    return ModelWindow(
        evaluation_time=cutoff,
        instruments=instruments,
        store=DuckDbObservationStore(_Catalog(registration, source)),
        allowed_requirements=(requirement,),
        consumer_id="test-consumer",
    )


def _cap(manifest: dict[str, object], cap: str = "0.10") -> SingleNameCap:
    return SingleNameCap(
        cap=cap,
        benchmark_dataset_id="benchmark_weight_daily",
        tolerance=str(manifest["weight_tolerance"]),
    )


def _latest_benchmark(
    manifest: dict[str, object], instruments: tuple[str, ...]
) -> dict[str, Decimal]:
    """Read the benchmark weights the projection should be derived from, independently."""
    path = FIXTURE / str(manifest["benchmark_path"])
    con = duckdb.connect()
    try:
        session = con.execute(
            f"SELECT max(available_at) FROM read_parquet('{path.as_posix()}')"
        ).fetchone()[0]
        rows = con.execute(
            f"SELECT instrument, benchmark_weight FROM read_parquet('{path.as_posix()}')"
            " WHERE available_at = ?",
            [session],
        ).fetchall()
    finally:
        con.close()
    weights = dict(rows)
    return {instrument: weights.get(instrument, Decimal(0)) for instrument in instruments}


def _view(account: AccountSnapshot, marks: MarkBatch) -> EconomicAccountView:
    """The author's view of a marked account, via the one function production uses."""
    return build_account_view(account, marks, datetime(2024, 1, 2, 15, 30, tzinfo=UTC))


def test_both_builtins_satisfy_the_full_constraint_contract() -> None:
    """All five abstract members, or the class cannot be instantiated at all."""
    assert sorted(SHIPPED_CONSTRAINTS) == ["no_short", "single_name_cap"]
    for name, cls in SHIPPED_CONSTRAINTS.items():
        assert issubclass(cls, Constraint)
        assert shipped_constraint_path(name).is_file()
    with pytest.raises(KeyError, match="unknown shipped constraint"):
        shipped_constraint_path("not_a_builtin")


def test_no_short_projects_both_bounds_for_every_instrument(
    instruments: tuple[str, ...],
) -> None:
    """A lower-only projection is inexpressible: evaluation rejects partial coverage."""
    bounds = NoShort().project(weightless_call(instruments))

    assert set(bounds.lower_weights) == set(instruments)
    assert set(bounds.upper_weights) == set(instruments)
    assert all(value == Decimal("0") for value in bounds.lower_weights.values())


def test_no_short_measures_the_worst_negative_holding_and_its_excess() -> None:
    """The arithmetic, kept from the member that judged decisions and now asked of the book.

    Measured on quantity, deliberately: a short is a negative holding whatever its price does,
    and reading a weight here would make the answer move with a NAV the rule does not care about.
    """
    constraint = NoShort()
    bounds = constraint.project(weightless_call(("LONG", "SHORT")))
    marks = MarkBatch((Mark("LONG", Decimal("1"), Decimal("10"), Decimal("10")),), Decimal("10"))

    clean = constraint.monitor(
        weightless_call(("LONG", "SHORT")),
        _view(AccountSnapshot(1, Decimal("100"), {"LONG": Decimal("5"), "SHORT": Decimal("2")}), marks),
        bounds,
    )
    dirty = constraint.monitor(
        weightless_call(("LONG", "SHORT")),
        _view(AccountSnapshot(1, Decimal("100"), {"LONG": Decimal("6"), "SHORT": Decimal("-2")}), marks),
        bounds,
    )

    assert clean.passed
    assert not dirty.passed
    assert dirty.measured == Decimal("-2")
    assert dirty.excess == Decimal("2")
    assert dirty.offenders == ("SHORT",)


def test_no_short_monitors_the_committed_account() -> None:
    constraint = NoShort()
    bounds = constraint.project(weightless_call(("A", "B")))
    marks = MarkBatch((Mark("A", Decimal("1"), Decimal("10"), Decimal("10")),), Decimal("10"))

    short = AccountSnapshot(3, Decimal("100"), {"A": Decimal("1"), "B": Decimal("-2")})
    finding = constraint.monitor(
        weightless_call(("A", "B")), _view(short, marks), bounds
    )

    assert not finding.passed
    assert finding.offenders == ("B",)


def test_single_name_cap_projects_from_real_benchmark_data(
    manifest: dict[str, object], instruments: tuple[str, ...]
) -> None:
    """A name may always be held at its index weight; the cap governs the active part."""
    constraint = _cap(manifest)
    window = _benchmark_window(manifest, instruments, constraint.requirements()[0])

    bounds = constraint.project(reading_call(window, instruments, constraint))

    assert set(bounds.upper_weights) == set(instruments)
    for instrument in instruments:
        assert bounds.upper_weights[instrument] >= constraint.cap
    # The largest real index weight exceeds the 0.10 cap, so the projection must lift it.
    assert max(bounds.upper_weights.values()) > constraint.cap


def test_single_name_cap_refuses_an_invariant_violating_benchmark(
    manifest: dict[str, object], tmp_path: Path
) -> None:
    """Failing inside project() keeps a bad benchmark from ever reaching optimize().

    The invalid panel is written here on purpose: the point under test is that the guard fires, and
    real vendor data is valid, so a violation has to be constructed to observe the refusal at all.
    """
    import duckdb

    bad = tmp_path / "bad_benchmark.parquet"
    con = duckdb.connect()
    try:
        con.execute(
            f"""
            COPY (
              SELECT available_at, instrument, -benchmark_weight AS benchmark_weight
              FROM read_parquet('{(FIXTURE / str(manifest["benchmark_path"])).as_posix()}')
            ) TO '{bad.as_posix()}' (FORMAT PARQUET)
            """
        )
    finally:
        con.close()

    instruments = tuple(sorted(str(row["ticker"]) for row in manifest["universe"]))
    constraint = _cap(manifest)
    requirement = constraint.requirements()[0]
    registration = DatasetRegistration.of(
        "benchmark_weight_daily",
        "benchmark-source",
        instrument_field="instrument",
        available_at="available_at",
        grain="instrument_instant",
        key_fields=("available_at", "instrument"),
        fields={"benchmark_weight": "CAST(benchmark_weight AS DOUBLE)"},
        field_types={"benchmark_weight": "DOUBLE"},
    )
    session = datetime.fromisoformat(str(manifest["last_session"])).date()
    window = ModelWindow(
        evaluation_time=LocalInstantDeclaration(session, time(16, 0), VENUE, 0, "+09:00").instant,
        instruments=instruments,
        store=DuckDbObservationStore(
            _Catalog(registration, SourceSpec.of("benchmark-source", bad))
        ),
        allowed_requirements=(requirement,),
        consumer_id="test-consumer",
    )

    with pytest.raises(AllocationViolation, match="long_only"):
        constraint.project(reading_call(window, instruments, constraint))


def test_single_name_cap_measures_excess_above_its_projected_ceiling(
    manifest: dict[str, object], instruments: tuple[str, ...]
) -> None:
    constraint = _cap(manifest)
    window = _benchmark_window(manifest, instruments, constraint.requirements()[0])
    bounds = constraint.project(reading_call(window, instruments, constraint))

    smallest = min(instruments, key=lambda name: bounds.upper_weights[name])
    ceiling = bounds.upper_weights[smallest]

    over = constraint._worst({smallest: ceiling + Decimal("0.05")}, bounds)
    under = constraint._worst({smallest: ceiling}, bounds)

    assert over[2] == (smallest,)
    assert over[0] - over[1] == Decimal("0.05")
    assert under[2] == (), "holding exactly at the projected bound is legal"


def test_single_name_cap_monitors_marked_weights(
    manifest: dict[str, object], instruments: tuple[str, ...]
) -> None:
    constraint = _cap(manifest)
    window = _benchmark_window(manifest, instruments, constraint.requirements()[0])
    bounds = constraint.project(reading_call(window, instruments, constraint))

    heavy = instruments[0]
    marks = MarkBatch((Mark(heavy, Decimal("1"), Decimal("900"), Decimal("900")),), Decimal("900"))
    account = AccountSnapshot(5, Decimal("100"), {heavy: Decimal("1")})

    finding = constraint.monitor(
        reading_call(window, instruments, constraint), _view(account, marks), bounds
    )

    assert finding.measured == Decimal("0.9")
    assert not finding.passed
    assert finding.offenders == (heavy,)


def test_long_only_emerges_from_intersecting_the_two_builtins(
    manifest: dict[str, object], instruments: tuple[str, ...]
) -> None:
    """The point of shipping both: a signed input is narrowed to long-only by the set."""
    cap = _cap(manifest)
    window = _benchmark_window(manifest, instruments, cap.requirements()[0])

    projected = project_constraints((NoShort(), cap), window)
    merged = merged_constraint_bounds(projected)

    # Independently read the benchmark rather than restating the merged bound on both sides of the
    # equality: the expectation has to come from the data, or the assertion cannot fail.
    expected = _latest_benchmark(manifest, instruments)
    above = [name for name in instruments if expected[name] > cap.cap]
    below = [name for name in instruments if expected[name] <= cap.cap]
    assert above and below, "the real slice must straddle the cap for this test to mean anything"

    assert all(value == Decimal("0") for value in merged.lower_weights.values()), (
        "the floor comes from NoShort alone: the cap projects a symmetric box, and the max of the "
        "two lower bounds is zero"
    )
    # And the cap on its own does NOT floor at zero, or the line above would hold whether or not
    # NoShort were in the set -- which is what made `NoShort`'s claim to be *the* projection that
    # removes the short leg false (issue 014).
    cap_alone = merged_constraint_bounds(project_constraints((cap,), window))
    assert all(value < Decimal("0") for value in cap_alone.lower_weights.values())
    for instrument in instruments:
        assert cap_alone.lower_weights[instrument] == -cap_alone.upper_weights[instrument], (
            "the cap bounds size, so its floor mirrors its ceiling rather than flooring at zero"
        )
    for instrument in above:
        assert merged.upper_weights[instrument] == expected[instrument], (
            "a name already heavier than the cap keeps its index weight as its ceiling"
        )
    for instrument in below:
        assert merged.upper_weights[instrument] == cap.cap
    assert isinstance(merged, ConstraintBounds)


def test_the_cap_gives_one_answer_about_a_short_across_both_members(
    manifest: dict[str, object], instruments: tuple[str, ...]
) -> None:
    """One rule, one book, one answer -- which once took three (issue 014).

    `project` floored at zero and forbade a short outright; a second member measured the signed
    weight and permitted it; a third measured the absolute one and reported it. So a signed
    intent passed the check that runs BEFORE execution and was reported as a violation by the one
    that runs AFTER it, while the box handed to the optimiser had excluded it in the first place.

    **Two of those three are now one.** Record `130` removed the member that judged the decision,
    so the remaining pair is what this pins: the box `project` hands out, and the measurement
    `monitor` makes. A third answer has nowhere left to come from.
    """
    cap = _cap(manifest)
    window = _benchmark_window(manifest, instruments, cap.requirements()[0])
    bounds = merged_constraint_bounds(project_constraints((cap,), window))
    name = instruments[0]
    ceiling = bounds.upper_weights[name]

    for size, expected in ((ceiling * 2, False), (ceiling / 2, True)):
        short = {name: -size}
        inside = bounds.lower_weights[name] <= short[name] <= bounds.upper_weights[name]
        # What `monitor` feeds `_worst`: the marked weight as a magnitude.
        _, _, offenders = cap._worst({name: size}, bounds)

        assert inside is expected, f"project disagreed at {size}"
        assert (not offenders) is expected, f"monitor disagreed at {size}"


def test_a_project_local_constraint_still_loads_alongside_a_builtin(tmp_path: Path) -> None:
    """Shipping builtins must not close a canonically open extension point."""
    from vqapr.extension.component import ComponentKind, ComponentRef
    from vqapr.extension.fingerprint import fingerprint_component
    from vqapr.extension.loading import load_constraint

    source = tmp_path / "local_constraint.py"
    source.write_text(
        """from __future__ import annotations

from decimal import Decimal

from vqapr.authoring import (
    Constraint,
    ConstraintBounds,
    ConstraintFinding,
    EconomicAccountView,
    Rebalance,
)
from vqapr.authoring import ConstraintFinding


class LocalCap(Constraint):
    @property
    def constraint_id(self):
        return "local-cap"

    def project(self, call):
        return ConstraintBounds(
            lower_weights={i: Decimal("0") for i in call.instruments},
            upper_weights={i: Decimal("1") for i in call.instruments},
        )

    def monitor(self, call, account, bounds):
        return ConstraintFinding(
            passed=True, measured=Decimal("0"), bound=Decimal("1"), excess=Decimal("0"), details={}
        )
""",
        encoding="utf-8",
    )
    ref = ComponentRef.of(
        "local-cap",
        ComponentKind.CONSTRAINT,
        source,
        "LocalCap",
        fingerprint=fingerprint_component(
            source, kind=ComponentKind.CONSTRAINT, object_name="LocalCap"
        ),
    )

    loaded = load_constraint(ref, project_root=tmp_path)

    assert isinstance(loaded, Constraint)
    assert loaded.constraint_id == "local-cap"
    assert not isinstance(loaded, tuple(SHIPPED_CONSTRAINTS.values()))


def test_configured_decimals_must_be_strings(manifest: dict[str, object]) -> None:
    for bad in (0.1, None, "", "not-a-number", "-0.1"):
        with pytest.raises(ValueError):
            SingleNameCap(
                cap=bad,  # type: ignore[arg-type]
                benchmark_dataset_id="benchmark_weight_daily",

                tolerance=str(manifest["weight_tolerance"]),
            )


def test_requirements_name_the_configured_benchmark_dataset_and_field(
    manifest: dict[str, object],
) -> None:
    """A requirement names the pair: which dataset, and which field on it."""
    constraint = _cap(manifest)
    requirement = constraint.requirements()[0]

    assert str(requirement.dataset_id) == "benchmark_weight_daily"
    assert requirement.field_id == "benchmark_weight"
    assert requirement.lookback == RowsLookback(1)
    assert NoShort().requirements() == ()


def test_single_name_cap_enforces_its_declared_tolerance_on_the_real_projection(
    manifest: dict[str, object], tmp_path: Path
) -> None:
    """The tolerance must bind where it is actually consulted, not only in the helper.

    `validate_allocation` is unit-tested directly, but the shipped constraint is what a run calls.
    This drives a benchmark inflated past the declared allowance through a real point-in-time window
    and asserts `project()` itself refuses, so the allowance cannot quietly stop being enforced on
    the path that matters.
    """
    import duckdb

    instruments = tuple(sorted(str(row["ticker"]) for row in manifest["universe"]))
    tolerance = Decimal(str(manifest["weight_tolerance"]))
    inflated = tmp_path / "inflated_benchmark.parquet"
    source = FIXTURE / str(manifest["benchmark_path"])

    con = duckdb.connect()
    try:
        # Scale the real panel so its per-date sum clears 1 + tolerance by a wide margin.
        con.execute(
            f"""
            COPY (
              SELECT available_at, instrument, benchmark_weight * 4 AS benchmark_weight
              FROM read_parquet('{source.as_posix()}')
            ) TO '{inflated.as_posix()}' (FORMAT PARQUET)
            """
        )
    finally:
        con.close()

    constraint = _cap(manifest)
    requirement = constraint.requirements()[0]
    registration = DatasetRegistration.of(
        "benchmark_weight_daily",
        "benchmark-source",
        instrument_field="instrument",
        available_at="available_at",
        grain="instrument_instant",
        key_fields=("available_at", "instrument"),
        fields={"benchmark_weight": "CAST(benchmark_weight AS DOUBLE)"},
        field_types={"benchmark_weight": "DOUBLE"},
    )
    session = datetime.fromisoformat(str(manifest["last_session"])).date()
    window = ModelWindow(
        evaluation_time=LocalInstantDeclaration(session, time(16, 0), VENUE, 0, "+09:00").instant,
        instruments=instruments,
        store=DuckDbObservationStore(
            _Catalog(registration, SourceSpec.of("benchmark-source", inflated))
        ),
        allowed_requirements=(requirement,),
        consumer_id="test-consumer",
    )

    with pytest.raises(AllocationViolation, match="above the declared"):
        constraint.project(reading_call(window, instruments, constraint))

    # The unmodified panel, well under the ceiling, still projects cleanly.
    assert tolerance > 0
    clean = _benchmark_window(manifest, instruments, requirement)
    assert constraint.project(reading_call(clean, instruments, constraint)).upper_weights
