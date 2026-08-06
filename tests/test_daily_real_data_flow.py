from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
import pytest

from qlibx import OutcomeStatus, QlibxProject
from qlibx.account import Account, StrategyMemoryStore
from qlibx.data import (
    AvailableAtField,
    ComponentRequirement,
    DatasetRegistration,
    SourceFormat,
)
from qlibx.execution import (
    CostRule,
    KrxExchange,
    KrxExchangeConfig,
    Side,
    StockInstrument,
)
from qlibx.flow import (
    CompositionFlow,
    DailyExecutionFlow,
    DailyExecutionProfile,
    DailyRunRequest,
    EnsembleDefinition,
    EnsembleMemberSpec,
    FrozenDecision,
    IntradayExecutionFlow,
    IntradayExecutionProfile,
    IntradayRunRequest,
)
from qlibx.kernel import BacktestClock
from qlibx.operations import (
    BudgetMode,
    DecisionAction,
    StrategyDraft,
    StrategyInvocation,
    WeightEntry,
)

ROOT = Path(__file__).parents[1]
DW_DAILY = ROOT / "data" / "DW" / "fng_stock_daily_prices.csv"
KST = ZoneInfo("Asia/Seoul")


def close_at(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, 15, 30, tzinfo=KST)


def extract_real_dw_rows(destination: Path) -> None:
    assert DW_DAILY.is_file(), "repository acceptance requires the real DW daily-price CSV"
    columns = (
        "{'ticker':'VARCHAR','trade_date':'BIGINT','base_price':'DOUBLE',"
        "'open_price':'DOUBLE','high_price':'DOUBLE','low_price':'DOUBLE',"
        "'close_price':'DOUBLE','prev_close':'DOUBLE','adjustment_factor':'DOUBLE',"
        "'volume':'DOUBLE','amount':'DOUBLE','shares':'DOUBLE',"
        "'listing_type':'VARCHAR','change_type':'VARCHAR','halt_code':'DOUBLE',"
        "'admin_code':'DOUBLE'}"
    )
    relation = duckdb.connect().sql(
        f"""
        SELECT
            strptime(CAST(trade_date AS VARCHAR), '%Y%m%d') AS date,
            strptime(CAST(trade_date AS VARCHAR), '%Y%m%d')
                + INTERVAL '6 hours 30 minutes' AS available_at,
            ticker,
            close_price AS execution_price,
            close_price AS valuation_price,
            close_price / base_price - 1 AS decision_return,
            volume AS trade_volume,
            halt_code <> 0 AS is_trading_halt
        FROM read_csv(
            '{DW_DAILY.as_posix()}',
            header = true,
            columns = {columns}
        )
        WHERE ticker IN ('A005930', 'A000660')
          AND trade_date BETWEEN 20240102 AND 20240105
        ORDER BY date, ticker
        """
    )
    relation.write_parquet(str(destination))


class ActualStateMomentumStrategy:
    strategy_id = "acceptance.actual-state-momentum"

    def requirements(self) -> tuple[ComponentRequirement, ...]:
        return (
            ComponentRequirement(
                requirement_id="strategy.daily_return",
                semantic_role="decision_return",
                dataset_id="dw-real-market",
            ),
        )

    def run(self, view: object) -> StrategyDraft:
        account = view.account_snapshot()  # type: ignore[attr-defined]
        memory = view.memory_snapshot()  # type: ignore[attr-defined]
        state_identity = f"{account.account_id}:v{account.version}"
        if account.positions:
            has_new_feedback = account.feedback_cursor > memory.feedback_cursor
            return StrategyDraft(
                weights=(),
                budget_mode=BudgetMode.FLEXIBLE,
                target_gross=1.0,
                decision_action=DecisionAction.HOLD,
                diagnostics=("hold because a committed physical position exists",),
                path_dependent=True,
                state_identity=state_identity,
                feedback_cursor=str(account.feedback_cursor),
                proposed_memory=(
                    {"confirmed_feedback_cursor": account.feedback_cursor}
                    if has_new_feedback
                    else None
                ),
                expected_memory_version=memory.version if has_new_feedback else None,
            )
        session = view.as_of.astimezone(KST).date()  # type: ignore[attr-defined]
        cross_section = view.session("decision_return", session)  # type: ignore[attr-defined]
        selected = cross_section.sort_values(
            ["decision_return", "instrument"],
            ascending=[False, True],
            kind="mergesort",
        ).iloc[0]
        return StrategyDraft(
            weights=(WeightEntry(instrument=str(selected.instrument), weight=1.0),),
            budget_mode=BudgetMode.FIXED,
            target_gross=1.0,
            decision_action=DecisionAction.TARGET,
            diagnostics=("selected the highest real DW close-to-base return",),
            path_dependent=True,
            state_identity=state_identity,
            feedback_cursor=str(account.feedback_cursor),
        )


class StoredWinnerStrategy:
    def __init__(self, strategy_id: str, direction: float) -> None:
        self.strategy_id = strategy_id
        self.direction = direction
        self.runs = 0

    def requirements(self) -> tuple[ComponentRequirement, ...]:
        return (
            ComponentRequirement(
                requirement_id=f"{self.strategy_id}.daily_return",
                semantic_role="decision_return",
                dataset_id="dw-real-market",
            ),
        )

    def run(self, view: object) -> StrategyDraft:
        self.runs += 1
        session = view.as_of.astimezone(KST).date()  # type: ignore[attr-defined]
        cross_section = view.session("decision_return", session)  # type: ignore[attr-defined]
        selected = cross_section.sort_values(
            ["decision_return", "instrument"],
            ascending=[False, True],
            kind="mergesort",
        ).iloc[0]
        return StrategyDraft(
            weights=(
                WeightEntry(
                    instrument=str(selected.instrument),
                    weight=self.direction,
                ),
            ),
            budget_mode=BudgetMode.FIXED,
            target_gross=1.0,
            decision_action=DecisionAction.RESEARCH_ONLY,
        )

def configured_exchange(
    *,
    cost_rate: float = 0.0015,
    participation_rate: float | None = None,
) -> KrxExchange:
    start = datetime(2020, 1, 1, tzinfo=KST)
    venue = KrxExchange(
        KrxExchangeConfig(
            schedule_version="krx-acceptance-2024-v1",
            participation_rate=participation_rate,
            cost_rules=(
                CostRule(
                    rule_id="stock-buy-2024",
                    product_type="stock",
                    side=Side.BUY,
                    effective_from=start,
                    rate=cost_rate,
                    minimum_cost=0,
                ),
                CostRule(
                    rule_id="stock-sell-2024",
                    product_type="stock",
                    side=Side.SELL,
                    effective_from=start,
                    rate=cost_rate,
                    minimum_cost=0,
                ),
            ),
        )
    )
    for ticker in ("A000660", "A005930"):
        venue.add_instrument(
            StockInstrument(
                instrument_id=ticker,
                exchange_id="XKRX",
                currency="KRW",
                lot_size=1,
            )
        )
    return venue


def initial_account() -> Account:
    return Account(
        account_id="real-dw-account",
        base_currency="KRW",
        initial_cash=10_000_000,
        instrument_ids=frozenset({"A000660", "A005930"}),
    )


def run_real_daily_flow(
    project: QlibxProject,
    *,
    run_id: str = "real-dw-daily-2024-01",
    sessions: tuple[datetime, ...] | None = None,
    decision_times: tuple[datetime, ...] | None = None,
    account: Account | None = None,
    memory: StrategyMemoryStore | None = None,
):
    selected_sessions = sessions or tuple(
        close_at(2024, 1, day) for day in (2, 3, 4, 5)
    )
    selected_decisions = decision_times or (
        selected_sessions[0],
        selected_sessions[2],
    )
    flow = DailyExecutionFlow(
        clock=BacktestClock(selected_sessions[0]),
        registry=project.registry_snapshot(),
        artifacts=project.artifacts,
        exchange=configured_exchange(),
        account=account or initial_account(),
        memory=memory,
        profile=DailyExecutionProfile(
            market_dataset_id="dw-real-market",
            execution_price_role="execution_price",
            valuation_price_role="valuation_price",
        ),
    )
    return flow.run(
        ActualStateMomentumStrategy(),
        DailyRunRequest(
            run_id=run_id,
            config_fingerprint="real-dw-actual-state-momentum-v1",
            decision_times=selected_decisions,
            session_closes=selected_sessions,
        ),
    )


def test_uc_closed_loop_001_and_uc_exec_002_use_real_dw_values(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    QlibxProject.init(project_root, apply=True)
    source = project_root / "dw-real-market.parquet"
    extract_real_dw_rows(source)
    project = QlibxProject.open(project_root)
    registration = project.register_dataset(
        DatasetRegistration(
            dataset_id="dw-real-market",
            source=source.name,
            source_format=SourceFormat.PARQUET,
            instrument_field="ticker",
            observation_time_field="date",
            available_at=AvailableAtField(field="available_at"),
            logical_key=("date", "available_at", "ticker"),
            semantic_bindings={
                "decision_return": "decision_return",
                "execution_price": "execution_price",
                "valuation_price": "valuation_price",
                "trade_volume": "trade_volume",
                "trading_halt": "is_trading_halt",
            },
            semantic_category="krx_daily_market",
            source_provenance=(
                "bounded unchanged rows from data/DW/fng_stock_daily_prices.csv; "
                "availability is architecture close convention 15:30 Asia/Seoul"
            ),
        )
    )
    assert registration.status is OutcomeStatus.COMPLETE
    assert registration.result.evidence.row_count == 8

    first = run_real_daily_flow(project)
    second = run_real_daily_flow(project)

    assert first.status is OutcomeStatus.COMPLETE
    assert second.status is OutcomeStatus.COMPLETE
    assert first.result.checkpoint == second.result.checkpoint
    assert first.result.decision_intents == second.result.decision_intents
    assert first.result.executions == second.result.executions

    assert len(first.result.decision_intents) == 1
    assert first.result.decision_intents[0].targets[0].instrument_id == "A005930"
    execution = first.result.executions[0]
    assert execution.event_time == close_at(2024, 1, 3)
    assert execution.fills[0].price == 77_000
    assert execution.fills[0].dealt_quantity == 129
    assert execution.fills[0].total_cost == pytest.approx(14_899.5)
    assert "intraday path and market impact are not modelled" in execution.limitations

    second_decision = first.result.strategy_results[1]
    actual = second_decision.state_accesses[0]
    assert second_decision.decision_action is DecisionAction.HOLD
    assert actual.version == 2
    assert actual.feedback_cursor == 2
    assert actual.cash == pytest.approx(52_100.5)
    assert actual.nav == pytest.approx(9_985_100.5)
    assert [(holding.instrument_id, holding.quantity) for holding in actual.holdings] == [
        ("A005930", 129)
    ]
    assert all(
        monitor.account.version == monitor.account_version_after_callback
        for monitor in first.result.monitors
    )
    assert any("|10|EXECUTION" in item for item in first.result.checkpoint.event_trace)
    assert first.result.final_account.holdings() == {"A005930": 129}
    assert len(first.result.memory_commits) == 1
    assert first.result.memory_commits[0].previous_version == 0
    assert first.result.memory_commits[0].version == 1
    assert first.result.memory_commits[0].feedback_cursor == 2
    assert first.result.memory_commits[0].value == {"confirmed_feedback_cursor": 2}

    parent_checkpoint = first.result.checkpoint
    parent_intent = first.result.decision_intents[0]
    parent_artifact = next(
        artifact
        for artifact in first.result.artifacts
        if artifact.artifact_type == "decision_intent"
    )
    child_session = (close_at(2024, 1, 3),)

    def execute_child(
        run_id: str,
        cost_rate: float,
        *,
        participation_rate: float | None = None,
    ):
        flow = DailyExecutionFlow(
            clock=BacktestClock(parent_intent.decision_time),
            registry=project.registry_snapshot(),
            artifacts=project.artifacts,
            exchange=configured_exchange(
                cost_rate=cost_rate,
                participation_rate=participation_rate,
            ),
            account=initial_account(),
            profile=DailyExecutionProfile(
                profile_id=f"{run_id}.profile",
                market_dataset_id="dw-real-market",
                execution_price_role="execution_price",
                valuation_price_role="valuation_price",
                volume_role="trade_volume" if participation_rate is not None else None,
            ),
        )
        return flow.execute_frozen(
            (FrozenDecision(intent=parent_intent, artifact=parent_artifact),),
            DailyRunRequest(
                run_id=run_id,
                config_fingerprint=f"{run_id}.config",
                decision_times=(),
                session_closes=child_session,
            ),
        )

    normal_child = execute_child("real-dw-child-normal", 0.0015)
    partial_child = execute_child(
        "real-dw-child-partial",
        0.0015,
        participation_rate=0.000001,
    )

    assert normal_child.status is OutcomeStatus.COMPLETE
    assert partial_child.status is OutcomeStatus.COMPLETE
    assert normal_child.result.final_account.holdings() == {"A005930": 129}
    assert partial_child.result.final_account.holdings() == {"A005930": 21}
    assert partial_child.result.executions[0].diagnostics[0].reasons == (
        "VOLUME_LIMIT",
        "LOT_ROUNDING",
    )
    assert normal_child.result.final_account.cash != partial_child.result.final_account.cash
    assert first.result.checkpoint == parent_checkpoint
    assert first.result.decision_intents[0] == parent_intent
    assert all(
        edge.dependency_id == parent_artifact.artifact_id
        for result in (normal_child, partial_child)
        for artifact in result.result.artifacts
        if artifact.artifact_type == "execution_result"
        for edge in artifact.dependencies
        if edge.consumer_role == "decision_intent"
    )

    # No repository intraday source exists. This bounded fixture characterizes the
    # multi-event contract explicitly; it is not evidence about historical execution quality.
    intraday_source = project_root / "intraday-characterization.csv"
    intraday_source.write_text(
        "timestamp,available_at,ticker,point_price,event_volume\n"
        "2024-01-03T09:30:00+09:00,2024-01-03T09:30:00+09:00,A005930,77000,30\n"
        "2024-01-03T11:00:00+09:00,2024-01-03T11:00:00+09:00,A005930,77000,30\n"
        "2024-01-03T15:20:00+09:00,2024-01-03T15:20:00+09:00,A005930,77000,30\n",
        encoding="utf-8",
    )
    registered_intraday = project.register_dataset(
        DatasetRegistration(
            dataset_id="intraday-characterization",
            source=intraday_source.name,
            source_format=SourceFormat.CSV,
            instrument_field="ticker",
            observation_time_field="timestamp",
            available_at=AvailableAtField(field="available_at"),
            logical_key=("timestamp", "available_at", "ticker"),
            semantic_bindings={
                "intraday_execution_price": "point_price",
                "intraday_volume": "event_volume",
            },
            semantic_category="synthetic_intraday_characterization",
            source_provenance=(
                "synthetic multi-event fixture; repository has no intraday source; "
                "must not be used as market-quality evidence"
            ),
        )
    )
    assert registered_intraday.status is OutcomeStatus.COMPLETE
    intraday_times = (
        datetime(2024, 1, 3, 9, 30, tzinfo=KST),
        datetime(2024, 1, 3, 11, 0, tzinfo=KST),
        datetime(2024, 1, 3, 15, 20, tzinfo=KST),
    )
    intraday_account = initial_account()
    intraday_flow = IntradayExecutionFlow(
        clock=BacktestClock(parent_intent.decision_time),
        registry=project.registry_snapshot(),
        artifacts=project.artifacts,
        exchange=configured_exchange(participation_rate=1.0),
        account=intraday_account,
        profile=IntradayExecutionProfile(
            profile_id="intraday-characterization.v1",
            market_dataset_id="intraday-characterization",
        ),
    )
    intraday = intraday_flow.execute_frozen(
        FrozenDecision(intent=parent_intent, artifact=parent_artifact),
        IntradayRunRequest(
            run_id="synthetic-intraday-child",
            config_fingerprint="synthetic-intraday-v1",
            execution_times=intraday_times,
        ),
    )

    assert intraday.status is OutcomeStatus.COMPLETE
    assert [
        evidence.execution.account_before.version
        for evidence in intraday.result.executions
    ] == [0, 1, 2]
    assert [
        evidence.execution.fills[0].dealt_quantity
        for evidence in intraday.result.executions
    ] == [30, 30, 30]
    assert intraday.result.executions[-1].remaining[0].remaining_quantity == 39
    assert intraday.result.executions[-1].completes_decision is False
    assert intraday.result.final_account.holdings() == {"A005930": 90}
    assert intraday.result.final_account.version == 4
    assert all(
        artifact.dependencies[0].dependency_id == parent_artifact.artifact_id
        for artifact in intraday.result.artifacts
    )

    missing_account = initial_account()
    missing_intraday = IntradayExecutionFlow(
        clock=BacktestClock(parent_intent.decision_time),
        registry=project.registry_snapshot(),
        artifacts=project.artifacts,
        exchange=configured_exchange(participation_rate=1.0),
        account=missing_account,
        profile=IntradayExecutionProfile(
            profile_id="missing-intraday.v1",
            market_dataset_id="dw-real-market",
        ),
    ).execute_frozen(
        FrozenDecision(intent=parent_intent, artifact=parent_artifact),
        IntradayRunRequest(
            run_id="missing-intraday-child",
            config_fingerprint="missing-intraday-v1",
            execution_times=(intraday_times[0],),
        ),
    )
    assert missing_intraday.status is OutcomeStatus.FAILED
    assert missing_intraday.errors[0].error_code == "REQUIREMENT_NOT_RESOLVED"
    assert missing_account.snapshot().version == 0

    phase_one_sessions = tuple(close_at(2024, 1, day) for day in (2, 3))
    phase_one = run_real_daily_flow(
        project,
        run_id="real-dw-resume-phase-1",
        sessions=phase_one_sessions,
        decision_times=(phase_one_sessions[0],),
    )
    restored = Account.from_checkpoint(phase_one.result.checkpoint.account_checkpoint)
    restored_memory = StrategyMemoryStore.from_checkpoint(
        phase_one.result.checkpoint.memory_snapshots
    )
    phase_two_sessions = tuple(close_at(2024, 1, day) for day in (4, 5))
    phase_two = run_real_daily_flow(
        project,
        run_id="real-dw-resume-phase-2",
        sessions=phase_two_sessions,
        decision_times=(phase_two_sessions[0],),
        account=restored,
        memory=restored_memory,
    )

    assert phase_one.status is OutcomeStatus.COMPLETE
    assert phase_two.status is OutcomeStatus.COMPLETE
    assert phase_two.result.strategy_results[0].state_accesses[0].version == 2
    assert phase_two.result.memory_commits[0].previous_version == 0
    assert phase_two.result.memory_commits[0].feedback_cursor == 2
    assert phase_two.result.final_account == first.result.final_account

    winner = StoredWinnerStrategy("acceptance.stored-winner", 1.0)
    opposite = StoredWinnerStrategy("acceptance.stored-opposite", -1.0)
    winner_run = project.invoke(
        winner,
        StrategyInvocation(
            invocation_id="stored-winner-real-dw",
            evaluation_time=close_at(2024, 1, 2),
            config_fingerprint="stored-winner-v1",
        ),
    )
    opposite_run = project.invoke(
        opposite,
        StrategyInvocation(
            invocation_id="stored-opposite-real-dw",
            evaluation_time=close_at(2024, 1, 2),
            config_fingerprint="stored-opposite-v1",
        ),
    )
    composition = CompositionFlow(
        registry=project.registry_snapshot(),
        artifacts=project.artifacts,
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
    assert {item.instrument for item in ensemble.result.evidence.contributions} == {
        "A005930"
    }
    assert incompatible.status is OutcomeStatus.FAILED
    assert incompatible.errors[0].error_code == "ENSEMBLE_FIXED_BUDGET_INCOMPATIBLE"
    assert winner.runs == 1
    assert opposite.runs == 1
    assert {
        edge.dependency_id
        for edge in ensemble.result.strategy.artifact.dependencies
        if edge.consumer_role == "ensemble_member"
    } == {spec.artifact_id for spec in member_specs}

    path_member_artifacts = tuple(
        artifact
        for artifact in first.result.artifacts
        if artifact.artifact_type == "strategy_result"
    )
    path_incompatible = composition.invoke_ensemble(
        EnsembleDefinition(
            strategy_id="acceptance.path-incompatible",
            members=tuple(
                EnsembleMemberSpec(artifact_id=artifact.artifact_id, allocation=0.5)
                for artifact in path_member_artifacts
            ),
            budget_mode=BudgetMode.FLEXIBLE,
            target_gross=1.0,
        ),
        StrategyInvocation(
            invocation_id="path-incompatible-real-dw",
            evaluation_time=close_at(2024, 1, 4),
            config_fingerprint="path-incompatible-v1",
        ),
    )
    assert path_incompatible.status is OutcomeStatus.FAILED
    assert path_incompatible.errors[0].error_code == "ENSEMBLE_STATE_INCOMPATIBLE"
