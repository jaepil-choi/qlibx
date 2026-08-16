"""UC-FACADE-001 — data registration uses only the documented public module."""

from __future__ import annotations

from datetime import date, time
from pathlib import Path

import duckdb
import pytest

import vqapr.public as public
from vqapr.domain.timestamps import LocalInstantDeclaration
from vqapr.public import (
    CalendarLookback,
    ComponentRef,
    DataModel,
    DataModelContext,
    DataRequirement,
    DatasetRegistration,
    ExecutionInputRegistration,
    ExecutionTableSpec,
    FillConvention,
    MaterializationResult,
    MaterializationSpec,
    MonitoringPolicy,
    OperationAgenda,
    RowsLookback,
    SourceSpec,
    VqaprError,
    materialize,
    register_agenda,
    register_data_model,
    register_dataset,
    register_execution_input,
    register_monitoring_policy,
    register_strategy_config,
    register_valuation_config,
)
from vqapr.runtime.agendas import OperationOccurrence, OperationRole


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
    assert all(
        value is getattr(public, value.__name__)
        for value in (
            CalendarLookback,
            ComponentRef,
            DataModel,
            DataModelContext,
            DataRequirement,
            MaterializationResult,
            MaterializationSpec,
            MonitoringPolicy,
            OperationAgenda,
            RowsLookback,
            materialize,
            register_agenda,
            register_data_model,
            register_monitoring_policy,
            register_strategy_config,
            register_valuation_config,
        )
    )
    assert public.__all__ == (
        "CalendarLookback",
        "ComponentRef",
        "DataModel",
        "DataModelContext",
        "DataRequirement",
        "DatasetRegistration",
        "ExecutionInputRegistration",
        "ExecutionTableSpec",
        "FillConvention",
        "MaterializationResult",
        "MaterializationSpec",
        "MonitoringPolicy",
        "OperationAgenda",
        "RowsLookback",
        "SourceSpec",
        "StrategyConfig",
        "ValuationConfig",
        "VqaprError",
        "materialize",
        "register_agenda",
        "register_data_model",
        "register_dataset",
        "register_execution_input",
        "register_monitoring_policy",
        "register_strategy_config",
        "register_valuation_config",
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


@pytest.mark.uc("UC-EXEC-001")
def test_public_facade_registers_a_valid_execution_input(
    tmp_path: Path, execution_parquet: Path
) -> None:
    registration = ExecutionInputRegistration.of(
        "krx-daily",
        ExecutionTableSpec(
            source=SourceSpec.of("execution", execution_parquet),
            trade_at_field="trade_at",
            instrument_field="instrument",
            is_tradable_field="is_tradable",
            price_fields={"close": "close"},
        ),
        FillConvention(
            offset_sessions=0,
            local_time=time(15, 30),
            timezone="Asia/Seoul",
            trade_price="close",
        ),
    )

    assert register_execution_input(tmp_path, registration) is True
    before = (tmp_path / ".vqapr" / "workspace.yaml").read_bytes()
    assert register_execution_input(tmp_path, registration) is False
    assert (tmp_path / ".vqapr" / "workspace.yaml").read_bytes() == before


def test_public_facade_registers_an_operation_agenda(tmp_path: Path) -> None:
    agenda = OperationAgenda.from_occurrences(
        agenda_id="strategy-agenda",
        role=OperationRole.STRATEGY_CALLBACK,
        timezone="Asia/Seoul",
        occurrences=(
            OperationOccurrence(
                "first",
                OperationRole.STRATEGY_CALLBACK,
                LocalInstantDeclaration(date(2024, 3, 5), time(15, 30), "Asia/Seoul", 0, "+09:00"),
            ),
        ),
        provenance="facade test",
    )

    assert register_agenda(tmp_path, agenda) is True
    assert register_agenda(tmp_path, agenda) is False


@pytest.mark.uc("UC-FILL-001")
def test_execution_price_failure_does_not_create_a_workspace(tmp_path: Path) -> None:
    target = tmp_path / "bad-execution.parquet"
    con = duckdb.connect()
    try:
        con.execute(
            f"""COPY (
                SELECT TIMESTAMPTZ '2024-03-05 15:30:00+09' AS trade_at,
                       'A' AS instrument, true AS is_tradable,
                       99.0 AS open, CAST('NaN' AS DOUBLE) AS close
            ) TO '{target.as_posix()}' (FORMAT PARQUET)"""
        )
    finally:
        con.close()
    registration = ExecutionInputRegistration.of(
        "krx-daily",
        ExecutionTableSpec(
            source=SourceSpec.of("execution", target),
            trade_at_field="trade_at",
            instrument_field="instrument",
            is_tradable_field="is_tradable",
            price_fields={"open": "open", "close": "close"},
        ),
        FillConvention(
            offset_sessions=0,
            local_time=time(15, 30),
            timezone="Asia/Seoul",
            trade_price="close",
        ),
    )

    with pytest.raises(VqaprError) as caught:
        register_execution_input(tmp_path, registration)

    assert caught.value.mutation is False
    assert caught.value.failures[0].code == "execution_input.register.price.invalid"
    assert not (tmp_path / ".vqapr").exists()
