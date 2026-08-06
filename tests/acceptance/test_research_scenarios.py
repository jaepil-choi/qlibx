from datetime import datetime

import duckdb

from qlibx import OperationOutcome, OutcomeStatus
from qlibx.account import (
    Account,
    FillBatch,
    Mark,
    MarkBatch,
    StrategyMemoryStore,
)
from qlibx.execution import Fill, Side
from qlibx.flow import (
    STORED_SIGNAL_CONTRACT,
    CompositionFlow,
    ConstraintFlow,
    DailyExecutionFlow,
    DailyExecutionProfile,
    DailyRunRequest,
    EnsembleDefinition,
    EnsembleMemberSpec,
    FrozenDecision,
    MonitoringFlow,
    PortfolioConstructionFlow,
    StoredSignalEntry,
    StoredSignalResult,
    StoredSignalWeighting,
)
from qlibx.kernel import BacktestClock
from qlibx.operations import BudgetMode, StrategyInvocation
from qlibx.portfolio import (
    ConstraintAdjustmentRequest,
    ConstraintDeclaration,
    ConstraintMonitoringRequest,
    ConstraintValidationRequest,
    ConstructionProfile,
    ExecutionLotInput,
    PortfolioConstructionRequest,
)
from tests.acceptance.real_dw_support import (
    KST,
    RealDwProject,
    StoredWinnerStrategy,
    WeakRealDwStrategy,
    close_at,
    configured_exchange,
    initial_account,
    run_real_daily_flow,
)


def _import_real_dw_signal(real_dw_case: RealDwProject) -> OperationOutcome:
    rows = duckdb.connect().sql(
        f"""
        SELECT ticker, decision_return
        FROM read_parquet('{real_dw_case.source.as_posix()}')
        WHERE CAST(date AS DATE) = DATE '2024-01-02'
        ORDER BY ticker
        """
    ).fetchall()
    signal = StoredSignalResult(
        signal_semantics="real_dw_close_to_base_return",
        observation_time=close_at(2024, 1, 2),
        entries=tuple(
            StoredSignalEntry(instrument=ticker, value=value)
            for ticker, value in rows
        ),
    )
    return real_dw_case.project.artifacts.import_model_bytes(
        logical_identity="external-signal:real-dw-2024-01-02",
        contract=STORED_SIGNAL_CONTRACT,
        producer_id="external.real-dw-characteristic",
        payload_bytes=signal.model_dump_json().encode("utf-8"),
    )


def _build_real_dw_long_only_portfolio(
    real_dw_case: RealDwProject,
) -> OperationOutcome:
    imported = _import_real_dw_signal(real_dw_case)
    alpha = CompositionFlow(
        registry=real_dw_case.project.registry_snapshot(),
        artifacts=real_dw_case.project.artifacts,
    ).invoke_stored_signal_strategy(
        artifact_id=imported.result.artifact_id,
        strategy_id="acceptance.constraint-source-alpha",
        weighting=StoredSignalWeighting.LONG_SHORT_EXTREMES,
        invocation=StrategyInvocation(
            invocation_id="constraint-source-alpha-real-dw",
            evaluation_time=close_at(2024, 1, 2),
            config_fingerprint="constraint-source-alpha-v1",
        ),
    )
    return PortfolioConstructionFlow(artifacts=real_dw_case.project.artifacts).construct(
        PortfolioConstructionRequest(
            invocation_id="constraint-source-portfolio-real-dw",
            source_artifact_id=alpha.result.artifact.artifact_id,
            evaluation_time=close_at(2024, 1, 2),
            config_fingerprint="constraint-source-portfolio-v1",
            profile=ConstructionProfile.EQUITY_LONG_ONLY,
            requested_budget=1.0,
        )
    )
def test_uc_alpha_budget_001_preserves_real_dw_flexible_residual(
    real_dw_case: RealDwProject,
) -> None:
    strategy = WeakRealDwStrategy()
    member = real_dw_case.project.invoke(
        strategy,
        StrategyInvocation(
            invocation_id="weak-real-dw-member",
            evaluation_time=close_at(2024, 1, 2),
            config_fingerprint="weak-real-dw-v1",
        ),
    )
    composition = CompositionFlow(
        registry=real_dw_case.project.registry_snapshot(),
        artifacts=real_dw_case.project.artifacts,
    )
    fixed_consumer = composition.invoke_ensemble(
        EnsembleDefinition(
            strategy_id="acceptance.weak-fixed-consumer",
            members=(
                EnsembleMemberSpec(
                    artifact_id=member.result.artifact.artifact_id,
                    allocation=1.0,
                ),
            ),
            budget_mode=BudgetMode.FIXED,
            target_gross=1.0,
        ),
        StrategyInvocation(
            invocation_id="weak-real-dw-fixed-consumer",
            evaluation_time=close_at(2024, 1, 2),
            config_fingerprint="weak-fixed-consumer-v1",
        ),
    )

    assert member.status is OutcomeStatus.COMPLETE
    assert member.result.result.invested_gross == 0.4
    assert member.result.result.residual_budget == 0.6
    assert fixed_consumer.status is OutcomeStatus.FAILED
    assert fixed_consumer.errors[0].error_code == "ENSEMBLE_FIXED_BUDGET_INCOMPATIBLE"
    assert strategy.runs == 1


def test_uc_signal_002_and_uc_artifact_001_reuse_real_dw_stored_signal(
    real_dw_case: RealDwProject,
) -> None:
    imported = _import_real_dw_signal(real_dw_case)
    composition = CompositionFlow(
        registry=real_dw_case.project.registry_snapshot(),
        artifacts=real_dw_case.project.artifacts,
    )
    long_short = composition.invoke_stored_signal_strategy(
        artifact_id=imported.result.artifact_id,
        strategy_id="acceptance.real-dw-long-short",
        weighting=StoredSignalWeighting.LONG_SHORT_EXTREMES,
        invocation=StrategyInvocation(
            invocation_id="stored-signal-long-short-real-dw",
            evaluation_time=close_at(2024, 1, 2),
            config_fingerprint="stored-signal-long-short-v1",
        ),
    )
    long_only = composition.invoke_stored_signal_strategy(
        artifact_id=imported.result.artifact_id,
        strategy_id="acceptance.real-dw-long-only",
        weighting=StoredSignalWeighting.LONG_ONLY_MAX,
        invocation=StrategyInvocation(
            invocation_id="stored-signal-long-only-real-dw",
            evaluation_time=close_at(2024, 1, 2),
            config_fingerprint="stored-signal-long-only-v1",
        ),
    )

    assert imported.status is OutcomeStatus.COMPLETE
    assert {item.instrument: item.weight for item in long_short.result.result.weights} == {
        "A000660": -0.5,
        "A005930": 0.5,
    }
    assert {item.instrument: item.weight for item in long_only.result.result.weights} == {
        "A005930": 1.0
    }
    assert all(
        any(
            edge.dependency_id == imported.result.artifact_id
            and edge.consumer_role == "stored_signal"
            for edge in result.result.artifact.dependencies
        )
        for result in (long_short, long_only)
    )


def test_uc_portfolio_001_constructs_two_portfolios_from_one_real_dw_alpha(
    real_dw_case: RealDwProject,
) -> None:
    imported = _import_real_dw_signal(real_dw_case)
    composition = CompositionFlow(
        registry=real_dw_case.project.registry_snapshot(),
        artifacts=real_dw_case.project.artifacts,
    )
    alpha = composition.invoke_stored_signal_strategy(
        artifact_id=imported.result.artifact_id,
        strategy_id="acceptance.real-dw-signed-alpha",
        weighting=StoredSignalWeighting.LONG_SHORT_EXTREMES,
        invocation=StrategyInvocation(
            invocation_id="portfolio-source-real-dw",
            evaluation_time=close_at(2024, 1, 2),
            config_fingerprint="portfolio-source-v1",
        ),
    )
    original_json = alpha.result.result.model_dump_json()
    construction = PortfolioConstructionFlow(artifacts=real_dw_case.project.artifacts)
    signed = construction.construct(
        PortfolioConstructionRequest(
            invocation_id="portfolio-hypothetical-signed-real-dw",
            source_artifact_id=alpha.result.artifact.artifact_id,
            evaluation_time=close_at(2024, 1, 2),
            config_fingerprint="hypothetical-signed-v1",
            profile=ConstructionProfile.HYPOTHETICAL_SIGNED,
            requested_budget=1.0,
        )
    )
    long_only = construction.construct(
        PortfolioConstructionRequest(
            invocation_id="portfolio-equity-long-only-real-dw",
            source_artifact_id=alpha.result.artifact.artifact_id,
            evaluation_time=close_at(2024, 1, 2),
            config_fingerprint="equity-long-only-v1",
            profile=ConstructionProfile.EQUITY_LONG_ONLY,
            requested_budget=1.0,
        )
    )

    assert signed.status is long_only.status is OutcomeStatus.COMPLETE
    assert {item.instrument: item.weight for item in signed.result.target_weights} == {
        "A000660": -0.5,
        "A005930": 0.5,
    }
    assert {item.instrument: item.weight for item in long_only.result.target_weights} == {
        "A005930": 1.0
    }
    assert signed.result.realized_gross == long_only.result.realized_gross == 1.0
    assert signed.result.realized_net == 0.0
    assert long_only.result.realized_net == 1.0
    assert alpha.result.result.model_dump_json() == original_json
    assert all(
        outcome.diagnostics[0].dependencies[0].dependency_id
        == alpha.result.artifact.artifact_id
        for outcome in (signed, long_only)
    )


def test_uc_constraint_002_and_uc_constraint_adjust_001_use_confirmed_k200_cutoff(
    real_dw_case: RealDwProject,
    real_dw_constraint_case: RealDwProject,
) -> None:
    declaration = ConstraintDeclaration(
        declaration_id="mvp-no-short-single-name-cap-v1",
        benchmark_weight_role="benchmark_weight",
        single_name_floor=0.10,
    )
    unconstrained_portfolio = _build_real_dw_long_only_portfolio(real_dw_case)
    missing = ConstraintFlow(
        registry=real_dw_case.project.registry_snapshot(),
        artifacts=real_dw_case.project.artifacts,
    ).adjust(
        declaration,
        ConstraintAdjustmentRequest(
            invocation_id="constraint-missing-k200-binding",
            source_portfolio_artifact_id=unconstrained_portfolio.diagnostics[0].artifact_id,
            evaluation_time=close_at(2024, 1, 3),
            config_fingerprint="constraint-missing-v1",
            account_state_identity="account:missing-binding:v0",
            capital=970_000.0,
            lots=(
                ExecutionLotInput(
                    instrument="A005930",
                    price=77_000.0,
                    lot_size=1.0,
                    current_quantity=12.0,
                ),
            ),
        ),
    )

    portfolio = _build_real_dw_long_only_portfolio(real_dw_constraint_case)
    flow = ConstraintFlow(
        registry=real_dw_constraint_case.project.registry_snapshot(),
        artifacts=real_dw_constraint_case.project.artifacts,
    )
    hidden = flow.adjust(
        declaration,
        ConstraintAdjustmentRequest(
            invocation_id="constraint-k200-before-confirmed-cutoff",
            source_portfolio_artifact_id=portfolio.diagnostics[0].artifact_id,
            evaluation_time=close_at(2024, 1, 2),
            config_fingerprint="constraint-hidden-v1",
            account_state_identity="account:hidden-cutoff:v0",
            capital=970_000.0,
            lots=(
                ExecutionLotInput(
                    instrument="A005930",
                    price=77_000.0,
                    lot_size=1.0,
                    current_quantity=12.0,
                ),
            ),
        ),
    )
    adjustment = flow.adjust(
        declaration,
        ConstraintAdjustmentRequest(
            invocation_id="constraint-k200-after-confirmed-cutoff",
            source_portfolio_artifact_id=portfolio.diagnostics[0].artifact_id,
            evaluation_time=close_at(2024, 1, 3),
            config_fingerprint="constraint-adjust-v1",
            account_state_identity="account:pretrade:v2",
            capital=970_000.0,
            lots=(
                ExecutionLotInput(
                    instrument="A005930",
                    price=77_000.0,
                    lot_size=1.0,
                    current_quantity=12.0,
                ),
            ),
        ),
    )
    validation = flow.validate(
        declaration,
        ConstraintValidationRequest(
            invocation_id="constraint-independent-validation",
            adjustment_artifact_id=adjustment.diagnostics[0].artifact_id,
            evaluation_time=close_at(2024, 1, 3),
            config_fingerprint="constraint-validate-v1",
        ),
    )

    assert missing.status is OutcomeStatus.FAILED
    assert missing.errors[0].error_code == "REQUIREMENT_NOT_RESOLVED"
    assert hidden.status is OutcomeStatus.FAILED
    assert hidden.errors[0].error_code == "CONSTRAINT_BENCHMARK_COVERAGE_MISSING"
    assert adjustment.status is validation.status is OutcomeStatus.COMPLETE
    item = adjustment.result.items[0]
    assert item.instrument == "A005930"
    assert item.benchmark_weight == 0.3172
    assert item.cap == 0.3172
    assert item.continuous_weight == 0.3172
    assert item.requested_delta_quantity < -8.0
    assert item.rounded_delta_quantity == -8.0
    assert item.projected_quantity == 4.0
    assert item.adjusted_weight == 4 * 77_000 / 970_000
    assert item.unresolved_excess == item.adjusted_weight - item.cap
    assert adjustment.result.unresolved_excess > 0
    assert any(
        edge.dependency_id == "account:pretrade:v2"
        and edge.consumer_role == "actual_pretrade_state"
        for edge in adjustment.diagnostics[0].dependencies
    )
    assert validation.result.eligible is False
    cap_finding = next(
        finding for finding in validation.result.findings
        if finding.metric == "single_name_cap"
    )
    assert cap_finding.passed is False
    assert cap_finding.excess == item.unresolved_excess
    assert adjustment.result.accesses[0].max_available_at.astimezone(KST) == datetime(
        2024, 1, 3, 9, 0, tzinfo=KST
    )


def test_uc_exec_003_monitors_real_no_trade_price_drift_without_mutation(
    real_dw_case: RealDwProject,
    real_dw_constraint_case: RealDwProject,
) -> None:
    prices = duckdb.connect().sql(
        f"""
        SELECT CAST(date AS DATE), execution_price
        FROM read_parquet('{real_dw_constraint_case.source.as_posix()}')
        WHERE ticker = 'A000660'
          AND CAST(date AS DATE) IN (DATE '2024-01-04', DATE '2024-01-05')
        ORDER BY date
        """
    ).fetchall()
    assert len(prices) == 2
    initial_price = float(prices[0][1])
    drift_price = float(prices[1][1])
    assert initial_price == 136_400.0
    assert drift_price == 137_500.0

    cash_after_fill = 9 * (initial_price + drift_price) / 2
    account = Account(
        account_id="monitoring-no-trade-account",
        base_currency="KRW",
        initial_cash=cash_after_fill + initial_price,
        instrument_ids=frozenset({"A000660"}),
    )
    account.commit(
        FillBatch(
            account_id=account.snapshot().account_id,
            event_id="monitoring-seed-fill",
            fills=(
                Fill(
                    fill_id="monitoring-seed-fill-1",
                    instrument_id="A000660",
                    side=Side.BUY,
                    requested_quantity=1,
                    dealt_quantity=1,
                    price=initial_price,
                    trade_value=initial_price,
                    total_cost=0,
                    cost_rule_id="real-dw-seed",
                    schedule_version="real-dw-2024",
                ),
            ),
        ),
        expected_version=0,
    )
    before_drift = account.commit(
        MarkBatch(
            account_id=account.snapshot().account_id,
            event_id="monitoring-mark-before-drift",
            marks=(Mark("A000660", initial_price),),
        ),
        expected_version=1,
    ).snapshot
    after_drift = account.commit(
        MarkBatch(
            account_id=account.snapshot().account_id,
            event_id="monitoring-mark-after-drift",
            marks=(Mark("A000660", drift_price),),
        ),
        expected_version=2,
    ).snapshot
    assert initial_price / before_drift.nav < 0.10
    assert drift_price / after_drift.nav > 0.10

    declaration = ConstraintDeclaration(
        declaration_id="mvp-no-short-single-name-cap-v1",
        benchmark_weight_role="benchmark_weight",
        single_name_floor=0.10,
    )
    memory = StrategyMemoryStore()
    account_before_monitor = account.checkpoint()
    memory_before_monitor = memory.checkpoint()
    missing = MonitoringFlow(
        clock=BacktestClock(close_at(2024, 1, 5)),
        registry=real_dw_case.project.registry_snapshot(),
        artifacts=real_dw_case.project.artifacts,
        account=account,
    ).run(
        declaration,
        ConstraintMonitoringRequest(
            invocation_id="monitoring-missing-k200-binding",
            config_fingerprint="monitoring-single-name-v1",
        ),
    )
    flow = MonitoringFlow(
        clock=BacktestClock(close_at(2024, 1, 5)),
        registry=real_dw_constraint_case.project.registry_snapshot(),
        artifacts=real_dw_constraint_case.project.artifacts,
        account=account,
    )
    request = ConstraintMonitoringRequest(
        invocation_id="monitoring-real-no-trade-drift",
        config_fingerprint="monitoring-single-name-v1",
    )
    first = flow.run(declaration, request)
    repeated = flow.run(declaration, request)

    assert missing.status is OutcomeStatus.FAILED
    assert missing.errors[0].error_code == "REQUIREMENT_NOT_RESOLVED"
    assert first.status is repeated.status is OutcomeStatus.COMPLETE
    assert first.result == repeated.result
    assert first.diagnostics[0].artifact_id == repeated.diagnostics[0].artifact_id
    assert first.diagnostics[0].artifact_type == "constraint_monitoring_result"
    assert first.result.account_state.version == after_drift.version
    assert first.result.compliant is False
    cap_finding = next(
        finding
        for finding in first.result.findings
        if finding.instrument == "A000660"
        and finding.metric == "single_name_cap"
    )
    assert cap_finding.measured == drift_price / after_drift.nav
    assert cap_finding.bound == 0.10
    assert cap_finding.excess > 0
    assert cap_finding.passed is False
    assert first.result.accesses[0].max_available_at.astimezone(KST) == datetime(
        2024, 1, 3, 9, 0, tzinfo=KST
    )
    assert any(
        edge.consumer_role == "committed_account_snapshot"
        and edge.dependency_id
        == f"{after_drift.account_id}:v{after_drift.version}:cursor{after_drift.feedback_cursor}"
        for edge in first.diagnostics[0].dependencies
    )
    assert account.checkpoint() == account_before_monitor
    assert memory.checkpoint() == memory_before_monitor


def test_uc_ensemble_001_records_crossing_budget_and_member_lineage(
    real_dw_case: RealDwProject,
) -> None:
    winner = StoredWinnerStrategy("acceptance.stored-winner", 1.0)
    opposite = StoredWinnerStrategy("acceptance.stored-opposite", -1.0)
    winner_run = real_dw_case.project.invoke(
        winner,
        StrategyInvocation(
            invocation_id="stored-winner-real-dw",
            evaluation_time=close_at(2024, 1, 2),
            config_fingerprint="stored-winner-v1",
        ),
    )
    opposite_run = real_dw_case.project.invoke(
        opposite,
        StrategyInvocation(
            invocation_id="stored-opposite-real-dw",
            evaluation_time=close_at(2024, 1, 2),
            config_fingerprint="stored-opposite-v1",
        ),
    )
    member_specs = (
        EnsembleMemberSpec(
            artifact_id=winner_run.result.artifact.artifact_id,
            allocation=0.5,
        ),
        EnsembleMemberSpec(
            artifact_id=opposite_run.result.artifact.artifact_id,
            allocation=0.5,
        ),
    )
    composition = CompositionFlow(
        registry=real_dw_case.project.registry_snapshot(),
        artifacts=real_dw_case.project.artifacts,
    )
    ensemble = composition.invoke_ensemble(
        EnsembleDefinition(
            strategy_id="acceptance.stored-crossing",
            members=member_specs,
            budget_mode=BudgetMode.FLEXIBLE,
            target_gross=1.0,
        ),
        StrategyInvocation(
            invocation_id="stored-crossing-real-dw",
            evaluation_time=close_at(2024, 1, 2),
            config_fingerprint="stored-crossing-v1",
        ),
    )
    incompatible = composition.invoke_ensemble(
        EnsembleDefinition(
            strategy_id="acceptance.stored-crossing-fixed",
            members=member_specs,
            budget_mode=BudgetMode.FIXED,
            target_gross=1.0,
        ),
        StrategyInvocation(
            invocation_id="stored-crossing-fixed-real-dw",
            evaluation_time=close_at(2024, 1, 2),
            config_fingerprint="stored-crossing-fixed-v1",
        ),
    )

    assert ensemble.status is OutcomeStatus.COMPLETE
    assert ensemble.result.strategy.result.weights == ()
    assert ensemble.result.evidence.gross_before_netting == 1
    assert ensemble.result.evidence.gross_after_netting == 0
    assert ensemble.result.evidence.crossed_gross == 1
    assert ensemble.result.evidence.residual_budget == 1
    assert incompatible.errors[0].error_code == "ENSEMBLE_FIXED_BUDGET_INCOMPATIBLE"
    assert winner.runs == opposite.runs == 1
    assert {
        edge.dependency_id
        for edge in ensemble.result.strategy.artifact.dependencies
        if edge.consumer_role == "ensemble_member"
    } == {item.artifact_id for item in member_specs}


def test_uc_alpha_path_001_uses_child_memory_for_rerun_or_frozen_intent_for_replay(
    real_dw_case: RealDwProject,
) -> None:
    memory_a = StrategyMemoryStore()
    parent = run_real_daily_flow(
        real_dw_case,
        run_id="path-parent-account-a",
        account=initial_account("account-a"),
        memory=memory_a,
    )
    parent_intent = parent.result.decision_intents[0]
    parent_artifact = next(
        artifact
        for artifact in parent.result.artifacts
        if artifact.artifact_type == "decision_intent"
    )
    memory_a_before = memory_a.checkpoint()

    memory_b = StrategyMemoryStore()
    rerun = run_real_daily_flow(
        real_dw_case,
        run_id="path-rerun-account-b",
        account=initial_account("account-b"),
        memory=memory_b,
    )

    replay_memory = StrategyMemoryStore()
    replay = DailyExecutionFlow(
        clock=BacktestClock(parent_intent.decision_time),
        registry=real_dw_case.project.registry_snapshot(),
        artifacts=real_dw_case.project.artifacts,
        exchange=configured_exchange(),
        account=initial_account("account-b-replay"),
        memory=replay_memory,
        profile=DailyExecutionProfile(
            profile_id="historical-intent-replay.v1",
            market_dataset_id="dw-real-market",
            execution_price_role="execution_price",
            valuation_price_role="valuation_price",
            limitations=(
                "historical parent intent replayed without target-account Strategy rerun",
            ),
        ),
    ).execute_frozen(
        (FrozenDecision(intent=parent_intent, artifact=parent_artifact),),
        DailyRunRequest(
            run_id="path-historical-replay-account-b",
            config_fingerprint="historical-replay-v1",
            decision_times=(),
            session_closes=(close_at(2024, 1, 3),),
        ),
    )

    assert parent.status is rerun.status is replay.status is OutcomeStatus.COMPLETE
    assert parent.result.strategy_results[0].state_identity == "account-a:v0"
    assert rerun.result.strategy_results[0].state_identity == "account-b:v0"
    assert memory_a.checkpoint() == memory_a_before
    assert memory_b.snapshot("acceptance.actual-state-momentum").version == 1
    assert replay_memory.checkpoint() == ()
    assert replay.result.strategy_results == ()
    assert replay.result.memory_commits == ()
    assert replay.result.executions[0].limitations == (
        "historical parent intent replayed without target-account Strategy rerun",
    )
    assert any(
        edge.dependency_id == parent_artifact.artifact_id
        and edge.consumer_role == "decision_intent"
        for envelope in replay.result.artifacts
        if envelope.artifact_type == "execution_result"
        for edge in envelope.dependencies
    )
