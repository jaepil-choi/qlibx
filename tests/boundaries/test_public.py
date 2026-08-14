"""UC-FACADE-001 — data registration uses only the documented public module."""

from __future__ import annotations

from pathlib import Path

import pytest

import vqapr.public as public
from vqapr.public import DatasetRegistration, SourceSpec, VqaprError, register_dataset


def _registration(**overrides) -> DatasetRegistration:
    kwargs = {
        "instrument_field": "instrument",
        "available_at": "available_at",
        "key_fields": ("session_date", "instrument"),
        "fields": {"close": "close", "session_date": "session_date"},
    }
    kwargs.update(overrides)
    return DatasetRegistration.of("price_daily", "prices", **kwargs)


@pytest.mark.uc("UC-FACADE-001")
def test_public_exports_are_fixed() -> None:
    assert public.__all__ == (
        "DatasetRegistration",
        "SourceSpec",
        "VqaprError",
        "register_dataset",
    )


@pytest.mark.uc("UC-FACADE-001")
def test_public_facade_registers_and_reports_an_idempotent_retry(
    tmp_path: Path, hive_parquet: Path
) -> None:
    source = SourceSpec.of("prices", hive_parquet, hive_partitioned=True)

    assert register_dataset(tmp_path, _registration(), source) is True
    assert register_dataset(tmp_path, _registration(), source) is False
    assert (tmp_path / ".vqapr" / "workspace.yaml").is_file()


@pytest.mark.uc("UC-FACADE-001")
def test_schema_failure_does_not_create_a_workspace(tmp_path: Path, hive_parquet: Path) -> None:
    source = SourceSpec.of("prices", hive_parquet, hive_partitioned=True)

    with pytest.raises(VqaprError) as caught:
        register_dataset(tmp_path, _registration(fields={"close": "missing"}), source)

    payload = caught.value.as_dict()
    assert payload["mutation"] is False
    assert payload["stage"] == "dataset.register.schema"
    assert payload["failures"][0]["code"] == "dataset.register.schema.field_missing"
    assert not (tmp_path / ".vqapr").exists()


@pytest.mark.uc("UC-FACADE-001")
def test_key_failure_does_not_create_a_workspace(tmp_path: Path, dup_parquet: Path) -> None:
    source = SourceSpec.of("prices", dup_parquet)

    with pytest.raises(VqaprError) as caught:
        register_dataset(tmp_path, _registration(), source)

    payload = caught.value.as_dict()
    assert payload["mutation"] is False
    assert payload["stage"] == "dataset.register.key"
    assert {failure["code"] for failure in payload["failures"]} == {
        "dataset.register.key.duplicate",
        "dataset.register.key.null",
    }
    assert not (tmp_path / ".vqapr").exists()


@pytest.mark.uc("UC-FACADE-001")
def test_source_id_mismatch_fails_before_opening_or_mutating(tmp_path: Path) -> None:
    missing = tmp_path / "source-does-not-exist"
    source = SourceSpec.of("other", missing)

    with pytest.raises(VqaprError) as caught:
        register_dataset(tmp_path, _registration(), source)

    payload = caught.value.as_dict()
    assert payload["mutation"] is False
    assert payload["stage"] == "dataset.register.schema"
    assert payload["failures"][0]["code"] == "dataset.register.schema.source_mismatch"
    assert not missing.exists()
    assert not (tmp_path / ".vqapr").exists()


@pytest.mark.uc("UC-FACADE-001")
def test_source_open_failure_does_not_create_a_workspace(tmp_path: Path) -> None:
    source = SourceSpec.of("prices", tmp_path / "source-does-not-exist")

    with pytest.raises(VqaprError) as caught:
        register_dataset(tmp_path, _registration(), source)

    payload = caught.value.as_dict()
    assert payload["mutation"] is False
    assert payload["failures"][0]["code"] == "source.scan.path_missing"
    assert not (tmp_path / ".vqapr").exists()
