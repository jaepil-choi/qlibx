from pathlib import Path

import pytest
from pydantic import ValidationError

from qlibx import OutcomeStatus, QlibxProject
from qlibx.data import (
    AvailableAtField,
    ComponentRequirement,
    ConfirmedDelayRule,
    DatasetRegistration,
    RequirementResolver,
    SourceFormat,
)


def registration(dataset_id: str, source: str, **bindings: str) -> DatasetRegistration:
    return DatasetRegistration(
        dataset_id=dataset_id,
        source=source,
        source_format=SourceFormat.CSV,
        instrument_field="CODE",
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
