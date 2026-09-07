"""UC-FACADE-001 — data registration uses only the documented public module."""

from __future__ import annotations

from datetime import time
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import duckdb
import pytest

import vqapr.flow.orchestration as orchestration
import vqapr.public as public
from vqapr.public import (
    QUANTUM,
    SHIPPED_CONSTRAINTS,
    AcademicExchange,
    AccountMode,
    AccountSnapshot,
    AllocationInvariants,
    AllocationSign,
    AllocationViolation,
    Budget,
    CalendarLookback,
    ComponentKind,
    ComponentRef,
    Constraint,
    ConstraintBounds,
    ConstraintFinding,
    ConstraintReport,
    ConstraintSet,
    DataModel,
    DataModelContext,
    DataRequirement,
    DatasetRegistration,
    EconomicPortfolioIntent,
    EtfInstrument,
    ExecutionInputRegistration,
    ExecutionTableSpec,
    FactorInstrument,
    FillConvention,
    FillSelector,
    FrozenAgenda,
    FrozenRun,
    Hold,
    IndexInstrument,
    Instrument,
    InstrumentKind,
    IntentSourceRef,
    ListingAccess,
    LocalInstantDeclaration,
    OperationOccurrence,
    OperationRole,
    OptimizeRefusal,
    OptimizeResult,
    PortfolioDirection,
    PortfolioTarget,
    RowsLookback,
    RunDefinition,
    Side,
    SimulationFailure,
    SimulationResult,
    SourceSpec,
    StockInstrument,
    StrategyModel,
    StrategyModelContext,
    TradeRule,
    VqaprError,
    callback_evidence,
    optimize,
    preflight_run,
    register_component,
    register_data_model,
    register_dataset,
    register_execution_input,
    register_strategy_model,
    run,
    shipped_constraint_path,
    validate_allocation,
)


def _registration(**overrides) -> DatasetRegistration:
    kwargs = {
        "instrument_field": "instrument",
        "available_at": "available_at",
        "key_fields": ("session_date", "instrument"),
        "grain": "rows",
        "fields": {"close": "close", "session_date": "session_date"},
    }
    kwargs.update(overrides)
    return DatasetRegistration.of("price_daily", "prices", **kwargs)


@pytest.mark.uc("UC-FACADE-001")
def test_public_exports_are_fixed() -> None:
    assert all(
        value is getattr(public, value.__name__)
        for value in (
            AcademicExchange,
            AccountMode,
            AccountSnapshot,
            Budget,
            CalendarLookback,
            ComponentKind,
            ComponentRef,
            Constraint,
            ConstraintBounds,
            ConstraintFinding,
            ConstraintReport,
            ConstraintSet,
            DataModel,
            DataModelContext,
            DataRequirement,
            EconomicPortfolioIntent,
            FrozenAgenda,
            FrozenRun,
            Instrument,
            InstrumentKind,
            IntentSourceRef,
            ListingAccess,
            TradeRule,
            LocalInstantDeclaration,
            AllocationInvariants,
            AllocationSign,
            AllocationViolation,
            Hold,
            OperationOccurrence,
            OperationRole,
            OptimizeRefusal,
            OptimizeResult,
            PortfolioDirection,
            PortfolioTarget,
            RowsLookback,
            RunDefinition,
            SimulationFailure,
            StockInstrument,
            EtfInstrument,
            IndexInstrument,
            FactorInstrument,
            SimulationResult,
            Side,
            StrategyModel,
            StrategyModelContext,
            callback_evidence,
            optimize,
            preflight_run,
            register_component,
            register_data_model,
            register_strategy_model,
            run,
            shipped_constraint_path,
            validate_allocation,
        )
    )
    assert QUANTUM is public.QUANTUM
    assert SHIPPED_CONSTRAINTS is public.SHIPPED_CONSTRAINTS
    assert public.__all__ == (
        "QUANTUM",
        "SHIPPED_CONSTRAINTS",
        "AcademicExchange",
        "AccountMode",
        "AccountSnapshot",
        "AllocationInvariants",
        "AllocationSign",
        "AllocationViolation",
        "Budget",
        "CalendarLookback",
        "ComponentKind",
        "ComponentRef",
        "Constraint",
        "ConstraintBounds",
        "ConstraintFinding",
        "ConstraintReport",
        "ConstraintSet",
        "DataModel",
        "DataModelContext",
        "DataModelEntry",
        "DataModelResult",
        "DataRequirement",
        "DatasetInput",
        "DatasetRegistration",
        "EconomicPortfolioIntent",
        "EtfInstrument",
        "ExactExecutionTarget",
        "ExchangeRulesView",
        "ExecutionFieldRequirement",
        "ExecutionInputRegistration",
        "ExecutionTableSpec",
        "FactorInstrument",
        "FillConvention",
        "FillCost",
        "FillSelector",
        "FrozenAgenda",
        "FrozenDataModel",
        "FrozenRun",
        "FrozenStrategy",
        "Grain",
        "Hold",
        "IndexInstrument",
        "InstantsLookback",
        "Instrument",
        "InstrumentKind",
        "InstrumentRoster",
        "IntentSourceRef",
        "KrxExchange",
        "KrxTradeRule",
        "ListingAccess",
        "LocalInstantDeclaration",
        "Mark",
        "MarkBatch",
        "ModelWindow",
        "NeutralizationRefusal",
        # `docs/issues/031`: the return type of `ModelWindow.observations`, which is the only
        # method a DataModel author can call, and which could not be imported from the facade.
        "ObservationBatch",
        "OperationOccurrence",
        "OperationRole",
        "OptimizeRefusal",
        "OptimizeResult",
        "PanelWindow",
        "PortfolioDirection",
        "PortfolioTarget",
        "Rebalance",
        "RowsLookback",
        "RunDefinition",
        "RunRecordMissing",
        "RunResult",
        "Side",
        "SideCost",
        "SimulationFailure",
        "SimulationResult",
        "SourceSpec",
        "StockInstrument",
        "StrategyEntry",
        "StrategyModel",
        "StrategyModelContext",
        "StrategyOutcome",
        "TableSpec",
        "TickerNetting",
        "TradeRule",
        "TradeTerms",
        "VqaprError",
        "WeightingRefusal",
        "ZeroDealtReason",
        "build_roster",
        "callback_evidence",
        "component_ref",
        "conformance",
        "decay",
        "declare_local_instant",
        "drawdown",
        "equal_weight",
        "export_roster",
        "fama_french_assign",
        "fama_french_cut_points",
        "hit_rate",
        "information_coefficient",
        "instrument",
        "instruments",
        "krx_listings",
        "krx_rules",
        "nav_series",
        "net_members",
        "neutralize",
        "optimize",
        "preflight_run",
        "proportional_weight",
        "rank",
        "rank_information_coefficient",
        "read_run_record",
        "read_strategy_record",
        "read_strategy_table",
        "register_component",
        "register_constraint",
        "register_data_model",
        "register_dataset",
        "register_exchange",
        "register_execution_input",
        "register_run",
        "register_strategy_model",
        "rescale",
        "returns",
        "run",
        "run_ids",
        "shipped_constraint_path",
        "signal_weight",
        "strategy_refs",
        "trade_rules_by_kind",
        "validate_allocation",
    )
    assert "Workspace" not in public.__all__
    assert "SimulationFlow" not in public.__all__
    assert "DuckDbObservationStore" not in public.__all__
    assert "RunStateRepository" not in public.__all__
    assert "AccountState" not in public.__all__
    assert "Dispatcher" not in public.__all__


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
            selector=FillSelector.NEXT_ELIGIBLE,
            local_time=time(15, 30),
            timezone="Asia/Seoul",
            trade_price="close",
        ),
    )

    assert register_execution_input(tmp_path, registration) is True
    before = (tmp_path / ".vqapr" / "workspace.yaml").read_bytes()
    assert register_execution_input(tmp_path, registration) is False
    assert (tmp_path / ".vqapr" / "workspace.yaml").read_bytes() == before


def test_public_run_uses_frozen_initial_model_memory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The strategy layer's frozen memory reaches the loaded strategy, detached (record `139`)."""
    from vqapr.flow.frozen import FrozenStrategy

    memory = {"carry": [1]}
    layer = object.__new__(FrozenStrategy)
    for name, value in {
        "config": SimpleNamespace(component=SimpleNamespace(component_id="s")),
        "constraints": SimpleNamespace(constraints=()),
        "agenda": SimpleNamespace(occurrences=()),
        "requirements": (),
        "constraint_requirements": (),
        "initial_model_memory": memory,
        "initial_model_state_ref": "frozen-memory-ref",
        "initial_payload": b"",
        "_identity": "layer",
    }.items():
        object.__setattr__(layer, name, value)
    frozen = object.__new__(FrozenRun)
    for name, value in {
        "run_id": "facade",
        "initial_account_snapshot": AccountSnapshot(0, Decimal("100"), {}),
        "initial_account_mode": AccountMode.LONG_ONLY,
        "exchange": object(),
        "execution_input": object(),
        "strategies": (layer,),
        "datamodels": (),
        "datasets": (),
        "sources": (),
        "instruments": ("A",),
        "requirements": (),
    }.items():
        object.__setattr__(frozen, name, value)
    strategy = SimpleNamespace(
        memory={"default": True},
        requirements=lambda: (),
        account_history=lambda: None,
        load_payload=lambda _source: None,
    )
    observed: dict[str, object] = {}

    class Flow:
        def __init__(self, _frozen, loaded_strategy, state, **_kwargs) -> None:
            observed["frozen"] = _frozen
            observed["memory"] = loaded_strategy.memory
            observed["ref"] = state.root.current_model_state_ref

        def run(self) -> object:
            return "result"

    class State:
        def __init__(self, **_kwargs) -> None:
            self.root = SimpleNamespace(current_model_state_ref="frozen-memory-ref")

        def load_payload(self, _ref: object) -> bytes:
            return b""

    monkeypatch.setattr(
        orchestration,
        "preflight_run",
        lambda *_args: pytest.fail("run must not preflight a FrozenRun"),
    )
    # `run` lives in `vqapr.flow.orchestration` since record `111`, so the loader it calls is
    # patched there. `vqapr.public.run` is the same function object, re-exported.
    monkeypatch.setattr(orchestration, "load_strategy_model", lambda *_a, **_k: strategy)
    monkeypatch.setattr(orchestration, "load_exchange", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        orchestration,
        "validate_execution_input",
        lambda _registration: SimpleNamespace(raise_if_failed=lambda: None),
    )
    monkeypatch.setattr(orchestration, "RunStateRepository", State)
    monkeypatch.setattr(orchestration, "SimulationFlow", Flow)

    outcome = public.run(tmp_path, frozen)
    assert outcome.result() == "result"
    assert outcome.results == {"s": "result"}
    memory["carry"].append(2)
    assert observed == {
        "frozen": frozen,
        "memory": {"carry": [1]},
        "ref": layer.initial_model_state_ref,
    }


def test_public_run_rejects_anything_other_than_a_frozen_run(tmp_path: Path) -> None:
    with pytest.raises(TypeError, match="frozen_run must be a FrozenRun"):
        public.run(tmp_path, object())


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
            selector=FillSelector.NEXT_ELIGIBLE,
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
