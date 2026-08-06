from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
import pytest

from qlibx import OutcomeStatus, QlibxProject
from qlibx.account import Account
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
    DailyExecutionFlow,
    DailyExecutionProfile,
    DailyRunRequest,
)
from qlibx.kernel import BacktestClock
from qlibx.operations import (
    BudgetMode,
    DecisionAction,
    StrategyDraft,
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
        state_identity = f"{account.account_id}:v{account.version}"
        if account.positions:
            return StrategyDraft(
                weights=(),
                budget_mode=BudgetMode.FLEXIBLE,
                target_gross=1.0,
                decision_action=DecisionAction.HOLD,
                diagnostics=("hold because a committed physical position exists",),
                path_dependent=True,
                state_identity=state_identity,
                feedback_cursor=str(account.feedback_cursor),
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


def configured_exchange() -> KrxExchange:
    start = datetime(2020, 1, 1, tzinfo=KST)
    venue = KrxExchange(
        KrxExchangeConfig(
            schedule_version="krx-acceptance-2024-v1",
            cost_rules=(
                CostRule(
                    rule_id="stock-buy-2024",
                    product_type="stock",
                    side=Side.BUY,
                    effective_from=start,
                    rate=0.0015,
                    minimum_cost=0,
                ),
                CostRule(
                    rule_id="stock-sell-2024",
                    product_type="stock",
                    side=Side.SELL,
                    effective_from=start,
                    rate=0.0015,
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

    phase_one_sessions = tuple(close_at(2024, 1, day) for day in (2, 3))
    phase_one = run_real_daily_flow(
        project,
        run_id="real-dw-resume-phase-1",
        sessions=phase_one_sessions,
        decision_times=(phase_one_sessions[0],),
    )
    restored = Account.from_checkpoint(phase_one.result.checkpoint.account_checkpoint)
    phase_two_sessions = tuple(close_at(2024, 1, day) for day in (4, 5))
    phase_two = run_real_daily_flow(
        project,
        run_id="real-dw-resume-phase-2",
        sessions=phase_two_sessions,
        decision_times=(phase_two_sessions[0],),
        account=restored,
    )

    assert phase_one.status is OutcomeStatus.COMPLETE
    assert phase_two.status is OutcomeStatus.COMPLETE
    assert phase_two.result.strategy_results[0].state_accesses[0].version == 2
    assert phase_two.result.final_account == first.result.final_account
