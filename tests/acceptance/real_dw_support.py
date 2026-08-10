"""Shared real-DW fixture support for current-scope acceptance scenarios."""

import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb

from qlibx import OutcomeStatus, QlibxProject
from qlibx.account import Account, StrategyMemoryStore
from qlibx.contracts import BudgetMode, DecisionAction, StrategyDraft, WeightEntry
from qlibx.data import AvailableAtField, ComponentRequirement, DatasetRegistration, SourceFormat
from qlibx.execution import (
    CostRule,
    KrxExchange,
    KrxExchangeConfig,
    Side,
    StockInstrument,
)
from qlibx.flow import DailyExecutionFlow, DailyExecutionProfile, DailyRunRequest
from qlibx.runtime import BacktestClock

ROOT = Path(__file__).parents[2]
DW_DAILY = ROOT / "data" / "DW" / "fng_stock_daily_prices.csv"
K200_PREPROCESSED = ROOT / "data" / "preprocessed" / "k200_members.parquet"
K200_ETF_PREPROCESSED = ROOT / "data" / "preprocessed" / "k200_etf_prices.parquet"
ADJUSTED_PRICES_PREPROCESSED = ROOT / "data" / "preprocessed" / "adjusted_prices.parquet"
SECTOR_PREPROCESSED = ROOT / "data" / "preprocessed" / "sector_classification.parquet"
INDUSTRY_MAPPING_PREPROCESSED = ROOT / "data" / "preprocessed" / "industry_mapping.parquet"
KST = ZoneInfo("Asia/Seoul")


@dataclass(frozen=True, slots=True)
class RealDwProject:
    root: Path
    source: Path
    project: QlibxProject


def close_at(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, 15, 30, tzinfo=KST)


def open_at(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, 9, 0, tzinfo=KST)


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


def extract_real_execution_event_rows(destination: Path) -> None:
    """Project honest open/close availability events from the real DW corpus."""

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
        WITH prices AS (
            SELECT
                ticker,
                strptime(CAST(trade_date AS VARCHAR), '%Y%m%d') AS session_open,
                strptime(CAST(trade_date AS VARCHAR), '%Y%m%d')
                    + INTERVAL '6 hours 30 minutes' AS session_close,
                open_price,
                close_price
            FROM read_csv(
                '{DW_DAILY.as_posix()}',
                header = true,
                columns = {columns}
            )
            WHERE ticker IN ('A005930', 'A000660')
              AND trade_date BETWEEN 20240102 AND 20240105
        )
        SELECT
            session_open AS event_time,
            session_open AS available_at,
            ticker,
            open_price AS open_execution_price,
            CAST(NULL AS DOUBLE) AS close_execution_price,
            CAST(NULL AS DOUBLE) AS valuation_price
        FROM prices
        UNION ALL
        SELECT
            session_close AS event_time,
            session_close AS available_at,
            ticker,
            CAST(NULL AS DOUBLE) AS open_execution_price,
            close_price AS close_execution_price,
            close_price AS valuation_price
        FROM prices
        ORDER BY event_time, ticker
        """
    )
    relation.write_parquet(str(destination))


def extract_real_forward_label_rows(destination: Path) -> None:
    """Project a bounded close-to-next-close label source from the real DW corpus."""

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
        WITH prices AS (
            SELECT
                ticker,
                trade_date,
                strptime(CAST(trade_date AS VARCHAR), '%Y%m%d') AS observation_time,
                close_price AS label_start_value,
                lead(close_price) OVER (
                    PARTITION BY ticker ORDER BY trade_date
                ) AS label_end_value,
                lead(
                    strptime(CAST(trade_date AS VARCHAR), '%Y%m%d')
                        + INTERVAL '6 hours 30 minutes'
                ) OVER (
                    PARTITION BY ticker ORDER BY trade_date
                ) AS horizon_end
            FROM read_csv(
                '{DW_DAILY.as_posix()}',
                header = true,
                columns = {columns}
            )
            WHERE ticker IN ('A005930', 'A000660')
              AND trade_date BETWEEN 20240102 AND 20240105
        )
        SELECT
            observation_time,
            horizon_end AS available_at,
            ticker,
            label_start_value,
            label_end_value,
            horizon_end
        FROM prices
        WHERE label_end_value IS NOT NULL
        ORDER BY observation_time, ticker
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


def extract_real_lookthrough_rows(destination: Path) -> None:
    assert K200_PREPROCESSED.is_file()
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
            members.index_weight AS constituent_weight
        FROM read_parquet('{K200_PREPROCESSED.as_posix()}') AS members
        JOIN next_session AS sessions USING (date)
        WHERE members.date IN (DATE '2024-01-02', DATE '2024-01-03')
          AND members.ticker IN ('A012330', 'A373220')
        ORDER BY members.date, members.ticker
        """
    )
    relation.write_parquet(str(destination))


def extract_real_extension_market_rows(destination: Path) -> None:
    assert DW_DAILY.is_file()
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
            strptime(CAST(trade_date AS VARCHAR), '%Y%m%d') AS observation_time,
            strptime(CAST(trade_date AS VARCHAR), '%Y%m%d')
                + INTERVAL '6 hours 30 minutes' AS available_at,
            ticker,
            close_price / base_price - 1 AS extension_input_value
        FROM read_csv(
            '{DW_DAILY.as_posix()}',
            header = true,
            columns = {columns}
        )
        WHERE ticker IN ('A005930', 'A000660')
          AND trade_date = 20240131
        ORDER BY ticker
        """
    )
    relation.write_parquet(str(destination))


def extract_real_extension_sector_rows(destination: Path) -> None:
    assert SECTOR_PREPROCESSED.is_file()
    assert INDUSTRY_MAPPING_PREPROCESSED.is_file()
    assert ADJUSTED_PRICES_PREPROCESSED.is_file()
    relation = duckdb.connect().sql(
        f"""
        WITH calendar AS (
            SELECT DISTINCT date
            FROM read_parquet('{ADJUSTED_PRICES_PREPROCESSED.as_posix()}')
            WHERE date BETWEEN DATE '2024-01-31' AND DATE '2024-02-02'
        ), next_session AS (
            SELECT date, lead(date) OVER (ORDER BY date) AS available_at
            FROM calendar
        )
        SELECT
            classifications.date AS observation_time,
            sessions.available_at,
            classifications.ticker,
            mapping.sector_code
        FROM read_parquet('{SECTOR_PREPROCESSED.as_posix()}') AS classifications
        JOIN read_parquet('{INDUSTRY_MAPPING_PREPROCESSED.as_posix()}') AS mapping
          USING (industry_code)
        JOIN next_session AS sessions ON classifications.date = sessions.date
        WHERE classifications.date = DATE '2024-01-31'
          AND classifications.ticker IN ('A005930', 'A000660')
        ORDER BY classifications.ticker
        """
    )
    relation.write_parquet(str(destination))


def real_lookthrough_physical_prices(trade_date: int) -> tuple[float, float]:
    assert K200_ETF_PREPROCESSED.is_file()
    columns = (
        "{'ticker':'VARCHAR','trade_date':'BIGINT','base_price':'DOUBLE',"
        "'open_price':'DOUBLE','high_price':'DOUBLE','low_price':'DOUBLE',"
        "'close_price':'DOUBLE','prev_close':'DOUBLE','adjustment_factor':'DOUBLE',"
        "'volume':'DOUBLE','amount':'DOUBLE','shares':'DOUBLE',"
        "'listing_type':'VARCHAR','change_type':'VARCHAR','halt_code':'DOUBLE',"
        "'admin_code':'DOUBLE'}"
    )
    stock_rows = duckdb.connect().sql(
        f"""
        SELECT close_price
        FROM read_csv(
            '{DW_DAILY.as_posix()}',
            header = true,
            columns = {columns}
        )
        WHERE ticker = 'A012330'
          AND trade_date = {trade_date}
        """
    ).fetchall()
    etf_rows = duckdb.connect().sql(
        f"""
        SELECT execution_close_price
        FROM read_parquet('{K200_ETF_PREPROCESSED.as_posix()}')
        WHERE ticker = 'A069500'
          AND CAST(date AS DATE) = strptime('{trade_date}', '%Y%m%d')::DATE
        """
    ).fetchall()
    assert len(stock_rows) == len(etf_rows) == 1
    return float(stock_rows[0][0]), float(etf_rows[0][0])


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
            source_timezone="UTC",
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
                "bounded unchanged rows from data/DW/fng_stock_daily_prices.csv; physical "
                "timestamps are naive UTC and the availability convention is 15:30 Asia/Seoul"
            ),
        )
    )
    assert registration.status is OutcomeStatus.COMPLETE
    assert registration.result.evidence.row_count == 8
    return RealDwProject(root=root, source=source, project=project)


def create_real_forward_label_project(root: Path, bounded_source: Path) -> RealDwProject:
    QlibxProject.init(root, apply=True)
    source = root / "real-forward-label.parquet"
    shutil.copyfile(bounded_source, source)
    project = QlibxProject.open(root)
    registration = project.register_dataset(
        DatasetRegistration(
            dataset_id="real-forward-label-prices",
            source=source.name,
            source_format=SourceFormat.PARQUET,
            source_timezone="UTC",
            instrument_field="ticker",
            observation_time_field="observation_time",
            available_at=AvailableAtField(field="available_at"),
            logical_key=("observation_time", "available_at", "ticker"),
            semantic_bindings={
                "label_start_value": "label_start_value",
                "label_end_value": "label_end_value",
            },
            semantic_category="real_krx_forward_label_source",
            source_provenance=(
                "bounded unchanged closes from data/DW/fng_stock_daily_prices.csv; "
                "each row is available at the observed next-session close in Asia/Seoul"
            ),
        )
    )
    assert registration.status is OutcomeStatus.COMPLETE
    assert registration.result.evidence.row_count == 6
    return RealDwProject(root=root, source=source, project=project)


def register_real_execution_events(
    case: RealDwProject,
    bounded_source: Path,
) -> RealDwProject:
    source = case.root / "real-execution-events.parquet"
    shutil.copyfile(bounded_source, source)
    registration = case.project.register_dataset(
        DatasetRegistration(
            dataset_id="dw-real-execution-events",
            source=source.name,
            source_format=SourceFormat.PARQUET,
            source_timezone="UTC",
            instrument_field="ticker",
            observation_time_field="event_time",
            available_at=AvailableAtField(field="available_at"),
            logical_key=("event_time", "available_at", "ticker"),
            semantic_bindings={
                "open_execution_price": "open_execution_price",
                "close_execution_price": "close_execution_price",
                "valuation_price": "valuation_price",
            },
            semantic_category="krx_daily_execution_events",
            source_provenance=(
                "bounded unchanged open/close values from "
                "data/DW/fng_stock_daily_prices.csv; open rows are available at 09:00 "
                "Asia/Seoul and close rows at 15:30 Asia/Seoul"
            ),
        )
    )
    assert registration.status is OutcomeStatus.COMPLETE
    assert registration.result.evidence.row_count == 16
    return RealDwProject(root=case.root, source=source, project=case.project)


def register_real_forward_label_horizon(case: RealDwProject) -> RealDwProject:
    registration = case.project.register_dataset(
        DatasetRegistration(
            dataset_id="real-forward-label-horizon",
            source=case.source.name,
            source_format=SourceFormat.PARQUET,
            source_timezone="UTC",
            instrument_field="ticker",
            observation_time_field="observation_time",
            available_at=AvailableAtField(field="available_at"),
            logical_key=("observation_time", "available_at", "ticker"),
            semantic_bindings={"horizon_end": "horizon_end"},
            semantic_category="real_krx_forward_label_source",
            source_provenance=(
                "explicit horizon binding over bounded unchanged closes from "
                "data/DW/fng_stock_daily_prices.csv; horizon_end is also the confirmed "
                "next-session-close availability instant"
            ),
        )
    )
    assert registration.status is OutcomeStatus.COMPLETE
    return case


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
            source_timezone="UTC",
            instrument_field="ticker",
            observation_time_field="observation_time",
            available_at=AvailableAtField(field="available_at"),
            logical_key=("observation_time", "available_at", "ticker"),
            semantic_bindings={"benchmark_weight": "index_weight"},
            semantic_category="krx_k200_benchmark_weight",
            source_provenance=(
                "bounded rows from audited data/preprocessed/k200_members.parquet, which is an "
                "exact weight projection of data/DW/fng_k200_members.csv; physical timestamps "
                "are naive UTC and available_at is the user-confirmed next distinct K200 "
                "trading session at 09:00 Asia/Seoul"
            ),
        )
    )
    assert registration.status is OutcomeStatus.COMPLETE
    assert registration.result.evidence.row_count == 2
    return case


def register_real_lookthrough_constituents(
    case: RealDwProject,
    bounded_source: Path,
) -> RealDwProject:
    source = case.root / "real-k200-etf-constituents.parquet"
    shutil.copyfile(bounded_source, source)
    registration = case.project.register_dataset(
        DatasetRegistration(
            dataset_id="real-k200-etf-constituents",
            source=source.name,
            source_format=SourceFormat.PARQUET,
            source_timezone="UTC",
            instrument_field="ticker",
            observation_time_field="observation_time",
            available_at=AvailableAtField(field="available_at"),
            logical_key=("observation_time", "available_at", "ticker"),
            semantic_bindings={"etf_constituent_weight": "constituent_weight"},
            semantic_category="user_selected_k200_etf_constituent_subset",
            source_provenance=(
                "user-authored KODEX 200 mapping over two equal-weight real K200 members; "
                "weights come from data/preprocessed/k200_members.parquet; physical timestamps "
                "are naive UTC and available_at uses the confirmed next K200 trading session "
                "at 09:00 Asia/Seoul; qlibx "
                "does not infer or auto-link this dataset from the ETF ticker"
            ),
        )
    )
    assert registration.status is OutcomeStatus.COMPLETE
    assert registration.result.evidence.row_count == 4
    return case


def register_real_extension_inputs(
    case: RealDwProject,
    market_source: Path,
    sector_source: Path,
) -> RealDwProject:
    project_market = case.root / "real-extension-market.parquet"
    project_sector = case.root / "real-extension-sector.parquet"
    shutil.copyfile(market_source, project_market)
    shutil.copyfile(sector_source, project_sector)
    market_registration = case.project.register_dataset(
        DatasetRegistration(
            dataset_id="real-extension-market",
            source=project_market.name,
            source_format=SourceFormat.PARQUET,
            source_timezone="UTC",
            instrument_field="ticker",
            observation_time_field="observation_time",
            available_at=AvailableAtField(field="available_at"),
            logical_key=("observation_time", "available_at", "ticker"),
            semantic_bindings={"extension_input_value": "extension_input_value"},
            semantic_category="krx_daily_return",
            source_provenance=(
                "bounded unchanged calculation from data/DW/fng_stock_daily_prices.csv; "
                "physical timestamps are naive UTC and available at the observed close, "
                "15:30 Asia/Seoul"
            ),
        )
    )
    sector_registration = case.project.register_dataset(
        DatasetRegistration(
            dataset_id="real-extension-sector",
            source=project_sector.name,
            source_format=SourceFormat.PARQUET,
            source_timezone="UTC",
            instrument_field="ticker",
            observation_time_field="observation_time",
            available_at=AvailableAtField(field="available_at"),
            logical_key=("observation_time", "available_at", "ticker"),
            semantic_bindings={"neutralization_group": "sector_code"},
            semantic_category="krx_sector_classification",
            source_provenance=(
                "bounded rows from data/preprocessed/sector_classification.parquet and "
                "industry_mapping.parquet, preprocessed from "
                "data/DW/DW_FNG_FGSC종목_20200101-20260430.csv; physical timestamps are "
                "naive UTC and available_at is the user-confirmed next trading session at "
                "09:00 Asia/Seoul"
            ),
        )
    )
    assert market_registration.status is OutcomeStatus.COMPLETE
    assert sector_registration.status is OutcomeStatus.COMPLETE
    assert market_registration.result.evidence.row_count == 2
    assert sector_registration.result.evidence.row_count == 2
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
        feedback = view.account_feedback()  # type: ignore[attr-defined]
        memory = view.memory_snapshot()  # type: ignore[attr-defined]
        state_identity = f"{account.account_id}:v{account.version}"
        if account.positions:
            has_new_feedback = feedback.next_cursor > memory.feedback_cursor
            return StrategyDraft(
                weights=(),
                budget_mode=BudgetMode.FLEXIBLE,
                target_gross=1.0,
                decision_action=DecisionAction.HOLD,
                diagnostics=("hold because a committed physical position exists",),
                path_dependent=True,
                state_identity=state_identity,
                feedback_cursor=str(feedback.next_cursor),
                proposed_memory=(
                    {"confirmed_feedback_cursor": feedback.next_cursor}
                    if has_new_feedback
                    else None
                ),
                expected_memory_version=memory.version if has_new_feedback else None,
            )
        session = view.as_of.astimezone(KST).date()  # type: ignore[attr-defined]
        cross_section = view.session(  # type: ignore[attr-defined]
            "decision_return",
            session,
            session_timezone="Asia/Seoul",
        )
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
        cross_section = view.session(  # type: ignore[attr-defined]
            "decision_return",
            session,
            session_timezone="Asia/Seoul",
        )
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
        cross_section = view.session(  # type: ignore[attr-defined]
            "decision_return",
            session,
            session_timezone="Asia/Seoul",
        )
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
    impact_rate: float = 0,
) -> KrxExchange:
    venue = KrxExchange(
        configured_exchange_config(
            cost_rate=cost_rate,
            participation_rate=participation_rate,
            impact_rate=impact_rate,
        )
    )
    for instrument in configured_instruments():
        venue.add_instrument(instrument)
    return venue


def configured_exchange_config(
    *,
    cost_rate: float = 0.0015,
    participation_rate: float | None = None,
    impact_rate: float = 0,
) -> KrxExchangeConfig:
    start = datetime(2020, 1, 1, tzinfo=KST)
    return KrxExchangeConfig(
        schedule_version="krx-acceptance-2024-v1",
        participation_rate=participation_rate,
        impact_rate=impact_rate,
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


def configured_instruments() -> tuple[StockInstrument, ...]:
    return tuple(
        StockInstrument(
            instrument_id=ticker,
            exchange_id="XKRX",
            currency="KRW",
            lot_size=1,
        )
        for ticker in ("A000660", "A005930")
    )


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
