from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
import pytest

from vqapr.data.datasets import DatasetRegistration
from vqapr.data.lookback import RowsLookback
from vqapr.data.requirements import DataRequirement
from vqapr.data.sources import SourceSpec
from vqapr.data.store import DuckDbObservationStore
from vqapr.data.windows import ModelWindow
from vqapr.domain.errors import VqaprError
from vqapr.flow.materialize import MaterializationSpec
from vqapr.public import materialize, register_data_model, register_dataset
from vqapr.workspace import Workspace

KST = ZoneInfo("Asia/Seoul")


def _register_prices(project: Path, parquet: Path) -> None:
    register_dataset(
        project,
        DatasetRegistration.of(
            "price_daily",
            "prices",
            instrument_field="instrument",
            available_at="available_at",
            key_fields=("available_at", "instrument"),
            fields={"close": "close", "volume": "volume"},
        ),
        SourceSpec.of("prices", parquet),
    )


def _component_source(path: Path) -> Path:
    path.write_text(
        """from vqapr.public import DataModel, DataRequirement, RowsLookback

class ReversalModel(DataModel):
    def requirements(self):
        return (DataRequirement.of(
            "reversal", "price_daily", fields=("close",), lookback=RowsLookback(2)
        ),)

    def compute(self, context):
        assert not hasattr(context, "account")
        assert not hasattr(context, "execution_input")
        rows = context.window.observations(self.requirements()[0]).rows
        by_instrument = {}
        for row in rows:
            if row["close"] is not None:
                by_instrument.setdefault(row["instrument"], []).append(float(row["close"]))
        return tuple(
            {"instrument": instrument, "score": -(values[-1] / values[0] - 1.0)}
            for instrument, values in sorted(by_instrument.items())
            if len(values) == 2
        )

class ForgingModel(ReversalModel):
    def compute(self, context):
        rows = super().compute(context)
        return tuple({**row, "available_at": context.window.evaluation_time} for row in rows)

class FailingSecondModel(ReversalModel):
    def compute(self, context):
        if context.window.evaluation_time.day == 7:
            raise RuntimeError("intentional second-evaluation failure")
        return super().compute(context)
""",
        encoding="utf-8",
    )
    return path


def _times() -> tuple[datetime, ...]:
    return (
        datetime(2024, 3, 6, 16, tzinfo=KST),
        datetime(2024, 3, 7, 16, tzinfo=KST),
    )


def test_materialize_publishes_a_registered_dataset_that_uses_the_same_read_path(
    tmp_path: Path, model_price_parquet: Path
) -> None:
    _register_prices(tmp_path, model_price_parquet)
    component_path = _component_source(tmp_path / "models.py")
    register_data_model(tmp_path, "reversal", component_path, "ReversalModel")

    result = materialize(
        tmp_path,
        "reversal",
        MaterializationSpec.of("reversal_2d", value_fields=("score",)),
        evaluation_times=_times(),
        instruments=("A", "B"),
    )

    assert result.output_path.is_file()
    assert result.lineage_path.is_file()
    assert Workspace.open(tmp_path).dataset("reversal_2d") == result.registration
    con = duckdb.connect()
    try:
        rows = con.execute(
            f"SELECT available_at, instrument, score FROM '{result.output_path.as_posix()}' "
            "ORDER BY available_at, instrument"
        ).fetchall()
    finally:
        con.close()
    assert len(rows) == 4
    assert rows[0][0] == _times()[0]
    assert rows[0][1] == "A"
    assert rows[0][2] == pytest.approx(-0.03)

    requirement = DataRequirement.of(
        "consumer", "reversal_2d", fields=("score",), lookback=RowsLookback(1)
    )
    window = ModelWindow(
        evaluation_time=_times()[1],
        instruments=("A", "B"),
        store=DuckDbObservationStore(Workspace.open(tmp_path)),
        allowed_requirements=(requirement,),
    )
    reread = window.observations(requirement)
    assert [row["instrument"] for row in reread.rows] == ["A", "B"]
    assert reread.access.actual_rows == {"A": {"score": 1}, "B": {"score": 1}}


def test_producer_cannot_forge_available_at_and_failure_does_not_mutate_workspace(
    tmp_path: Path, model_price_parquet: Path
) -> None:
    _register_prices(tmp_path, model_price_parquet)
    component_path = _component_source(tmp_path / "models.py")
    register_data_model(tmp_path, "forger", component_path, "ForgingModel")
    before = Workspace.open(tmp_path).path.read_bytes()

    with pytest.raises(VqaprError) as caught:
        materialize(
            tmp_path,
            "forger",
            MaterializationSpec.of("forged", value_fields=("score",)),
            evaluation_times=_times(),
            instruments=("A", "B"),
        )

    assert caught.value.stage == "materialize.output"
    assert caught.value.mutation is False
    assert Workspace.open(tmp_path).path.read_bytes() == before
    assert not (tmp_path / ".vqapr" / "materialized" / "forged.parquet").exists()


def test_mid_run_compute_failure_publishes_nothing(
    tmp_path: Path, model_price_parquet: Path
) -> None:
    _register_prices(tmp_path, model_price_parquet)
    component_path = _component_source(tmp_path / "models.py")
    register_data_model(tmp_path, "failing", component_path, "FailingSecondModel")
    before = Workspace.open(tmp_path).path.read_bytes()

    with pytest.raises(VqaprError) as caught:
        materialize(
            tmp_path,
            "failing",
            MaterializationSpec.of("partial", value_fields=("score",)),
            evaluation_times=_times(),
            instruments=("A", "B"),
        )

    assert caught.value.stage == "materialize.compute"
    assert caught.value.mutation is False
    assert "intentional second-evaluation failure" in caught.value.failures[0].observed
    assert Workspace.open(tmp_path).path.read_bytes() == before
    assert not (tmp_path / ".vqapr" / "materialized" / "partial.parquet").exists()


def test_an_edited_component_computes_instead_of_being_refused(
    tmp_path: Path, model_price_parquet: Path
) -> None:
    """Editing a registered component and re-running is the ordinary development loop.

    This previously pinned the opposite: an edit was refused at load with
    `component.load.fingerprint_drift`, whose stated repair was "re-register the component" --
    which `register_component` then refused, demanding a new identity. The two pointed at each
    other (`docs/implementations/057`), so the gate was removed (issue 009) and the fingerprint
    became a receipt: still computed, and the run record states what actually loaded.

    What must still hold is that materialize does not mutate the workspace.
    """
    _register_prices(tmp_path, model_price_parquet)
    component_path = _component_source(tmp_path / "models.py")
    register_data_model(tmp_path, "reversal", component_path, "ReversalModel")
    before = Workspace.open(tmp_path).path.read_bytes()
    component_path.write_text(
        component_path.read_text(encoding="utf-8") + "\n# drift\n",
        encoding="utf-8",
    )

    materialize(
        tmp_path,
        "reversal",
        MaterializationSpec.of("drifted", value_fields=("score",)),
        evaluation_times=_times(),
        instruments=("A", "B"),
    )

    # One component id, before and after. The edit neither refuses nor mints a second identity,
    # which is the whole difference this milestone makes.
    after = Workspace.open(tmp_path)
    assert len(after.components) == 1, "an edit must not mint a second component id"
    assert [str(ref.component_id) for ref in after.components] == ["reversal"]

@pytest.mark.parametrize(
    "evaluation_times",
    [
        (),
        (_times()[1], _times()[0]),
        (_times()[0], _times()[0]),
        (datetime(2024, 3, 6, 16),),
    ],
)
def test_materialize_rejects_invalid_evaluation_times_before_output(
    tmp_path: Path,
    model_price_parquet: Path,
    evaluation_times: tuple[datetime, ...],
) -> None:
    _register_prices(tmp_path, model_price_parquet)
    component_path = _component_source(tmp_path / "models.py")
    register_data_model(tmp_path, "reversal", component_path, "ReversalModel")
    before = Workspace.open(tmp_path).path.read_bytes()

    with pytest.raises(VqaprError) as caught:
        materialize(
            tmp_path,
            "reversal",
            MaterializationSpec.of("invalid-times", value_fields=("score",)),
            evaluation_times=evaluation_times,
            instruments=("A", "B"),
        )

    assert caught.value.stage == "materialize.input"
    assert caught.value.mutation is False
    assert Workspace.open(tmp_path).path.read_bytes() == before


def test_materialize_lineage_payload_keys_are_pinned(
    tmp_path: Path, model_price_parquet: Path
) -> None:
    """The mirror of the allocation payload assertion.

    `_stage_and_publish` and the lineage envelope split were extracted so two callers could share
    one publication authority. Nothing pinned the DataModel side of that payload afterwards, so a
    key added, dropped or renamed during a later refactor would pass unnoticed. This is the guard.
    """
    _register_prices(tmp_path, model_price_parquet)
    component_path = _component_source(tmp_path / "models.py")
    register_data_model(tmp_path, "reversal", component_path, "ReversalModel")

    result = materialize(
        tmp_path,
        "reversal",
        MaterializationSpec.of("reversal_2d", value_fields=("score",)),
        evaluation_times=_times(),
        instruments=("A", "B"),
    )

    payload = json.loads(result.lineage_path.read_text(encoding="utf-8"))

    assert set(payload) == {
        "schema_version",
        "operation",
        "component",
        "output",
        "instruments",
        "invocations",
    }
    assert payload["operation"] == "datamodel.materialize"
    assert set(payload["component"]) == {"component_id", "fingerprint"}
    assert set(payload["output"]) == {"dataset_id", "source_id", "value_fields"}
    assert set(payload["invocations"][0]) == {
        "evaluation_time",
        "output_available_at",
        "row_count",
        "accesses",
    }
    assert "run" not in payload, "the DataModel operation must not carry run provenance"
