from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from qlibx import OutcomeStatus, QlibxProject
from qlibx.data import (
    AvailableAtField,
    ComponentRequirement,
    ConfirmedDelayRule,
    DatasetRegistration,
    ObservationStore,
    RequirementResolver,
    SourceFormat,
)


def registration(dataset_id: str, source: str, **bindings: str) -> DatasetRegistration:
    return DatasetRegistration(
        dataset_id=dataset_id,
        source=source,
        source_format=SourceFormat.CSV,
        instrument_field="CODE",
        source_timezone="UTC",
        available_at=AvailableAtField(field="DATE"),
        logical_key=("DATE", "CODE"),
        semantic_bindings={"value": "VALUE", **bindings},
        source_provenance="test fixture",
    )


def initialized_project(tmp_path: Path) -> QlibxProject:
    QlibxProject.init(tmp_path, apply=True)
    return QlibxProject.open(tmp_path)


def test_uc_data_001_minimal_registration_accepts_user_field_names(tmp_path: Path) -> None:
    source = tmp_path / "market.csv"
    source.write_text(
        "DATE,CODE,VALUE\n2025-01-02,005930,10.0\n2025-01-02,069500,20.0\n",
        encoding="utf-8",
    )
    project = initialized_project(tmp_path)

    outcome = project.register_dataset(registration("market", "market.csv"))

    assert outcome.status is OutcomeStatus.COMPLETE
    registered = project.registry_snapshot().get("market")
    assert registered is not None
    assert registered.instrument_field == "CODE"
    assert registered.evidence.row_count == 2
    assert "currency" not in registered.bindings
    assert "universe" not in registered.bindings


def test_uc_data_002_requirement_gap_is_progressive_and_retryable(tmp_path: Path) -> None:
    source = tmp_path / "market.csv"
    source.write_text(
        "DATE,CODE,VALUE,SECTOR\n2025-01-02,005930,10.0,IT\n",
        encoding="utf-8",
    )
    project = initialized_project(tmp_path)
    first = project.register_dataset(registration("market", "market.csv"))
    assert first.status is OutcomeStatus.COMPLETE
    resolver = RequirementResolver()
    sector = ComponentRequirement(
        requirement_id="strategy.sector",
        semantic_role="sector",
    )

    failed = resolver.resolve(
        operation="strategy.run",
        idempotency_identity="strategy-1",
        requirements=(sector,),
        registry=project.registry_snapshot(),
    )

    assert failed.failed
    assert failed.errors[0].stage_path == "strategy.run.requirements.sector"
    assert failed.errors[0].commit_status.value == "NONE"
    assert len(project.registry_snapshot().datasets) == 1

    enriched = registration("market-with-sector", "market.csv", sector="SECTOR")
    assert project.register_dataset(enriched).status is OutcomeStatus.COMPLETE
    retried = resolver.resolve(
        operation="strategy.run",
        idempotency_identity="strategy-2",
        requirements=(sector,),
        registry=project.registry_snapshot(),
    )
    assert not retried.failed
    assert retried.bindings[0].dataset_id == "market-with-sector"


def test_ambiguous_semantic_role_requires_an_explicit_dataset(tmp_path: Path) -> None:
    source = tmp_path / "market.csv"
    source.write_text(
        "DATE,CODE,VALUE\n2025-01-02,005930,10.0\n",
        encoding="utf-8",
    )
    project = initialized_project(tmp_path)
    for dataset_id in ("z-market", "a-market"):
        assert project.register_dataset(
            registration(dataset_id, "market.csv")
        ).status is OutcomeStatus.COMPLETE
    resolver = RequirementResolver()
    implicit = ComponentRequirement(
        requirement_id="strategy.value",
        semantic_role="value",
    )

    ambiguous = resolver.resolve(
        operation="strategy.run",
        idempotency_identity="strategy-ambiguous",
        requirements=(implicit,),
        registry=project.registry_snapshot(),
    )
    explicit = resolver.resolve(
        operation="strategy.run",
        idempotency_identity="strategy-explicit",
        requirements=(implicit.model_copy(update={"dataset_id": "z-market"}),),
        registry=project.registry_snapshot(),
    )

    assert ambiguous.failed
    error = ambiguous.errors[0]
    assert error.error_code == "REQUIREMENT_AMBIGUOUS"
    assert error.context["candidate_count"] == 2
    assert error.context["candidates"] == [
        {
            "dataset_id": "a-market",
            "registration_identity": project.registry_snapshot().get(
                "a-market"
            ).registration_identity,
        },
        {
            "dataset_id": "z-market",
            "registration_identity": project.registry_snapshot().get(
                "z-market"
            ).registration_identity,
        },
    ]
    assert not explicit.failed
    assert explicit.bindings[0].dataset_id == "z-market"


def test_registration_conflict_does_not_replace_existing_identity(tmp_path: Path) -> None:
    source = tmp_path / "market.csv"
    source.write_text("DATE,CODE,VALUE\n2025-01-02,005930,10.0\n", encoding="utf-8")
    project = initialized_project(tmp_path)
    first = project.register_dataset(registration("market", "market.csv"))
    original = project.registry_snapshot().get("market")

    source.write_text("DATE,CODE,VALUE\n2025-01-02,005930,11.0\n", encoding="utf-8")
    conflict = project.register_dataset(registration("market", "market.csv"))

    assert first.status is OutcomeStatus.COMPLETE
    assert conflict.status is OutcomeStatus.FAILED
    assert conflict.errors[0].error_code == "REGISTRATION_IDENTITY_CONFLICT"
    assert project.registry_snapshot().get("market") == original


def test_duplicate_logical_key_fails_before_publication(tmp_path: Path) -> None:
    source = tmp_path / "duplicate.csv"
    source.write_text(
        "DATE,CODE,VALUE\n2025-01-02,005930,10.0\n2025-01-02,005930,11.0\n",
        encoding="utf-8",
    )
    project = initialized_project(tmp_path)

    outcome = project.register_dataset(registration("duplicate", "duplicate.csv"))

    assert outcome.status is OutcomeStatus.FAILED
    assert outcome.errors[0].stage_path == "dataset.register.key_uniqueness"
    assert not project.registry_snapshot().datasets


def test_naive_source_timestamps_require_declared_timezone(tmp_path: Path) -> None:
    source = tmp_path / "market.csv"
    source.write_text("DATE,CODE,VALUE\n2025-01-02,005930,10.0\n", encoding="utf-8")
    project = initialized_project(tmp_path)
    undeclared = registration("market", "market.csv").model_copy(
        update={"source_timezone": None}
    )

    outcome = project.register_dataset(undeclared)

    assert outcome.status is OutcomeStatus.FAILED
    assert outcome.errors[0].error_code == "TIMESTAMP_TIMEZONE_UNDECLARED"
    assert outcome.errors[0].stage_path == "dataset.register.timestamp_timezone"
    assert outcome.errors[0].commit_status.value == "NONE"
    assert project.registry_snapshot().datasets == ()


@pytest.mark.parametrize(
    ("rows", "invalid_count", "samples"),
    (
        (
            "not-a-date,005930,10.0\nstill-not-a-date,069500,20.0\n",
            2,
            ("not-a-date", "still-not-a-date"),
        ),
        (
            "2025-01-02T06:30:00+00:00,005930,10.0\nnot-a-date,069500,20.0\n",
            1,
            ("not-a-date",),
        ),
    ),
)
def test_non_null_unparseable_availability_is_not_reported_as_timezone_error(
    tmp_path: Path,
    rows: str,
    invalid_count: int,
    samples: tuple[str, ...],
) -> None:
    source = tmp_path / "market.csv"
    source.write_text("DATE,CODE,VALUE\n" + rows, encoding="utf-8")
    project = initialized_project(tmp_path)
    undeclared = registration("market", "market.csv").model_copy(
        update={"source_timezone": None}
    )

    outcome = project.register_dataset(undeclared)

    assert outcome.status is OutcomeStatus.FAILED
    error = outcome.errors[0]
    assert error.error_code == "TIMESTAMP_VALUES_UNPARSEABLE"
    assert error.stage_path == "dataset.register.available_at"
    assert error.requirement_id == "dataset.available_at"
    assert error.context == {
        "field": "DATE",
        "invalid_count": invalid_count,
        "samples": samples,
    }
    assert project.registry_snapshot().datasets == ()


def test_unparseable_observation_time_identifies_its_requirement(tmp_path: Path) -> None:
    source = tmp_path / "market.csv"
    source.write_text(
        "AVAILABLE,OBSERVED,CODE,VALUE\n"
        "2025-01-02T06:30:00+00:00,not-a-date,005930,10.0\n",
        encoding="utf-8",
    )
    project = initialized_project(tmp_path)
    observed = registration("market", "market.csv").model_copy(
        update={
            "source_timezone": None,
            "available_at": AvailableAtField(field="AVAILABLE"),
            "observation_time_field": "OBSERVED",
            "logical_key": ("AVAILABLE", "CODE"),
        }
    )

    outcome = project.register_dataset(observed)

    assert outcome.status is OutcomeStatus.FAILED
    error = outcome.errors[0]
    assert error.error_code == "TIMESTAMP_VALUES_UNPARSEABLE"
    assert error.stage_path == "dataset.register.observation_time"
    assert error.requirement_id == "dataset.observation_time"
    assert error.context["samples"] == ("not-a-date",)
    assert project.registry_snapshot().datasets == ()


def test_null_availability_retains_available_at_invalid_error(tmp_path: Path) -> None:
    source = tmp_path / "market.csv"
    source.write_text("DATE,CODE,VALUE\n,005930,10.0\n", encoding="utf-8")
    project = initialized_project(tmp_path)
    nullable = registration("market", "market.csv").model_copy(
        update={"source_timezone": None, "logical_key": ("CODE",)}
    )

    outcome = project.register_dataset(nullable)

    assert outcome.status is OutcomeStatus.FAILED
    error = outcome.errors[0]
    assert error.error_code == "AVAILABLE_AT_INVALID"
    assert error.stage_path == "dataset.register.available_at"
    assert error.requirement_id == "dataset.available_at"
    assert project.registry_snapshot().datasets == ()


def test_declared_source_timezone_localizes_naive_timestamps(tmp_path: Path) -> None:
    source = tmp_path / "market.csv"
    source.write_text(
        "DATE,CODE,VALUE\n2025-01-02T15:30:00,005930,10.0\n",
        encoding="utf-8",
    )
    project = initialized_project(tmp_path)
    declared = registration("market", "market.csv").model_copy(
        update={"source_timezone": "Asia/Seoul"}
    )

    outcome = project.register_dataset(declared)

    assert outcome.status is OutcomeStatus.COMPLETE
    registered = outcome.result
    assert registered.evidence.available_at_min == "2025-01-02T06:30:00+00:00"
    assert registered.evidence.localized_source_timezone == "Asia/Seoul"
    store = ObservationStore()
    before = store.query(
        registered,
        field="VALUE",
        as_of=datetime(2025, 1, 2, 6, 29, tzinfo=UTC),
    )
    at = store.query(
        registered,
        field="VALUE",
        as_of=datetime(2025, 1, 2, 6, 30, tzinfo=UTC),
    )
    assert before.empty
    assert at["value"].tolist() == [10.0]


def test_declared_timezone_over_aware_timestamps_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "market.csv"
    source.write_text(
        "DATE,CODE,VALUE\n2025-01-02T06:30:00+00:00,005930,10.0\n",
        encoding="utf-8",
    )
    project = initialized_project(tmp_path)

    outcome = project.register_dataset(registration("market", "market.csv"))

    assert outcome.status is OutcomeStatus.FAILED
    assert outcome.errors[0].error_code == "TIMESTAMP_TIMEZONE_UNUSED"
    assert outcome.errors[0].commit_status.value == "NONE"
    assert project.registry_snapshot().datasets == ()


def test_unknown_source_timezone_is_a_validation_error() -> None:
    payload = registration("market", "market.csv").model_dump()
    payload["source_timezone"] = "Mars/Olympus"

    with pytest.raises(ValidationError, match="unknown source_timezone"):
        DatasetRegistration.model_validate(payload)


def test_unsupported_atomic_publication_fails_without_visibility(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "market.csv"
    source.write_text("DATE,CODE,VALUE\n2025-01-02,005930,10.0\n", encoding="utf-8")
    project = initialized_project(tmp_path)

    def reject_link(source_path: object, destination_path: object) -> None:
        del source_path, destination_path
        raise OSError("hard links unsupported")

    monkeypatch.setattr("qlibx.data.registry.os.link", reject_link)
    outcome = project.register_dataset(registration("market", "market.csv"))

    assert outcome.status is OutcomeStatus.FAILED
    assert outcome.errors[0].error_code == "DATASET_QUERY_SNAPSHOT_PUBLICATION_FAILED"
    assert outcome.errors[0].commit_status.value == "NONE"
    assert project.registry_snapshot().datasets == ()

def test_delay_rule_requires_explicit_user_confirmation() -> None:
    with pytest.raises(ValidationError):
        ConfirmedDelayRule.model_validate(
            {
                "source_field": "DATE",
                "delay_seconds": 86400,
                "rule_id": "source-t-plus-one",
                "user_confirmed": False,
            }
        )
