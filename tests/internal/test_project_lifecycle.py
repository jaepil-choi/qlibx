"""The supported lifecycle end to end: open, register, materialize, run, publish.

This is the test that proves the invocation boundary is reachable from the public surface
rather than only from its own unit tests. It also pins the property the factor testbed
migration depends on: monthly cadence surviving across fresh model instances through
returned state alone.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

import vqapr
from vqapr.authoring import (
    ConstraintBounds,
    DataModel,
    DatasetInput,
    DerivedRow,
    DiagnosticTable,
    EconomicAccountView,
    Hold,
    Observation,
    Output,
    RowsLookback,
    StrategyModel,
    StrategyResult,
)
from vqapr.project import DatasetDeclaration

PRICES = DatasetInput(dataset_id="stock_daily", fields=("ret",), lookback=RowsLookback(rows=1))
INSTRUMENT = "005930"


def _resolver(alias, declaration, evaluation_time):
    return (
        Observation(
            instrument_id=INSTRUMENT,
            available_at=evaluation_time,
            values={"ret": Decimal("0.01")},
        ),
    )


def _account():
    return EconomicAccountView(
        cash=Decimal(1000), positions={}, nav=None, nav_observed_at=None
    )


def _bounds():
    return ConstraintBounds(
        lower_weights={INSTRUMENT: Decimal(0)}, upper_weights={INSTRUMENT: Decimal(1)}
    )


def _dataset():
    return DatasetDeclaration(
        dataset_id="stock_daily",
        path=Path("prepared/stock_daily.parquet"),
        hive_partitioned=False,
        instrument_field="instrument",
        available_at_field="available_at",
        key_fields=("available_at", "instrument"),
        fields={"ret": "ret"},
    )


class _Signal(DataModel):
    def inputs(self):
        return {"prices": PRICES}

    def output(self):
        return Output(semantic_fields=("signal",))

    def compute(self, call):
        observations = call.read("prices")
        return tuple(
            DerivedRow(instrument_id=o.instrument_id, values={"signal": o.values["ret"]})
            for o in observations
        )


class _MonthlyCadence(StrategyModel):
    """The exact shape `models/factors.py` must migrate to: cadence in returned state."""

    def diagnostics(self):
        return (DiagnosticTable(table_id="formation", semantic_fields=("month",)),)

    def decide(self, call):
        previous = call.previous_state if isinstance(call.previous_state, dict) else {}
        month = call.evaluation_time.year * 12 + (call.evaluation_time.month - 1)
        if previous.get("last_formed_month") == month:
            return StrategyResult(
                decision=Hold(reason="already-formed"), next_state=previous, diagnostics={}
            )
        return StrategyResult(
            decision=Hold(reason="formed"),
            next_state={**previous, "last_formed_month": month},
            diagnostics={"formation": ({"month": month},)},
        )


def test_the_supported_lifecycle_runs_end_to_end(tmp_path: Path):
    root = tmp_path / "project"
    root.mkdir()

    project = vqapr.open(root)
    assert not (root / ".vqapr").exists()

    receipt = project.register(_dataset())
    assert receipt.created is True

    materialized = project.materialize(
        model=_Signal,
        config={},
        evaluation_times=(
            datetime(2024, 3, 1, 16, tzinfo=UTC),
            datetime(2024, 3, 2, 16, tzinfo=UTC),
        ),
        resolver=_resolver,
    )
    assert materialized.evaluations == 2
    assert len(materialized.rows) == 2
    assert len(materialized.access_tokens) == 2

    completed = project.run(
        strategy=_MonthlyCadence,
        config={},
        occurrences=(
            datetime(2024, 3, 1, 16, tzinfo=UTC),
            datetime(2024, 3, 15, 16, tzinfo=UTC),
            datetime(2024, 4, 1, 16, tzinfo=UTC),
        ),
        account=_account(),
        instruments=(INSTRUMENT,),
        constraint_bounds=_bounds(),
        resolver=_resolver,
        initial_strategy_state=None,
    )

    published = completed.publish({"allocation": b"alloc", "records": b"records"})
    assert set(published.output_ids) == {"allocation", "records"}
    assert "allocation" in vqapr.open(root).catalog()._catalog.publications


def test_monthly_cadence_survives_only_through_returned_state(tmp_path: Path):
    """Two occurrences in one month form once; a new month forms again.

    Every occurrence gets a brand new model instance, so this sequence is only possible
    if `previous_state`/`next_state` is genuinely threading the cadence.
    """
    project = vqapr.open(tmp_path)
    completed = project.run(
        strategy=_MonthlyCadence,
        config={},
        occurrences=(
            datetime(2024, 3, 1, 16, tzinfo=UTC),
            datetime(2024, 3, 15, 16, tzinfo=UTC),
            datetime(2024, 4, 1, 16, tzinfo=UTC),
        ),
        account=_account(),
        instruments=(INSTRUMENT,),
        constraint_bounds=_bounds(),
        resolver=_resolver,
        initial_strategy_state=None,
    )

    assert [d.reason for d in completed.decisions] == ["formed", "already-formed", "formed"]
    assert completed.final_state == {"last_formed_month": 2024 * 12 + 3}


def test_a_run_is_replayable_from_the_same_initial_state(tmp_path: Path):
    """The same occurrences and the same initial state produce the same decisions."""
    project = vqapr.open(tmp_path)
    occurrences = (
        datetime(2024, 3, 1, 16, tzinfo=UTC),
        datetime(2024, 3, 15, 16, tzinfo=UTC),
        datetime(2024, 4, 1, 16, tzinfo=UTC),
    )
    kwargs = dict(
        strategy=_MonthlyCadence,
        config={},
        occurrences=occurrences,
        account=_account(),
        instruments=(INSTRUMENT,),
        constraint_bounds=_bounds(),
        resolver=_resolver,
        initial_strategy_state=None,
    )
    first = project.run(**kwargs)
    second = project.run(**kwargs)

    assert [d.reason for d in first.decisions] == [d.reason for d in second.decisions]
    assert first.final_state == second.final_state


def test_resuming_mid_month_does_not_re_form(tmp_path: Path):
    """The exact case the factor model's docstring calls out.

    Deriving cadence from the occurrence date alone would re-form on the first session of
    a month even when the run resumed mid-month. Threading state makes the resumed run
    hold instead.
    """
    project = vqapr.open(tmp_path)
    completed = project.run(
        strategy=_MonthlyCadence,
        config={},
        occurrences=(datetime(2024, 3, 20, 16, tzinfo=UTC),),
        account=_account(),
        instruments=(INSTRUMENT,),
        constraint_bounds=_bounds(),
        resolver=_resolver,
        initial_strategy_state={"last_formed_month": 2024 * 12 + 2},
    )
    assert [d.reason for d in completed.decisions] == ["already-formed"]


def test_materialize_refuses_an_empty_evaluation_set(tmp_path: Path):
    project = vqapr.open(tmp_path)
    with pytest.raises(ValueError, match="non-empty"):
        project.materialize(model=_Signal, config={}, evaluation_times=(), resolver=_resolver)


def test_publish_refuses_an_empty_output_set(tmp_path: Path):
    project = vqapr.open(tmp_path)
    completed = project.run(
        strategy=_MonthlyCadence,
        config={},
        occurrences=(datetime(2024, 3, 1, 16, tzinfo=UTC),),
        account=_account(),
        instruments=(INSTRUMENT,),
        constraint_bounds=_bounds(),
        resolver=_resolver,
    )
    with pytest.raises(ValueError, match="non-empty"):
        completed.publish({})


# --- materialization output persistence ---------------------------------------------------


def test_materialize_persists_nothing_unless_asked(tmp_path: Path):
    """Persistence is an explicit request, never an implicit side effect."""
    project = vqapr.open(tmp_path)
    result = project.materialize(
        model=_Signal,
        config={},
        evaluation_times=(datetime(2024, 3, 1, 16, tzinfo=UTC),),
        resolver=_resolver,
    )
    assert result.output_dataset_id is None
    assert result.digest is None
    assert project.generation() == 0


def test_materialize_persists_and_binds_when_asked(tmp_path: Path):
    from vqapr._internal.objects import has_object

    project = vqapr.open(tmp_path)
    result = project.materialize(
        model=_Signal,
        config={},
        evaluation_times=(
            datetime(2024, 3, 1, 16, tzinfo=UTC),
            datetime(2024, 3, 2, 16, tzinfo=UTC),
        ),
        resolver=_resolver,
        output_dataset_id="signal_daily",
    )

    assert result.output_dataset_id == "signal_daily"
    assert has_object(tmp_path, result.digest)
    binding = project.catalog().dataset("signal_daily")
    assert binding["digest"] == result.digest
    assert binding["derived"] is True


def test_a_persisted_row_carries_the_framework_stamped_evaluation_time(tmp_path: Path):
    """A derived row is only meaningful alongside the cutoff it was computed at."""
    import json

    from vqapr._internal.objects import read_object

    project = vqapr.open(tmp_path)
    result = project.materialize(
        model=_Signal,
        config={},
        evaluation_times=(datetime(2024, 3, 1, 16, tzinfo=UTC),),
        resolver=_resolver,
        output_dataset_id="signal_daily",
    )
    payload = json.loads(read_object(tmp_path, result.digest))
    assert payload["rows"][0]["evaluation_time"] == "2024-03-01T16:00:00+00:00"
    assert payload["rows"][0]["instrument_id"] == INSTRUMENT


def test_a_result_cannot_claim_a_dataset_without_a_digest():
    from vqapr.project import MaterializationResult

    with pytest.raises(ValueError, match="both be set or both be None"):
        MaterializationResult(
            rows=(), access_tokens=(), evaluations=1, output_dataset_id="x", digest=None
        )


def test_an_invalid_output_dataset_id_is_refused(tmp_path: Path):
    project = vqapr.open(tmp_path)
    with pytest.raises(ValueError, match="output_dataset_id"):
        project.materialize(
            model=_Signal,
            config={},
            evaluation_times=(datetime(2024, 3, 1, 16, tzinfo=UTC),),
            resolver=_resolver,
            output_dataset_id="has whitespace",
        )


def test_a_persisted_materialization_reads_back_through_the_supported_surface(tmp_path: Path):
    """A digest that names bytes nobody can reach is not a usable output."""
    project = vqapr.open(tmp_path)
    project.materialize(
        model=_Signal,
        config={},
        evaluation_times=(
            datetime(2024, 3, 1, 16, tzinfo=UTC),
            datetime(2024, 3, 2, 16, tzinfo=UTC),
        ),
        resolver=_resolver,
        output_dataset_id="signal_daily",
    )
    rows = project.read_output("signal_daily")
    assert len(rows) == 2
    assert rows[0]["instrument_id"] == INSTRUMENT
    assert rows[0]["evaluation_time"] == "2024-03-01T16:00:00+00:00"


def test_reading_a_physical_source_as_an_output_raises(tmp_path: Path):
    """A registered source carries no digest; returning () would hide the mistake."""
    project = vqapr.open(tmp_path)
    project.register(_dataset())
    with pytest.raises(KeyError, match="carries no content digest"):
        project.read_output("stock_daily")


def test_reading_an_unregistered_output_raises(tmp_path: Path):
    project = vqapr.open(tmp_path)
    with pytest.raises(KeyError):
        project.read_output("never_registered")


def test_lineage_records_what_the_run_actually_read(tmp_path: Path):
    """Lineage is framework-derived from real access, not author-supplied."""
    project = vqapr.open(tmp_path)
    project.materialize(
        model=_Signal,
        config={},
        evaluation_times=(
            datetime(2024, 3, 1, 16, tzinfo=UTC),
            datetime(2024, 3, 2, 16, tzinfo=UTC),
        ),
        resolver=_resolver,
        output_dataset_id="signal_daily",
    )
    lineage = project.read_lineage("signal_daily")

    assert lineage["evaluations"] == 2
    assert lineage["model"] == "_Signal"
    # One read per evaluation, each naming the alias and dataset actually touched.
    assert len(lineage["reads"]) == 2
    assert lineage["reads"][0]["alias"] == "prices"
    assert lineage["reads"][0]["dataset_id"] == "stock_daily"
    assert lineage["reads"][0]["observation_count"] == 1


def test_rows_and_lineage_share_one_object(tmp_path: Path):
    """They cannot disagree, because they are never written separately."""
    project = vqapr.open(tmp_path)
    result = project.materialize(
        model=_Signal,
        config={},
        evaluation_times=(datetime(2024, 3, 1, 16, tzinfo=UTC),),
        resolver=_resolver,
        output_dataset_id="signal_daily",
    )
    rows = project.read_output("signal_daily")
    lineage = project.read_lineage("signal_daily")
    assert len(rows) == 1
    assert lineage["evaluations"] == 1
    # One digest names both.
    assert project.catalog().dataset("signal_daily")["digest"] == result.digest


def test_reading_lineage_of_a_physical_source_raises(tmp_path: Path):
    project = vqapr.open(tmp_path)
    project.register(_dataset())
    with pytest.raises(KeyError, match="carries no content digest"):
        project.read_lineage("stock_daily")
