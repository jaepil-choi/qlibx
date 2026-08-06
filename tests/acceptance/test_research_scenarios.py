import duckdb

from qlibx import OutcomeStatus
from qlibx.account import StrategyMemoryStore
from qlibx.flow import (
    STORED_SIGNAL_CONTRACT,
    CompositionFlow,
    DailyExecutionFlow,
    DailyExecutionProfile,
    DailyRunRequest,
    EnsembleDefinition,
    EnsembleMemberSpec,
    FrozenDecision,
    StoredSignalEntry,
    StoredSignalResult,
    StoredSignalWeighting,
)
from qlibx.kernel import BacktestClock
from qlibx.operations import BudgetMode, StrategyInvocation
from tests.acceptance.real_dw_support import (
    RealDwProject,
    StoredWinnerStrategy,
    close_at,
    configured_exchange,
    initial_account,
    run_real_daily_flow,
)


def test_uc_signal_002_and_uc_artifact_001_reuse_real_dw_stored_signal(
    real_dw_case: RealDwProject,
) -> None:
    rows = duckdb.connect().sql(
        f"""
        SELECT ticker, decision_return
        FROM read_parquet('{real_dw_case.source.as_posix()}')
        WHERE CAST(date AS DATE) = DATE '2024-01-02'
        ORDER BY ticker
        """
    ).fetchall()
    external_signal = StoredSignalResult(
        signal_semantics="real_dw_close_to_base_return",
        observation_time=close_at(2024, 1, 2),
        entries=tuple(
            StoredSignalEntry(instrument=ticker, value=value)
            for ticker, value in rows
        ),
    )
    imported = real_dw_case.project.artifacts.import_model_bytes(
        logical_identity="external-signal:real-dw-2024-01-02",
        contract=STORED_SIGNAL_CONTRACT,
        producer_id="external.real-dw-characteristic",
        payload_bytes=external_signal.model_dump_json().encode("utf-8"),
    )
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
