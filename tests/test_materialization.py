from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from qlibx import (
    ForwardReturnLabelEntry,
    ForwardReturnLabelModel,
    ForwardReturnLabelResult,
    MaterializationInvocation,
    OutcomeStatus,
    QlibxModel,
    QlibxProject,
)
from qlibx.data import AvailableAtField, DatasetRegistration, RowsLookback, SourceFormat
from qlibx.operations import FORWARD_RETURN_LABEL_OUTPUT


def _write_source(path: Path, *, horizon_instruments: tuple[str, ...] = ("A", "B")) -> None:
    rows = [
        "observation_time,available_at,instrument,start_value,end_value,horizon_end",
        "2024-01-02T06:30:00Z,2024-01-03T06:30:00Z,A,100,110,2024-01-03T06:30:00Z",
        "2024-01-02T06:30:00Z,2024-01-03T06:30:00Z,B,200,180,2024-01-03T06:30:00Z",
        "2024-01-03T06:30:00Z,2024-01-04T06:30:00Z,A,110,121,2024-01-04T06:30:00Z",
        "2024-01-03T06:30:00Z,2024-01-04T06:30:00Z,B,180,198,2024-01-04T06:30:00Z",
    ]
    if horizon_instruments != ("A", "B"):
        rows = [rows[0], *(row for row in rows[1:] if row.split(",")[2] in horizon_instruments)]
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def _registration(
    source: Path,
    *,
    dataset_id: str,
    semantic_bindings: dict[str, str],
) -> DatasetRegistration:
    return DatasetRegistration(
        dataset_id=dataset_id,
        source=source.name,
        source_format=SourceFormat.CSV,
        instrument_field="instrument",
        observation_time_field="observation_time",
        available_at=AvailableAtField(field="available_at"),
        logical_key=("observation_time", "available_at", "instrument"),
        semantic_bindings=semantic_bindings,
        semantic_category="forward_label_source",
        source_provenance="deterministic forward-label contract fixture",
    )


def _project(tmp_path: Path) -> tuple[QlibxProject, Path]:
    QlibxProject.init(tmp_path, apply=True)
    source = tmp_path / "forward-label.csv"
    _write_source(source)
    project = QlibxProject.open(tmp_path)
    registered = project.register_dataset(
        _registration(
            source,
            dataset_id="label-prices",
            semantic_bindings={
                "label_start_value": "start_value",
                "label_end_value": "end_value",
            },
        )
    )
    assert registered.status is OutcomeStatus.COMPLETE
    return project, source


def _register_horizon(project: QlibxProject, source: Path) -> None:
    registered = project.register_dataset(
        _registration(
            source,
            dataset_id="label-horizon",
            semantic_bindings={"horizon_end": "horizon_end"},
        )
    )
    assert registered.status is OutcomeStatus.COMPLETE


def _invocation(
    identity: str,
    day: int,
    *,
    hour: int = 6,
    minute: int = 30,
    resolves_error_artifact_id: str | None = None,
) -> MaterializationInvocation:
    return MaterializationInvocation(
        invocation_id=identity,
        evaluation_time=datetime(2024, 1, day, hour, minute, tzinfo=UTC),
        config_fingerprint="forward-label-config-v1",
        resolves_error_artifact_id=resolves_error_artifact_id,
    )


class CountingForwardLabelModel:
    producer_id = "tests.counting-forward-label"
    output_contract = FORWARD_RETURN_LABEL_OUTPUT

    def __init__(self) -> None:
        self._delegate = ForwardReturnLabelModel(
            "label-prices",
            "label-horizon",
            RowsLookback(rows=100),
        )
        self.calls = 0

    def requirements(self) -> tuple[object, ...]:
        return self._delegate.requirements()

    def run(self, view: object) -> ForwardReturnLabelResult:
        self.calls += 1
        return self._delegate.run(view)  # type: ignore[arg-type]


def test_missing_horizon_fails_before_model_then_linked_retry_respects_pit(
    tmp_path: Path,
) -> None:
    project, source = _project(tmp_path)
    model = CountingForwardLabelModel()

    missing = project.materialize(model, _invocation("missing-horizon", 3))

    assert missing.status is OutcomeStatus.FAILED
    assert missing.errors[0].error_code == "REQUIREMENT_NOT_RESOLVED"
    assert missing.errors[0].requirement_id == "label.horizon_end"
    assert missing.errors[0].commit_status.value == "NONE"
    assert model.calls == 0
    assert project.artifacts.list_envelopes() == ()
    failure = missing.diagnostics[0]

    _register_horizon(project, source)
    retry = project.materialize(
        model,
        _invocation(
            "valid-horizon-retry",
            3,
            resolves_error_artifact_id=failure.artifact_id,
        ),
    )

    assert retry.status is OutcomeStatus.COMPLETE
    assert model.calls == 1
    result = retry.result.result
    assert [(item.instrument, item.value) for item in result.entries] == [
        ("A", pytest.approx(0.1)),
        ("B", pytest.approx(-0.1)),
    ]
    assert {item.observation_time.day for item in result.entries} == {2}
    assert all(item.available_at <= result.evaluation_time for item in result.entries)
    dependencies = retry.result.artifact.dependencies
    assert {edge.consumer_role for edge in dependencies} == {
        "horizon_end",
        "label_end_value",
        "label_start_value",
        "materialization_config",
        "resolves_error",
    }
    assert any(
        edge.dependency_kind == "error" and edge.dependency_id == failure.artifact_id
        for edge in dependencies
    )
    assert len(project.artifacts.list_envelopes(include_failure=True)) == 2

    later = project.materialize(model, _invocation("later-horizon", 4))
    assert later.status is OutcomeStatus.COMPLETE
    assert len(later.result.result.entries) == 4


def test_no_visible_forward_label_is_a_typed_failure(tmp_path: Path) -> None:
    project, source = _project(tmp_path)
    _register_horizon(project, source)
    model = CountingForwardLabelModel()

    outcome = project.materialize(
        model,
        _invocation("before-first-horizon", 3, minute=29),
    )

    assert outcome.status is OutcomeStatus.FAILED
    assert outcome.errors[0].error_code == "FORWARD_LABEL_INPUT_EMPTY"
    assert outcome.errors[0].stage_path == "materialization.run.compute"
    assert model.calls == 1
    assert project.artifacts.list_envelopes() == ()


def test_source_drift_is_a_materialization_data_failure(tmp_path: Path) -> None:
    project, source = _project(tmp_path)
    _register_horizon(project, source)
    source.write_text(source.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    outcome = project.materialize(
        ForwardReturnLabelModel(
            "label-prices",
            "label-horizon",
            RowsLookback(rows=100),
        ),
        _invocation("source-drift", 3),
    )

    assert outcome.status is OutcomeStatus.FAILED
    assert outcome.errors[0].error_code == "MATERIALIZATION_DATA_READ_FAILED"
    assert outcome.errors[0].stage_path == "materialization.run.data"
    assert project.artifacts.list_envelopes() == ()


class WrongPayload(QlibxModel):
    value: str


class WrongResultOperation:
    producer_id = "tests.wrong-result"
    output_contract = FORWARD_RETURN_LABEL_OUTPUT

    def requirements(self) -> tuple[object, ...]:
        return ()

    def run(self, _view: object) -> WrongPayload:
        return WrongPayload(value="wrong")


def test_wrong_materialization_payload_is_not_reusable(tmp_path: Path) -> None:
    QlibxProject.init(tmp_path, apply=True)
    project = QlibxProject.open(tmp_path)

    outcome = project.materialize(WrongResultOperation(), _invocation("wrong-result", 3))

    assert outcome.status is OutcomeStatus.FAILED
    assert outcome.errors[0].error_code == "MATERIALIZATION_RESULT_INVALID"
    assert project.artifacts.list_envelopes() == ()


def test_forward_label_payload_rejects_invalid_time_and_calculation() -> None:
    with pytest.raises(ValidationError, match="horizon_end"):
        ForwardReturnLabelEntry(
            instrument="A",
            observation_time=datetime(2024, 1, 3, tzinfo=UTC),
            horizon_end=datetime(2024, 1, 2, tzinfo=UTC),
            available_at=datetime(2024, 1, 3, tzinfo=UTC),
            start_value=100,
            end_value=110,
            value=0.1,
        )

    with pytest.raises(ValidationError, match="does not match"):
        ForwardReturnLabelEntry(
            instrument="A",
            observation_time=datetime(2024, 1, 2, tzinfo=UTC),
            horizon_end=datetime(2024, 1, 3, tzinfo=UTC),
            available_at=datetime(2024, 1, 3, tzinfo=UTC),
            start_value=100,
            end_value=110,
            value=0.2,
        )
