"""Shared real-DW fixture support for current-scope acceptance scenarios."""

import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb

from qlibx import OutcomeStatus, QlibxProject
from qlibx.account import Account, StrategyMemoryStore
from qlibx.data import AvailableAtField, ComponentRequirement, DatasetRegistration, SourceFormat
from qlibx.execution import (
    CostRule,
    KrxExchange,
    KrxExchangeConfig,
    Side,
    StockInstrument,
)
from qlibx.flow import DailyExecutionFlow, DailyExecutionProfile, DailyRunRequest
from qlibx.kernel import BacktestClock
from qlibx.operations import BudgetMode, DecisionAction, StrategyDraft, WeightEntry

ROOT = Path(__file__).parents[2]
DW_DAILY = ROOT / "data" / "DW" / "fng_stock_daily_prices.csv"
K200_PREPROCESSED = ROOT / "data" / "preprocessed" / "k200_members.parquet"
KST = ZoneInfo("Asia/Seoul")


@dataclass(frozen=True, slots=True)
class RealDwProject:
    root: Path
    source: Path
    project: QlibxProject


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


def extract_real_k200_rows(destination: Path) -> None:
    assert K200_PREPROCESSED.is_file(), "repository acceptance requires real K200 membership"
    relation = duckdb.connect().sql(
        f"""
        WITH calendar AS (
            SELECT DISTINCT date
            FROM read_parquet('{K200_PREPROCESSED.as_posix()}')
        ), next_session AS (
            SELECT date, lead(date) OVER (ORDER BY date) AS available_at
            FROM calendar
        )
        SELECT
            members.date AS observation_time,
            sessions.available_at,
            members.ticker,
            members.index_weight
        FROM read_parquet('{K200_PREPROCESSED.as_posix()}') AS members
        JOIN next_session AS sessions USING (date)
        WHERE members.date = DATE '2024-01-02'
          AND members.ticker IN ('A005930', 'A000660')
        ORDER BY members.ticker
        """
    )
    relation.write_parquet(str(destination))


def create_real_dw_project(root: Path, bounded_source: Path) -> RealDwProject:
    QlibxProject.init(root, apply=True)
    source = root / "dw-real-market.parquet"
    shutil.copyfile(bounded_source, source)
    project = QlibxProject.open(root)
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
    return RealDwProject(root=root, source=source, project=project)


def register_real_k200_benchmark(
    case: RealDwProject,
    bounded_source: Path,
) -> RealDwProject:
    source = case.root / "real-k200-benchmark.parquet"
    shutil.copyfile(bounded_source, source)
    registration = case.project.register_dataset(
        DatasetRegistration(
            dataset_id="real-k200-benchmark",
            source=source.name,
            source_format=SourceFormat.PARQUET,
            instrument_field="ticker",
            observation_time_field="observation_time",
            available_at=AvailableAtField(field="available_at"),
            logical_key=("observation_time", "available_at", "ticker"),
            semantic_bindings={"benchmark_weight": "index_weight"},
            semantic_category="krx_k200_benchmark_weight",
            source_provenance=(
                "bounded rows from audited data/preprocessed/k200_members.parquet, which is an "
                "exact weight projection of data/DW/fng_k200_members.csv; available_at is the "
                "user-confirmed next distinct K200 trading session at 09:00 Asia/Seoul"
            ),
        )
    )
    assert registration.status is OutcomeStatus.COMPLETE
    assert registration.result.evidence.row_count == 2
    return case


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
                WeightEntry(instrument=str(selected.instrument), weight=self.direction),
            ),
            budget_mode=BudgetMode.FIXED,
            target_gross=1.0,
            decision_action=DecisionAction.RESEARCH_ONLY,
        )


class WeakRealDwStrategy(StoredWinnerStrategy):
    def __init__(self) -> None:
        super().__init__("acceptance.weak-real-dw", 0.4)

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
            weights=(WeightEntry(instrument=str(selected.instrument), weight=0.4),),
            budget_mode=BudgetMode.FLEXIBLE,
            target_gross=1.0,
            decision_action=DecisionAction.RESEARCH_ONLY,
            diagnostics=("real DW signal retained only forty percent gross",),
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
            cost_rules=tuple(
                CostRule(
                    rule_id=f"stock-{side.value.lower()}-2024",
                    product_type="stock",
                    side=side,
                    effective_from=start,
                    rate=cost_rate,
                    minimum_cost=0,
                )
                for side in (Side.BUY, Side.SELL)
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


def initial_account(account_id: str = "real-dw-account") -> Account:
    return Account(
        account_id=account_id,
        base_currency="KRW",
        initial_cash=10_000_000,
        instrument_ids=frozenset({"A000660", "A005930"}),
    )


def run_real_daily_flow(
    case: RealDwProject,
    *,
    run_id: str = "real-dw-daily-2024-01",
    sessions: tuple[datetime, ...] | None = None,
    decision_times: tuple[datetime, ...] | None = None,
    account: Account | None = None,
    memory: StrategyMemoryStore | None = None,
):
    selected_sessions = sessions or tuple(close_at(2024, 1, day) for day in (2, 3, 4, 5))
    selected_decisions = decision_times or (selected_sessions[0], selected_sessions[2])
    flow = DailyExecutionFlow(
        clock=BacktestClock(selected_sessions[0]),
        registry=case.project.registry_snapshot(),
        artifacts=case.project.artifacts,
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
