"""The shipped compliance rules, exercised on the marked account with real benchmark data.

Design §7.2: a rule observes the committed book on the market clock with its own parameters. The
box the strategy built inside is `vqapr.portfolio.bounds`' business (`tests/portfolio/test_bounds.py`);
what is pinned here is that the rule of the same name measures the same ceiling from the same data,
so the two declarations of one cap agree when they are given the same number -- and are still two
declarations.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, time
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest

from tests.component.compliance.support import reading_call, weightless_call
from vqapr.authoring import Compliance, EconomicAccountView
from vqapr.component.compliance.no_short import NoShort
from vqapr.component.compliance.shipped import SHIPPED_COMPLIANCE, shipped_compliance_path
from vqapr.component.compliance.single_name_cap import SingleNameCap
from vqapr.data.dataset import DatasetRegistration
from vqapr.data.lookback import RowsLookback
from vqapr.data.requirement import DataRequirement
from vqapr.data.source import SourceSpec
from vqapr.data.store import DuckDbObservationStore
from vqapr.data.window import ModelWindow
from vqapr.domain.account import AccountSnapshot, Mark, MarkBatch
from vqapr.domain.instants import LocalInstantDeclaration
from vqapr.flow.run.compliance import build_account_view
from vqapr.portfolio.allocation import AllocationViolation
from vqapr.portfolio.bounds import single_name_cap

FIXTURE = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "real"
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


def _registration() -> DatasetRegistration:
    return DatasetRegistration.of(
        "benchmark_weight_daily",
        "benchmark-source",
        instrument_field="instrument",
        available_at="available_at",
        grain="instrument_instant",
        key_fields=("available_at", "instrument"),
        fields={"benchmark_weight": "CAST(benchmark_weight AS DOUBLE)"},
        field_types={"benchmark_weight": "DOUBLE"},
    )


def _window_over(
    manifest: dict[str, object],
    instruments: tuple[str, ...],
    requirement: DataRequirement,
    path: Path,
) -> ModelWindow:
    session = datetime.fromisoformat(str(manifest["last_session"])).date()
    cutoff = LocalInstantDeclaration(session, time(16, 0), VENUE, 0, "+09:00").instant
    return ModelWindow(
        evaluation_time=cutoff,
        instruments=instruments,
        store=DuckDbObservationStore(
            _Catalog(_registration(), SourceSpec.of("benchmark-source", path))
        ),
        allowed_requirements=(requirement,),
        consumer_id="test-consumer",
    )


def _benchmark_window(
    manifest: dict[str, object], instruments: tuple[str, ...], requirement: DataRequirement
) -> ModelWindow:
    return _window_over(manifest, instruments, requirement, FIXTURE / str(manifest["benchmark_path"]))


def _cap(manifest: dict[str, object], cap: str = "0.10") -> SingleNameCap:
    return SingleNameCap(
        cap=cap,
        benchmark_dataset_id="benchmark_weight_daily",
        tolerance=str(manifest["weight_tolerance"]),
    )


def _latest_benchmark(
    manifest: dict[str, object], instruments: tuple[str, ...]
) -> dict[str, Decimal]:
    """Read the benchmark weights the ceiling should be derived from, independently."""
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


def _scaled_benchmark(manifest: dict[str, object], path: Path, factor: str) -> Path:
    source = FIXTURE / str(manifest["benchmark_path"])
    con = duckdb.connect()
    try:
        con.execute(
            f"""
            COPY (
              SELECT available_at, instrument, benchmark_weight * {factor} AS benchmark_weight
              FROM read_parquet('{source.as_posix()}')
            ) TO '{path.as_posix()}' (FORMAT PARQUET)
            """
        )
    finally:
        con.close()
    return path


def test_both_builtins_satisfy_the_compliance_contract() -> None:
    assert sorted(SHIPPED_COMPLIANCE) == ["no_short", "single_name_cap"]
    for name, cls in SHIPPED_COMPLIANCE.items():
        assert issubclass(cls, Compliance)
        assert shipped_compliance_path(name).is_file()
    with pytest.raises(KeyError, match="unknown shipped compliance rule"):
        shipped_compliance_path("not_a_builtin")


def test_no_short_measures_the_worst_negative_holding_and_its_excess() -> None:
    """Measured on quantity, deliberately: a short is a negative holding whatever its price does,
    and reading a weight here would make the answer move with a NAV the rule does not care
    about."""
    rule = NoShort()
    marks = MarkBatch((Mark("LONG", Decimal("1"), Decimal("10"), Decimal("10")),), Decimal("10"))

    clean = rule.observe(
        weightless_call(
            ("LONG", "SHORT"),
            account=_view(
                AccountSnapshot(1, Decimal("100"), {"LONG": Decimal("5"), "SHORT": Decimal("2")}),
                marks,
            ),
        )
    )
    dirty = rule.observe(
        weightless_call(
            ("LONG", "SHORT"),
            account=_view(
                AccountSnapshot(1, Decimal("100"), {"LONG": Decimal("6"), "SHORT": Decimal("-2")}),
                marks,
            ),
        )
    )

    assert clean.passed
    assert not dirty.passed
    assert dirty.measured == Decimal("-2")
    assert dirty.excess == Decimal("2")
    assert dirty.offenders == ("SHORT",)
    assert NoShort().requirements() == (), "a rule about a holding's sign reads nothing"


def test_single_name_cap_ceilings_come_from_real_benchmark_data(
    manifest: dict[str, object], instruments: tuple[str, ...]
) -> None:
    """A name may always be held at its index weight; the cap governs the active part."""
    rule = _cap(manifest)
    window = _benchmark_window(manifest, instruments, rule.requirements()[0])

    ceilings = rule.ceilings(reading_call(window, instruments, rule))

    assert set(ceilings) == set(instruments)
    for instrument in instruments:
        assert ceilings[instrument] >= rule.cap
    # The largest real index weight exceeds the 0.10 cap, so the ceiling must lift there.
    assert max(ceilings.values()) > rule.cap


def test_the_rule_and_the_kit_derive_the_same_ceiling_from_the_same_number(
    manifest: dict[str, object], instruments: tuple[str, ...]
) -> None:
    """Two declarations of one cap (design §7.2): the strategy's kit call and the rule's own
    parameter. Given the same number and the same benchmark, they agree -- which is what lets
    the report read a disagreement as information rather than as noise."""
    rule = _cap(manifest)
    window = _benchmark_window(manifest, instruments, rule.requirements()[0])
    expected = _latest_benchmark(manifest, instruments)

    observed = rule.ceilings(reading_call(window, instruments, rule))
    _, built = single_name_cap(instruments, expected, rule.cap)

    assert observed == built
    above = [name for name in instruments if expected[name] > rule.cap]
    assert above, "the real slice must straddle the cap for this test to mean anything"
    for instrument in above:
        assert observed[instrument] == expected[instrument]


def test_single_name_cap_refuses_an_invariant_violating_benchmark(
    manifest: dict[str, object], instruments: tuple[str, ...], tmp_path: Path
) -> None:
    """A bad benchmark fails the observation rather than assuming a zero weight. The invalid
    panel is written here on purpose: real vendor data is valid, so a violation has to be
    constructed to observe the refusal at all."""
    rule = _cap(manifest)
    window = _window_over(
        manifest,
        instruments,
        rule.requirements()[0],
        _scaled_benchmark(manifest, tmp_path / "bad_benchmark.parquet", "-1"),
    )
    marks = MarkBatch((Mark(instruments[0], Decimal("1"), Decimal("9"), Decimal("9")),), Decimal("9"))
    account = AccountSnapshot(5, Decimal("1"), {instruments[0]: Decimal("1")})

    with pytest.raises(AllocationViolation, match="long_only"):
        rule.observe(reading_call(window, instruments, rule, account=_view(account, marks)))


def test_single_name_cap_measures_excess_above_its_ceiling(
    manifest: dict[str, object], instruments: tuple[str, ...]
) -> None:
    rule = _cap(manifest)
    window = _benchmark_window(manifest, instruments, rule.requirements()[0])
    ceilings = rule.ceilings(reading_call(window, instruments, rule))

    smallest = min(instruments, key=lambda name: ceilings[name])
    ceiling = ceilings[smallest]

    over = rule._worst({smallest: ceiling + Decimal("0.05")}, ceilings)
    under = rule._worst({smallest: ceiling}, ceilings)

    assert over[2] == (smallest,)
    assert over[0] - over[1] == Decimal("0.05")
    assert under[2] == (), "holding exactly at the ceiling is legal"


def test_single_name_cap_observes_marked_weights(
    manifest: dict[str, object], instruments: tuple[str, ...]
) -> None:
    rule = _cap(manifest)
    window = _benchmark_window(manifest, instruments, rule.requirements()[0])

    heavy = instruments[0]
    marks = MarkBatch((Mark(heavy, Decimal("1"), Decimal("900"), Decimal("900")),), Decimal("900"))
    account = AccountSnapshot(5, Decimal("100"), {heavy: Decimal("1")})

    finding = rule.observe(
        reading_call(window, instruments, rule, account=_view(account, marks))
    )

    assert finding.measured == Decimal("0.9")
    assert not finding.passed
    assert finding.offenders == (heavy,)


def test_the_cap_gives_one_answer_about_a_short(
    manifest: dict[str, object], instruments: tuple[str, ...]
) -> None:
    """One rule, one book, one answer (issue 014): the ceiling bounds SIZE, and a short within
    it is not this rule's finding -- reporting the sign is `NoShort`'s job."""
    rule = _cap(manifest)
    window = _benchmark_window(manifest, instruments, rule.requirements()[0])
    ceilings = rule.ceilings(reading_call(window, instruments, rule))
    name = instruments[0]
    ceiling = ceilings[name]

    for size, inside in ((ceiling * 2, False), (ceiling / 2, True)):
        _, _, offenders = rule._worst({name: -size}, ceilings)
        assert (not offenders) is inside, f"the rule disagreed at {-size}"


def test_a_project_local_rule_still_loads_alongside_a_builtin(tmp_path: Path) -> None:
    """Shipping builtins must not close a canonically open extension point."""
    from vqapr.component.fingerprint import fingerprint_component
    from vqapr.component.loading import load_compliance
    from vqapr.component.reference import ComponentRef
    from vqapr.domain.wiring import Role

    source = tmp_path / "local_rule.py"
    source.write_text(
        """from __future__ import annotations

from decimal import Decimal

from vqapr.authoring import Compliance, ComplianceFinding


class LocalCap(Compliance):
    @property
    def compliance_id(self):
        return "local-cap"

    def observe(self, call):
        return ComplianceFinding(
            passed=True, measured=Decimal("0"), bound=Decimal("1"), excess=Decimal("0"), details={}
        )
""",
        encoding="utf-8",
    )
    ref = ComponentRef.of(
        "local-cap",
        Role.COMPLIANCE,
        source,
        "LocalCap",
        fingerprint=fingerprint_component(
            source, kind=Role.COMPLIANCE, object_name="LocalCap"
        ),
    )

    loaded = load_compliance(ref, project_root=tmp_path)

    assert isinstance(loaded, Compliance)
    assert loaded.compliance_id == "local-cap"
    assert not isinstance(loaded, tuple(SHIPPED_COMPLIANCE.values()))


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
    rule = _cap(manifest)
    requirement = rule.requirements()[0]

    assert str(requirement.dataset_id) == "benchmark_weight_daily"
    assert requirement.field_id == "benchmark_weight"
    assert requirement.lookback == RowsLookback(1)


def test_single_name_cap_enforces_its_declared_tolerance_on_the_real_benchmark(
    manifest: dict[str, object], instruments: tuple[str, ...], tmp_path: Path
) -> None:
    """The tolerance must bind where it is actually consulted: a benchmark inflated past the
    declared allowance, read through a real point-in-time window, fails `observe` itself."""
    rule = _cap(manifest)
    requirement = rule.requirements()[0]
    inflated = _window_over(
        manifest,
        instruments,
        requirement,
        _scaled_benchmark(manifest, tmp_path / "inflated_benchmark.parquet", "4"),
    )
    marks = MarkBatch((Mark(instruments[0], Decimal("1"), Decimal("9"), Decimal("9")),), Decimal("9"))
    account = AccountSnapshot(5, Decimal("1"), {instruments[0]: Decimal("1")})

    with pytest.raises(AllocationViolation, match="above the declared"):
        rule.observe(reading_call(inflated, instruments, rule, account=_view(account, marks)))

    # The unmodified panel, well under the ceiling, still observes cleanly.
    clean = _benchmark_window(manifest, instruments, requirement)
    assert rule.observe(
        reading_call(clean, instruments, rule, account=_view(account, marks))
    ).measured
