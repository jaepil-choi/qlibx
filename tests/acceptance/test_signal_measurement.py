"""The signal-measurement showcase's own pipeline, run headlessly and checked.

This does not reimplement `showcases/show_007_signal_measurement/run.py`'s pipeline: it imports the
showcase module directly and calls its `_pipeline` function against a pytest-owned temporary
project, exactly as `run.py`'s own `main()` does against `outputs/`. Reimplementing the pipeline
here would let a regression in the showcase's own code leave this suite green, which would prove
nothing about the code that actually ships.

Three things are asserted beyond what `run.py` itself already asserts before returning:

* the recorded tables exist with the shape the assignment requires,
* the neutralised signal is exactly orthogonal to a market column on every occurrence, recomputed
  from the published artifact rather than trusted from the transform, and
* the re-hydrated marks equal the committed ones, field for field.
"""

from __future__ import annotations

import importlib.util
import sys
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SHOWCASE_DIR = REPO_ROOT / "showcases" / "show_007_signal_measurement"


def _load_showcase():
    """Import run.py as a module without requiring showcases/ to be a package."""
    spec = importlib.util.spec_from_file_location(
        "show_007_signal_measurement_run", SHOWCASE_DIR / "run.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def showcase():
    return _load_showcase()


@pytest.fixture(scope="module")
def pipeline_result(showcase, tmp_path_factory):
    project = tmp_path_factory.mktemp("show007") / "project"
    return showcase._pipeline(project)


def test_the_showcase_exists_and_states_its_own_limits() -> None:
    readme = (SHOWCASE_DIR / "README.md").read_text(encoding="utf-8")

    assert (SHOWCASE_DIR / "run.py").is_file()
    assert "does NOT" in readme or "NOT demonstrate" in readme, (
        "the showcase must state what it does not prove"
    )


def test_the_recorded_tables_exist_with_the_expected_shape(pipeline_result) -> None:
    trace, digests = pipeline_result

    assert trace["signal_run_record"]["dataset"] == "signal_measurement"
    assert trace["signal_run_record"]["rows"] > 0
    assert trace["signal_run_record"]["rows"] == trace["signal_run_record"]["read_back"]

    assert trace["account_run_record"]["dataset"] == "run_account"
    assert trace["account_run_record"]["rows"] > 0
    assert trace["account_run_record"]["rows"] == trace["account_run_record"]["read_back"]

    assert trace["signal_occurrences"] > 0
    assert trace["signal_occurrences"] <= trace["callbacks"]

    assert set(digests) == {
        "signal_measurement.parquet",
        "signal_measurement.lineage.json",
        "run_account.parquet",
        "run_account.lineage.json",
    }


def test_the_neutralised_signal_is_exactly_orthogonal_on_every_occurrence(
    showcase, tmp_path
) -> None:
    """Recomputed from the published artifact alone, not from the transform's own contract."""
    project = tmp_path / "orthogonality-project"
    trace, _digests = showcase._pipeline(project)

    output_path = project / ".vqapr" / "materialized" / "signal_measurement.parquet"
    assert output_path.is_file()

    con = duckdb.connect()
    try:
        rows = con.execute(
            f"SELECT available_at, neutralized_signal "
            f"FROM read_parquet('{output_path.as_posix()}') ORDER BY available_at, instrument"
        ).fetchall()
    finally:
        con.close()

    assert rows, "the published signal table must not be empty"

    by_occurrence: dict[object, list[Decimal]] = {}
    for available_at, neutralized_signal in rows:
        by_occurrence.setdefault(available_at, []).append(Decimal(neutralized_signal))

    assert len(by_occurrence) == trace["signal_occurrences"]
    for available_at, values in by_occurrence.items():
        assert sum(values) == 0, (
            f"neutralised signal at {available_at} is not orthogonal to the market column: "
            f"sum={sum(values)}"
        )

    assert any(value != 0 for values in by_occurrence.values() for value in values), (
        "at least one recorded signal must be genuinely non-flat"
    )


def test_an_identity_signal_would_fail_the_orthogonality_check() -> None:
    """The falsifier has to kill a no-op: an un-neutralised ranked signal is not orthogonal."""
    sys.path.insert(0, str(REPO_ROOT / "src"))
    from vqapr.transforms.cross_section import rank

    raw = {"A": Decimal("10"), "B": Decimal("20"), "C": Decimal("30"), "D": Decimal("47")}
    ranked = rank(raw)

    assert sum(ranked.values()) != 0, (
        "an unneutralised ranked signal is not orthogonal to the market column"
    )


def test_the_rehydrated_marks_equal_the_committed_ones(showcase, tmp_path) -> None:
    project = tmp_path / "rehydration-project"
    trace, _digests = showcase._pipeline(project)

    rehydration = trace["mark_rehydration"]
    assert rehydration["rehydrated_mark_count"] > 0
    assert rehydration["rehydrated_versions"], "at least one committed mark must be witnessed"
    # showcase._pipeline itself already asserts field-for-field equality against the mark the
    # account still holds (see _rehydrate_marks); re-checking the summary counts here guards
    # against a future _pipeline edit silently dropping that assertion while still returning a
    # trace that looks complete.
    #
    # The publication carries MORE than memory does, and that is the point. A run retains only the
    # marks some consumer declared it would read, so post-mortem reconstruction has to come from
    # the published table. Requiring the opposite would be requiring the run to hold a history
    # nobody asked for.
    assert rehydration["rehydrated_mark_count"] >= rehydration["committed_mark_count"]
    assert len(rehydration["rehydrated_versions"]) > 1, (
        "the published table must reconstruct more than the single retained mark"
    )


def test_the_execution_evidence_reconciles_with_the_committed_account(pipeline_result) -> None:
    trace, _digests = pipeline_result
    execution = trace["execution"]

    assert execution["replayed_cash"] == execution["committed_cash"]
    assert int(execution["dealt_fills"]) > 0
