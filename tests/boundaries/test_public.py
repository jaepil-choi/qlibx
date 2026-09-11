"""UC-FACADE-001 — data registration uses only the documented public module."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import duckdb
import pytest

import vqapr.public as public
import vqapr.run.assemble as orchestration
from vqapr.public import (
    QUANTUM,
    SHIPPED_COMPLIANCE,
    AcademicExchange,
    AccountMode,
    AccountSnapshot,
    AllocationInvariants,
    AllocationSign,
    AllocationViolation,
    Budget,
    CalendarLookback,
    Compliance,
    ComplianceCall,
    ComplianceFinding,
    ComplianceReport,
    ComplianceSet,
    Component,
    ComponentRef,
    CrossSection,
    DataModel,
    DataModelContext,
    DataRequirement,
    DatasetRegistration,
    EconomicPortfolioIntent,
    EtfInstrument,
    ExecutionRole,
    FactorInstrument,
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
    OptimizeRefusal,
    OptimizeResult,
    PortfolioDirection,
    PortfolioTarget,
    Role,
    RowsLookback,
    RunDefinition,
    Series,
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
    register_data_model,
    register_dataset,
    register_strategy_model,
    run,
    shipped_compliance_path,
    validate_allocation,
)
from vqapr.workspace.registry import Workspace


def _registration(**overrides) -> DatasetRegistration:
    kwargs = {
        "instrument_field": "instrument",
        "available_at": "available_at",
        "key_fields": ("session_date", "instrument"),
        "grain": "rows",
        "fields": {"close": "close", "session_date": "session_date"},
        "field_types": {"close": "INTEGER", "session_date": "DATE"},
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
            CrossSection,
            Component,
            Role,
            ComponentRef,
            Compliance,
            ComplianceCall,
            ComplianceFinding,
            ComplianceReport,
            ComplianceSet,
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
            Series,
            Side,
            StrategyModel,
            StrategyModelContext,
            callback_evidence,
            optimize,
            preflight_run,
            register_data_model,
            register_strategy_model,
            run,
            shipped_compliance_path,
            validate_allocation,
        )
    )
    assert QUANTUM is public.QUANTUM
    assert SHIPPED_COMPLIANCE is public.SHIPPED_COMPLIANCE
    assert public.__all__ == (
        "QUANTUM",
        "SHIPPED_COMPLIANCE",
        "AcademicExchange",
        "AccountMode",
        "AccountSnapshot",
        "AllocationInvariants",
        "AllocationSign",
        "AllocationViolation",
        "Budget",
        "CalendarLookback",
        "Call",
        "Compliance",
        "ComplianceCall",
        "ComplianceFinding",
        "ComplianceReport",
        "ComplianceSet",
        "Component",
        "ComponentRef",
        "CrossSection",
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
        "ExecutionCall",
        "ExecutionFieldRequirement",
        "ExecutionRole",
        "ExecutionTable",
        "ExecutionTableSpec",
        "FactorInstrument",
        "FillCost",
        "FillRule",
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
        "KrxSettings",
        "KrxTradeRule",
        "ListingAccess",
        "LocalInstantDeclaration",
        "Mark",
        "MarkBatch",
        "ModelWindow",
        "NeutralizationRefusal",
        "ObservationBatch",
        "OperationOccurrence",
        "OptimizeRefusal",
        "OptimizeResult",
        "PanelWindow",
        "Part",
        "PortfolioDirection",
        "PortfolioTarget",
        "Rebalance",
        "Role",
        "RowsLookback",
        "RunAgenda",
        "RunDefinition",
        "RunExecution",
        "RunFill",
        "RunRecordMissing",
        "RunReport",
        "RunResult",
        "Series",
        "Side",
        "SideCost",
        "SimulationFailure",
        "SimulationResult",
        "SourceSpec",
        "Stage",
        "Status",
        "StockInstrument",
        "StrategyEntry",
        "StrategyModel",
        "StrategyModelContext",
        "StrategyOutcome",
        "StrategyReport",
        "TableSpec",
        "TickerNetting",
        "Tool",
        "TradeRule",
        "TradeTerms",
        "VqaprError",
        "WeightingRefusal",
        "ZeroDealtReason",
        "build_roster",
        "callback_evidence",
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
        "intersect",
        "krx_listings",
        "krx_rules",
        "nav_series",
        "net_members",
        "neutralize",
        "no_short",
        "optimize",
        "preflight_run",
        "proportional_weight",
        "rank",
        "rank_information_coefficient",
        "read_run_record",
        "read_strategy_record",
        "read_strategy_table",
        "register_compliance",
        "register_data_model",
        "register_dataset",
        "register_exchange",
        "register_instruments",
        "register_run",
        "register_strategy_model",
        "rescale",
        "returns",
        "run",
        "run_ids",
        "run_report",
        "shipped_compliance_path",
        "signal_weight",
        "single_name_cap",
        "strategy_refs",
        "strategy_report",
        "trade_rules_by_kind",
        "validate_allocation",
    )
    assert "Workspace" not in public.__all__
    assert "strategy_loop" not in public.__all__
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
        register_dataset(
            tmp_path,
            _registration(fields={"close": "missing"}, field_types={"close": "INTEGER"}),
            source,
        )

    payload = caught.value.as_dict()
    assert payload["mutation"] is False
    assert payload["stage"] == "register"
    assert payload["failures"][0]["code"] == "dataset.field_missing"
    assert not (tmp_path / ".vqapr").exists()


@pytest.mark.uc("UC-FACADE-001")
def test_key_failure_does_not_create_a_workspace(tmp_path: Path, dup_parquet: Path) -> None:
    source = SourceSpec.of("prices", dup_parquet)

    with pytest.raises(VqaprError) as caught:
        register_dataset(tmp_path, _registration(), source)

    payload = caught.value.as_dict()
    assert payload["mutation"] is False
    assert payload["stage"] == "register"
    assert {failure["code"] for failure in payload["failures"]} == {
        "dataset.key_duplicate",
        "dataset.key_null",
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
    assert payload["stage"] == "register"
    assert payload["failures"][0]["code"] == "dataset.source_mismatch"
    assert not missing.exists()
    assert not (tmp_path / ".vqapr").exists()


@pytest.mark.uc("UC-FACADE-001")
def test_source_open_failure_does_not_create_a_workspace(tmp_path: Path) -> None:
    source = SourceSpec.of("prices", tmp_path / "source-does-not-exist")

    with pytest.raises(VqaprError) as caught:
        register_dataset(tmp_path, _registration(), source)

    payload = caught.value.as_dict()
    assert payload["mutation"] is False
    assert payload["failures"][0]["code"] == "source.path_missing"
    assert not (tmp_path / ".vqapr").exists()


@pytest.mark.uc("UC-EXEC-001")
def test_public_facade_registers_a_venue_table_as_a_dataset(
    tmp_path: Path, execution_parquet: Path
) -> None:
    """The execution table is data (record `185`): it registers through the dataset door, with
    an execution role; which price a run fills at is the run's, not the registration's."""
    registration = DatasetRegistration.of(
        "krx-daily",
        "execution",
        instrument_field="instrument",
        available_at="trade_at",
        key_fields=("trade_at", "instrument"),
        fields={"close": "close", "is_tradable": "is_tradable"},
        field_types={"close": "DOUBLE", "is_tradable": "BOOLEAN"},
        grain="instrument_instant",
        execution={"is_tradable": "is_tradable"},
    )
    assert registration.execution == ExecutionRole("is_tradable")
    source = SourceSpec.of("execution", execution_parquet)

    assert register_dataset(tmp_path, registration, source) is True
    before = (tmp_path / ".vqapr" / "workspace.yaml").read_bytes()
    assert register_dataset(tmp_path, registration, source) is False
    assert (tmp_path / ".vqapr" / "workspace.yaml").read_bytes() == before
    assert Workspace.open(tmp_path).dataset("krx-daily").execution == ExecutionRole("is_tradable")


def test_public_run_uses_frozen_initial_model_memory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The strategy layer's frozen memory reaches the loaded strategy, detached (record `139`)."""
    from vqapr.run.preflight.frozen import FrozenStrategy

    memory = {"carry": [1]}
    layer = object.__new__(FrozenStrategy)
    for name, value in {
        "config": SimpleNamespace(component=SimpleNamespace(component_id="s")),
        "compliance": SimpleNamespace(rules=()),
        "agenda": SimpleNamespace(occurrences=()),
        "requirements": (),
        "compliance_requirements": (),
        "initial_model_memory": memory,
        "initial_model_state_ref": "frozen-memory-ref",
        "initial_payload": b"",
        "_identity": "layer",
    }.items():
        object.__setattr__(layer, name, value)
    frozen = object.__new__(FrozenRun)
    for name, value in {
        "run_id": "facade",
        "writes": "facade-weights",
        "initial_account_snapshot": AccountSnapshot(0, Decimal("100"), {}),
        "initial_account_mode": AccountMode.LONG_ONLY,
        "exchange": object(),
        "execution": object(),
        "strategy": layer,
        "datamodel": None,
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

    # What `public.run` reads off a finished run and nothing more: the recorder rows it
    # publishes under `writes` (none here, so nothing is published). One object, so the
    # assertions below can check identity: the outcome carries what the flow returned.
    finished = SimpleNamespace(final_state=SimpleNamespace(recorder_rows={}))

    class Flow:
        def __init__(self, _frozen, loaded_strategy, state, **_kwargs) -> None:
            observed["frozen"] = _frozen
            observed["memory"] = loaded_strategy.memory
            observed["ref"] = state.root.current_model_state_ref

        def run(self) -> object:
            return finished

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
    # `run` lives in `vqapr.run.assemble` since record `111`, so the loader it calls is
    # patched there. `vqapr.public.run` is the same function object, re-exported.
    monkeypatch.setattr(orchestration, "load_strategy_model", lambda *_a, **_k: strategy)
    monkeypatch.setattr(orchestration, "load_exchange", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(orchestration, "RunStateRepository", State)
    monkeypatch.setattr(orchestration, "strategy_loop", Flow)

    outcome = public.run(tmp_path, frozen)
    assert outcome.result() is finished
    assert outcome.results == {"s": finished}
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
def test_a_non_positive_execution_price_is_measured_without_creating_a_workspace(
    tmp_path: Path,
) -> None:
    target = tmp_path / "bad-execution.parquet"
    con = duckdb.connect()
    try:
        con.execute(
            f"""COPY (
                SELECT TIMESTAMPTZ '2024-03-05 15:30:00+09' AS trade_at,
                       'A' AS instrument, true AS is_tradable,
                       99.0::DOUBLE AS open, 0.0::DOUBLE AS close
            ) TO '{target.as_posix()}' (FORMAT PARQUET)"""
        )
    finally:
        con.close()
    from vqapr.data.dataset import DatasetRegistration
    from vqapr.data.verification import verify_source

    registration = DatasetRegistration.of(
        "krx-daily",
        "execution",
        instrument_field="instrument",
        available_at="trade_at",
        key_fields=("trade_at", "instrument"),
        fields={"open": "open", "close": "close", "is_tradable": "is_tradable"},
        field_types={"open": "DOUBLE", "close": "DOUBLE", "is_tradable": "BOOLEAN"},
        grain="instrument_instant",
        execution={"is_tradable": "is_tradable"},
    )

    # The one door measures which prices are finite and positive wherever a row is tradable
    # (record `234`); a run that chooses `close` is refused at preflight by that fact. Nothing
    # here touches a workspace.
    diagnosis, _, measured = verify_source(registration, SourceSpec.of("execution", target))

    assert diagnosis.ok
    assert measured.execution_prices == ("open",)
    assert not (tmp_path / ".vqapr").exists()
