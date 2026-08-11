from dataclasses import replace
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from qlibx import (
    ConstraintAdjustmentSpec,
    ConstraintMonitoringSpec,
    ConstraintValidationSpec,
    CostRule,
    DailyAccountSeed,
    DailyMarketBinding,
    DailySimulationSpec,
    ExecutionLotInput,
    KrxExchangeConfig,
    MvpConstraintPolicy,
    OutcomeStatus,
    QlibxProject,
    Side,
    StockInstrument,
    StrategyInvocation,
)
from qlibx.contracts import (
    BudgetMode,
    DecisionAction,
    EveryNSessions,
    StrategyDraft,
    WeightEntry,
)
from qlibx.data import AvailableAtField, DatasetRegistration, SourceFormat
from qlibx.errors import CommitStatus
from qlibx.execution.preparation import KRX_PREPARATION_CONTRACT
from qlibx.flow import PORTFOLIO_RESULT_CONTRACT
from qlibx.flow.analysis import SIMULATION_CHECKPOINT_CONTRACT
from qlibx.portfolio import (
    ConstructionProfile,
    PortfolioConstructionResult,
    PortfolioWeight,
)

KST = ZoneInfo("Asia/Seoul")


class ConstraintFreeStrategy:
    strategy_id = "test.constraint-free"

    def requirements(self) -> tuple[object, ...]:
        return ()

    def run(self, view: object) -> StrategyDraft:
        return StrategyDraft(
            weights=(WeightEntry(instrument="A005930", weight=1.0),),
            budget_mode=BudgetMode.FIXED,
            target_gross=1.0,
            decision_action=DecisionAction.RESEARCH_ONLY,
        )


class MonitoringSeedStrategy:
    strategy_id = "test.monitoring-seed"

    def requirements(self) -> tuple[object, ...]:
        return ()

    def trigger(self) -> EveryNSessions:
        return EveryNSessions(n=2)

    def run(self, view: object) -> StrategyDraft:
        return StrategyDraft(
            weights=(WeightEntry(instrument="A005930", weight=1.0),),
            budget_mode=BudgetMode.FIXED,
            target_gross=1.0,
            decision_action=DecisionAction.TARGET,
        )


def evaluation_time() -> datetime:
    return datetime(2024, 1, 3, 15, 30, tzinfo=KST)


def create_project(tmp_path: Path, name: str) -> QlibxProject:
    root = tmp_path / name
    QlibxProject.init(root, apply=True)
    return QlibxProject.open(root)


def import_source_portfolio(project: QlibxProject, identity: str = "public-source") -> str:
    source = PortfolioConstructionResult(
        invocation_id=f"{identity}-portfolio",
        source_artifact_id=f"{identity}-strategy",
        source_strategy_id="test.public-signed",
        evaluation_time=evaluation_time(),
        profile=ConstructionProfile.HYPOTHETICAL_SIGNED,
        original_weights=(
            PortfolioWeight(instrument="A005930", weight=0.6),
            PortfolioWeight(instrument="A000660", weight=-0.4),
        ),
        target_weights=(
            PortfolioWeight(instrument="A005930", weight=0.6),
            PortfolioWeight(instrument="A000660", weight=-0.4),
        ),
        requested_budget=1.0,
        realized_gross=1.0,
        realized_net=0.2,
        cash_residual=0.0,
        diagnostics=("public constraint fixture",),
    )
    imported = project.artifacts.import_model_bytes(
        logical_identity=f"portfolio:{identity}",
        contract=PORTFOLIO_RESULT_CONTRACT,
        producer_id="test.public-portfolio",
        payload_bytes=source.model_dump_json().encode(),
    )
    assert imported.status is OutcomeStatus.COMPLETE
    return imported.result.artifact_id


def register_benchmark(
    project: QlibxProject,
    dataset_id: str,
    *,
    available_at: str = "2024-01-03T09:00:00+09:00",
    instruments: tuple[tuple[str, float], ...] = (
        ("A000660", 0.0674),
        ("A005930", 0.3172),
    ),
) -> None:
    source = project.root / f"{dataset_id}.csv"
    rows = "".join(
        f"2024-01-02T09:00:00+09:00,{available_at},{instrument},{weight}\n"
        for instrument, weight in instruments
    )
    source.write_text(
        "observation_time,available_at,ticker,benchmark_weight\n" + rows,
        encoding="utf-8",
    )
    outcome = project.register_dataset(
        DatasetRegistration(
            dataset_id=dataset_id,
            source=source.name,
            source_format=SourceFormat.CSV,
            instrument_field="ticker",
            observation_time_field="observation_time",
            available_at=AvailableAtField(field="available_at"),
            logical_key=("observation_time", "available_at", "ticker"),
            semantic_bindings={"benchmark_weight": "benchmark_weight"},
            source_provenance="bounded public constraint fixture",
        )
    )
    assert outcome.status is OutcomeStatus.COMPLETE


def register_daily_market(project: QlibxProject) -> None:
    source = project.root / "monitoring-market.csv"
    source.write_text(
        "observation_time,available_at,ticker,close\n"
        "2024-01-02T09:00:00+09:00,2024-01-02T15:30:00+09:00,A000660,100000\n"
        "2024-01-02T09:00:00+09:00,2024-01-02T15:30:00+09:00,A005930,77000\n"
        "2024-01-03T09:00:00+09:00,2024-01-03T15:30:00+09:00,A000660,101000\n"
        "2024-01-03T09:00:00+09:00,2024-01-03T15:30:00+09:00,A005930,78000\n",
        encoding="utf-8",
    )
    outcome = project.register_dataset(
        DatasetRegistration(
            dataset_id="monitoring-market",
            source=source.name,
            source_format=SourceFormat.CSV,
            instrument_field="ticker",
            observation_time_field="observation_time",
            available_at=AvailableAtField(field="available_at"),
            logical_key=("observation_time", "available_at", "ticker"),
            semantic_bindings={
                "execution_price": "close",
                "valuation_price": "close",
            },
            source_provenance="bounded public monitoring facade fixture",
        )
    )
    assert outcome.status is OutcomeStatus.COMPLETE


def monitoring_daily_spec() -> DailySimulationSpec:
    start = datetime(2020, 1, 1, tzinfo=KST)
    return DailySimulationSpec(
        run_id="public-monitoring-seed-run",
        strategy_fingerprint="public-monitoring-seed-v1",
        account=DailyAccountSeed(
            account_id="public-monitoring-account",
            base_currency="KRW",
            initial_cash=1_000_000,
        ),
        instruments=tuple(
            StockInstrument(
                instrument_id=instrument,
                exchange_id="XKRX",
                currency="KRW",
                lot_size=1,
            )
            for instrument in ("A000660", "A005930")
        ),
        exchange=KrxExchangeConfig(
            schedule_version="public-monitoring-cost-v1",
            cost_rules=tuple(
                CostRule(
                    rule_id=f"stock-{side.value.lower()}",
                    product_type="stock",
                    side=side,
                    effective_from=start,
                    rate=0,
                    minimum_cost=0,
                )
                for side in Side
            ),
        ),
        market=DailyMarketBinding(market_dataset_id="monitoring-market"),
        session_closes=(
            datetime(2024, 1, 2, 15, 30, tzinfo=KST),
            evaluation_time(),
        ),
    )


def policy(dataset_id: str | None) -> MvpConstraintPolicy:
    return MvpConstraintPolicy(
        policy_id="mvp-no-short-cap-v1",
        benchmark_dataset_id=dataset_id,
    )


def lots() -> tuple[ExecutionLotInput, ...]:
    return (
        ExecutionLotInput(
            instrument="A005930",
            price=77_000,
            lot_size=1,
            current_quantity=12,
        ),
        ExecutionLotInput(
            instrument="A000660",
            price=136_800,
            lot_size=1,
            current_quantity=0,
        ),
    )


def adjustment_spec(
    source_artifact_id: str,
    selected_policy: MvpConstraintPolicy,
    *,
    invocation_id: str = "public-constraint-adjustment",
    selected_lots: tuple[ExecutionLotInput, ...] | None = None,
) -> ConstraintAdjustmentSpec:
    return ConstraintAdjustmentSpec(
        invocation_id=invocation_id,
        source_portfolio_artifact_id=source_artifact_id,
        evaluation_time=evaluation_time(),
        policy=selected_policy,
        account_state_identity="public-account:v0",
        capital=970_000,
        lots=lots() if selected_lots is None else selected_lots,
    )


def test_public_constraint_policy_and_fingerprint_are_bounded() -> None:
    selected_policy = policy("benchmark-a")
    first = adjustment_spec("artifact-source", selected_policy)
    reordered = adjustment_spec(
        "artifact-source",
        selected_policy,
        selected_lots=tuple(reversed(lots())),
    )
    changed = adjustment_spec(
        "artifact-source",
        selected_policy,
        selected_lots=(lots()[0].model_copy(update={"price": 77_001}), lots()[1]),
    )

    assert first.frozen_config_fingerprint() == reordered.frozen_config_fingerprint()
    assert first.to_request().lots == reordered.to_request().lots
    assert first.frozen_config_fingerprint() != changed.frozen_config_fingerprint()

    with pytest.raises(ValidationError, match=r"0\.1"):
        MvpConstraintPolicy(
            policy_id="unsupported-floor",
            benchmark_dataset_id="benchmark-a",
            single_name_floor=0.2,  # type: ignore[arg-type]
        )
    with pytest.raises(ValidationError, match="timezone-aware"):
        ConstraintAdjustmentSpec(
            invocation_id="naive-time",
            source_portfolio_artifact_id="artifact-source",
            evaluation_time=datetime(2024, 1, 3, 15, 30),
            policy=selected_policy,
            account_state_identity="public-account:v0",
            capital=970_000,
            lots=lots(),
        )
    with pytest.raises(ValidationError, match="must be unique"):
        adjustment_spec(
            "artifact-source",
            selected_policy,
            selected_lots=(lots()[0], lots()[0]),
        )


def test_public_constraint_facade_adjusts_then_independently_denies_residual(
    tmp_path: Path,
) -> None:
    project = create_project(tmp_path, "public-constraint")
    register_benchmark(project, "benchmark-a")
    source = import_source_portfolio(project)
    spec = adjustment_spec(source, policy("benchmark-a"))

    adjustment = project.adjust_constraints(spec)
    repeated = project.adjust_constraints(spec)
    assert adjustment.status is repeated.status is OutcomeStatus.COMPLETE
    assert adjustment.diagnostics[0].artifact_id == repeated.diagnostics[0].artifact_id
    assert adjustment.result.adjusted_weights == (
        PortfolioWeight(instrument="A005930", weight=0.31752577319587627),
        PortfolioWeight(instrument="A000660", weight=0.0),
    )
    assert adjustment.result.items[0].reasons == (
        "single_name_cap",
        "order_delta_lot_floor",
    )
    assert adjustment.result.items[1].reasons == ("no_short",)
    assert adjustment.result.unresolved_excess == pytest.approx(0.00032577319587628883)

    validation_spec = ConstraintValidationSpec(
        invocation_id="public-constraint-validation",
        adjustment_artifact_id=adjustment.diagnostics[0].artifact_id,
        evaluation_time=evaluation_time(),
        policy=policy("benchmark-a"),
    )
    validation = project.validate_constraints(validation_spec)
    repeated_validation = project.validate_constraints(validation_spec)
    assert validation.status is repeated_validation.status is OutcomeStatus.COMPLETE
    assert validation.diagnostics[0].artifact_id == repeated_validation.diagnostics[0].artifact_id
    assert validation.result.compliant is False
    failed = tuple(item for item in validation.result.findings if not item.passed)
    assert [(item.instrument, item.metric) for item in failed] == [("A005930", "single_name_cap")]
    assert adjustment.result.accesses == validation.result.accesses
    assert {edge.dependency_kind for edge in adjustment.diagnostics[0].dependencies} == {
        "artifact",
        "config",
        "dataset",
        "state",
    }


def test_constraint_free_strategy_does_not_require_benchmark(tmp_path: Path) -> None:
    project = create_project(tmp_path, "constraint-free")

    outcome = project.invoke(
        ConstraintFreeStrategy(),
        StrategyInvocation(
            invocation_id="constraint-free-strategy",
            evaluation_time=evaluation_time(),
            config_fingerprint="constraint-free-v1",
        ),
    )

    assert outcome.status is OutcomeStatus.COMPLETE
    assert [item.artifact_type for item in project.artifacts.list_envelopes()] == [
        "strategy_result"
    ]


def test_public_constraint_missing_and_ambiguous_binding_fail_before_mutation(
    tmp_path: Path,
) -> None:
    missing_project = create_project(tmp_path, "missing-benchmark")
    missing_source = import_source_portfolio(missing_project, "missing")
    missing = missing_project.adjust_constraints(
        adjustment_spec(missing_source, policy("missing-benchmark"), invocation_id="missing")
    )
    assert missing.status is OutcomeStatus.FAILED
    assert missing.errors[0].error_code == "REQUIREMENT_NOT_RESOLVED"
    assert missing.errors[0].commit_status is CommitStatus.NONE

    ambiguous_project = create_project(tmp_path, "ambiguous-benchmark")
    register_benchmark(ambiguous_project, "benchmark-a")
    register_benchmark(ambiguous_project, "benchmark-b")
    ambiguous_source = import_source_portfolio(ambiguous_project, "ambiguous")
    ambiguous = ambiguous_project.adjust_constraints(
        adjustment_spec(ambiguous_source, policy(None), invocation_id="ambiguous")
    )
    assert ambiguous.status is OutcomeStatus.FAILED
    assert ambiguous.errors[0].error_code == "REQUIREMENT_AMBIGUOUS"
    assert ambiguous.errors[0].commit_status is CommitStatus.NONE

    for selected in (missing_project, ambiguous_project):
        types = {
            item.artifact_type for item in selected.artifacts.list_envelopes(include_failure=True)
        }
        assert types == {"operation_error", "portfolio_construction_result"}


def test_public_constraint_hidden_incomplete_and_missing_lot_fail_with_evidence(
    tmp_path: Path,
) -> None:
    hidden_project = create_project(tmp_path, "hidden-benchmark")
    register_benchmark(
        hidden_project,
        "benchmark-hidden",
        available_at="2024-01-04T09:00:00+09:00",
    )
    hidden_source = import_source_portfolio(hidden_project, "hidden")
    hidden = hidden_project.adjust_constraints(
        adjustment_spec(hidden_source, policy("benchmark-hidden"), invocation_id="hidden")
    )
    assert hidden.status is OutcomeStatus.FAILED
    assert hidden.errors[0].error_code == "CONSTRAINT_BENCHMARK_COVERAGE_MISSING"
    assert hidden.errors[0].commit_status is CommitStatus.NONE

    incomplete_project = create_project(tmp_path, "incomplete-benchmark")
    register_benchmark(
        incomplete_project,
        "benchmark-incomplete",
        instruments=(("A005930", 0.3172),),
    )
    incomplete_source = import_source_portfolio(incomplete_project, "incomplete")
    incomplete = incomplete_project.adjust_constraints(
        adjustment_spec(
            incomplete_source,
            policy("benchmark-incomplete"),
            invocation_id="incomplete",
        )
    )
    assert incomplete.status is OutcomeStatus.FAILED
    assert incomplete.errors[0].error_code == "CONSTRAINT_BENCHMARK_COVERAGE_MISSING"
    assert incomplete.errors[0].context["instruments"] == ["A000660"]

    lot_project = create_project(tmp_path, "missing-lot")
    register_benchmark(lot_project, "benchmark-lot")
    lot_source = import_source_portfolio(lot_project, "lot")
    missing_lot = lot_project.adjust_constraints(
        adjustment_spec(
            lot_source,
            policy("benchmark-lot"),
            invocation_id="missing-lot",
            selected_lots=(lots()[0],),
        )
    )
    assert missing_lot.status is OutcomeStatus.FAILED
    assert missing_lot.errors[0].error_code == "CONSTRAINT_EXECUTION_LOT_MISSING"
    assert missing_lot.errors[0].context["instruments"] == ["A000660"]


def test_public_validation_rejects_changed_benchmark_identity(tmp_path: Path) -> None:
    project = create_project(tmp_path, "changed-benchmark")
    register_benchmark(project, "benchmark-a")
    register_benchmark(project, "benchmark-b")
    source = import_source_portfolio(project, "changed")
    adjustment = project.adjust_constraints(
        adjustment_spec(source, policy("benchmark-a"), invocation_id="changed-adjustment")
    )
    assert adjustment.status is OutcomeStatus.COMPLETE

    validation = project.validate_constraints(
        ConstraintValidationSpec(
            invocation_id="changed-validation",
            adjustment_artifact_id=adjustment.diagnostics[0].artifact_id,
            evaluation_time=evaluation_time(),
            policy=policy("benchmark-b"),
        )
    )

    assert validation.status is OutcomeStatus.FAILED
    assert validation.errors[0].error_code == "CONSTRAINT_BENCHMARK_IDENTITY_MISMATCH"
    assert validation.errors[0].commit_status is CommitStatus.NONE


def test_constraint_flow_distinguishes_data_and_compute_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(tmp_path, "failure-boundaries")
    register_benchmark(project, "benchmark-a")
    source = import_source_portfolio(project, "failure-boundaries")
    selected_policy = policy("benchmark-a")

    def fail_compute(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("synthetic compute defect")

    with monkeypatch.context() as patch:
        patch.setattr(
            "qlibx.flow.constraints.adjust_single_name_caps",
            fail_compute,
        )
        compute_failure = project.adjust_constraints(
            adjustment_spec(
                source,
                selected_policy,
                invocation_id="constraint-compute-failure",
            )
        )

    def fail_data(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("synthetic data defect")

    with monkeypatch.context() as patch:
        patch.setattr(
            "qlibx.flow.constraints.ConstraintFlow._benchmark",
            fail_data,
        )
        data_failure = project.adjust_constraints(
            adjustment_spec(
                source,
                selected_policy,
                invocation_id="constraint-data-failure",
            )
        )

    assert compute_failure.status is OutcomeStatus.FAILED
    assert compute_failure.errors[0].error_code == "CONSTRAINT_COMPUTE_FAILED"
    assert compute_failure.errors[0].stage_path == "constraint.adjust.compute"
    assert compute_failure.errors[0].commit_status is CommitStatus.NONE
    assert data_failure.status is OutcomeStatus.FAILED
    assert data_failure.errors[0].error_code == "CONSTRAINT_DATA_READ_FAILED"
    assert data_failure.errors[0].stage_path == "constraint.adjust.data"
    assert data_failure.errors[0].commit_status is CommitStatus.NONE


def test_daily_execution_applies_constraint_preparation_before_exchange(
    tmp_path: Path,
) -> None:
    project = create_project(tmp_path, "daily-preparation")
    register_daily_market(project)
    register_benchmark(project, "monitoring-benchmark")
    selected_spec = monitoring_daily_spec().model_copy(
        update={"constraint_policy": policy("monitoring-benchmark")}
    )

    outcome = project.run_daily(MonitoringSeedStrategy(), selected_spec)

    assert outcome.status is OutcomeStatus.COMPLETE
    assert len(outcome.result.executions) == 1
    execution = outcome.result.executions[0]
    loaded = project.artifacts.load_model(
        execution.preparation_artifact_id,
        KRX_PREPARATION_CONTRACT,
    )
    assert loaded.status is OutcomeStatus.COMPLETE
    preparation = loaded.result.payload
    assert preparation.constraint_adjustment is not None
    assert preparation.constraint_validation is not None
    assert preparation.compliant is True
    assert preparation.adjusted_weights != preparation.constructed_weights


def test_daily_constraint_missing_benchmark_does_not_call_exchange(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(tmp_path, "daily-preparation-missing")
    register_daily_market(project)
    selected_spec = monitoring_daily_spec().model_copy(
        update={"constraint_policy": policy("missing-benchmark")}
    )
    called = False

    def unexpected_exchange_call(*_args: object, **_kwargs: object) -> object:
        nonlocal called
        called = True
        raise AssertionError("exchange must not be called after preparation input failure")

    monkeypatch.setattr(
        "qlibx.execution.krx.KrxExchange.match_batch",
        unexpected_exchange_call,
    )
    outcome = project.run_daily(MonitoringSeedStrategy(), selected_spec)

    assert outcome.status is OutcomeStatus.FAILED
    assert called is False
    assert outcome.errors[0].error_code == "REQUIREMENT_NOT_RESOLVED"
    assert not any(
        item.artifact_type in {"krx_execution_preparation", "execution_result"}
        for item in project.artifacts.list_envelopes(include_failure=True)
    )


def test_public_constraint_monitoring_restores_checkpoint_and_is_deterministic(
    tmp_path: Path,
) -> None:
    project = create_project(tmp_path, "public-monitoring")
    register_daily_market(project)
    register_benchmark(project, "monitoring-benchmark")
    daily = project.run_daily(MonitoringSeedStrategy(), monitoring_daily_spec())
    assert daily.status is OutcomeStatus.COMPLETE
    checkpoint_artifact = next(
        artifact
        for artifact in daily.result.artifacts
        if artifact.artifact_type == "simulation_checkpoint"
    )
    monitoring_spec = ConstraintMonitoringSpec(
        invocation_id="public-constraint-monitoring",
        checkpoint_artifact_id=checkpoint_artifact.artifact_id,
        evaluation_time=evaluation_time(),
        policy=policy("monitoring-benchmark"),
    )

    first = project.monitor_constraints(monitoring_spec)
    repeated = project.monitor_constraints(monitoring_spec)

    assert first.status is repeated.status is OutcomeStatus.COMPLETE
    assert first.result == repeated.result
    assert first.diagnostics[0].artifact_type == "constraint_monitoring_result"
    assert first.diagnostics[0].artifact_id == repeated.diagnostics[0].artifact_id
    held = first.result.account_state.holdings[0]
    assert held.marked_at == monitoring_spec.evaluation_time
    assert first.result.account_state.valuation_status == "COMPLETE"

    stale = project.monitor_constraints(
        monitoring_spec.model_copy(
            update={
                "invocation_id": "public-constraint-monitoring-stale",
                "evaluation_time": datetime(2024, 1, 5, 15, 30, tzinfo=KST),
            }
        )
    )
    assert stale.status is OutcomeStatus.FAILED
    assert stale.errors[0].error_code == "ACCOUNT_VALUATION_STALE"

    checkpoint = daily.result.checkpoint
    invalid_account = replace(
        checkpoint.account_checkpoint,
        version=checkpoint.account_checkpoint.version + 1,
    )
    invalid_checkpoint = checkpoint.model_copy(
        update={
            "run_id": "invalid-account-checkpoint",
            "account_checkpoint": invalid_account,
        }
    )
    imported = project.artifacts.import_model_bytes(
        logical_identity="simulation-checkpoint:invalid-account-checkpoint",
        contract=SIMULATION_CHECKPOINT_CONTRACT,
        producer_id="test.invalid-account-checkpoint",
        payload_bytes=invalid_checkpoint.model_dump_json().encode(),
    )
    assert imported.status is OutcomeStatus.COMPLETE
    invalid = project.monitor_constraints(
        monitoring_spec.model_copy(
            update={
                "invocation_id": "public-constraint-monitoring-invalid",
                "checkpoint_artifact_id": imported.result.artifact_id,
            }
        )
    )
    assert invalid.status is OutcomeStatus.FAILED
    assert invalid.errors[0].error_code == "MONITORING_ACCOUNT_CHECKPOINT_INVALID"
    assert invalid.errors[0].stage_path == "monitoring.constraint.checkpoint"
    assert invalid.errors[0].commit_status is CommitStatus.NONE
