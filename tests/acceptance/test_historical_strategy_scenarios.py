import shutil
from datetime import datetime
from pathlib import Path

import duckdb
import pytest

from qlibx import OutcomeStatus, QlibxProject
from qlibx.account import Account, StrategyMemoryStore
from qlibx.contracts import (
    BudgetMode,
    DecisionAction,
    EveryNSessions,
    StrategyDraft,
    WeightEntry,
)
from qlibx.data import (
    AvailableAtField,
    ComponentRequirement,
    DatasetRegistration,
    SourceFormat,
)
from qlibx.execution import (
    CostRule,
    EtfInstrument,
    KrxExchange,
    KrxExchangeConfig,
    Side,
    StockInstrument,
)
from qlibx.flow import DailyExecutionFlow, DailyExecutionProfile, DailyRunRequest
from qlibx.runtime import BacktestClock
from tests.acceptance.real_dw_support import (
    DW_DAILY,
    K200_ETF_PREPROCESSED,
    KST,
    RealDwProject,
    close_at,
)

ETF = "A069500"
STOCKS = ("A000660", "A005930")


def _peer_market_source(destination: Path) -> None:
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
        WITH stock AS (
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
              AND trade_date BETWEEN 20240102 AND 20240108
        ), etf AS (
            SELECT
                date,
                date + INTERVAL '6 hours 30 minutes' AS available_at,
                ticker,
                execution_close_price AS execution_price,
                execution_close_price AS valuation_price,
                0.0 AS decision_return,
                trade_volume,
                false AS is_trading_halt
            FROM read_parquet('{K200_ETF_PREPROCESSED.as_posix()}')
            WHERE ticker = '{ETF}'
              AND CAST(date AS DATE) BETWEEN DATE '2024-01-02' AND DATE '2024-01-08'
        )
        SELECT * FROM stock
        UNION ALL
        SELECT * FROM etf
        ORDER BY date, ticker
        """
    )
    relation.write_parquet(str(destination))


def _peer_project(
    root: Path,
    bounded_real_k200_source: Path,
) -> RealDwProject:
    QlibxProject.init(root, apply=True)
    market = root / "peer-momentum-market.parquet"
    _peer_market_source(market)
    benchmark = root / "peer-momentum-benchmark.parquet"
    shutil.copyfile(bounded_real_k200_source, benchmark)
    project = QlibxProject.open(root)

    market_registration = project.register_dataset(
        DatasetRegistration(
            dataset_id="peer-momentum-market",
            source=market.name,
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
            semantic_category="krx_daily_stock_etf_market",
            source_provenance=(
                "bounded real DW closes for A000660/A005930 and audited real "
                "KODEX 200 closes; availability is 15:30 Asia/Seoul"
            ),
        )
    )
    benchmark_registration = project.register_dataset(
        DatasetRegistration(
            dataset_id="peer-momentum-benchmark",
            source=benchmark.name,
            source_format=SourceFormat.PARQUET,
            source_timezone="UTC",
            instrument_field="ticker",
            observation_time_field="observation_time",
            available_at=AvailableAtField(field="available_at"),
            logical_key=("observation_time", "available_at", "ticker"),
            semantic_bindings={"benchmark_weight": "index_weight"},
            semantic_category="krx_k200_benchmark_weight",
            source_provenance=(
                "bounded audited K200 weights with user-confirmed next-session "
                "09:00 Asia/Seoul availability"
            ),
        )
    )
    assert market_registration.status is OutcomeStatus.COMPLETE
    assert market_registration.result.evidence.row_count == 15
    assert benchmark_registration.status is OutcomeStatus.COMPLETE
    assert benchmark_registration.result.evidence.row_count == 2
    return RealDwProject(root=root, source=market, project=project)


class PeerMomentumEnhancedIndexStrategy:
    strategy_id = "acceptance.peer-momentum-enhanced-index"

    def requirements(self) -> tuple[ComponentRequirement, ...]:
        return (
            ComponentRequirement(
                requirement_id="peer_momentum.decision_return",
                semantic_role="decision_return",
                dataset_id="peer-momentum-market",
            ),
            ComponentRequirement(
                requirement_id="peer_momentum.benchmark_weight",
                semantic_role="benchmark_weight",
                dataset_id="peer-momentum-benchmark",
            ),
        )

    def trigger(self) -> EveryNSessions:
        return EveryNSessions(n=2)

    def run(self, view: object) -> StrategyDraft:
        account = view.account_snapshot()  # type: ignore[attr-defined]
        feedback = view.account_feedback()  # type: ignore[attr-defined]
        memory = view.memory_snapshot()  # type: ignore[attr-defined]
        session = view.as_of.astimezone(KST).date()  # type: ignore[attr-defined]
        return_frame = view.session(  # type: ignore[attr-defined]
            "decision_return",
            session,
            session_timezone="Asia/Seoul",
        )
        benchmark_frame = view.latest("benchmark_weight")  # type: ignore[attr-defined]

        observed = {
            str(row.instrument): float(row.decision_return)
            for row in return_frame.itertuples()
            if str(row.instrument) in STOCKS
        }
        assert set(observed) == set(STOCKS)
        raw_peer_signal = {
            instrument: sum(
                value for peer, value in observed.items() if peer != instrument
            )
            / (len(observed) - 1)
            for instrument in STOCKS
        }

        prior = memory.value if isinstance(memory.value, dict) else {}
        prior_history = prior.get("signal_history", {})
        updated_history: dict[str, list[float]] = {}
        decayed: dict[str, float] = {}
        for instrument in STOCKS:
            old_values = (
                list(prior_history.get(instrument, []))
                if isinstance(prior_history, dict)
                else []
            )
            values = [*old_values, raw_peer_signal[instrument]][-5:]
            updated_history[instrument] = values
            weights = range(1, len(values) + 1)
            decayed[instrument] = sum(
                weight * value for weight, value in zip(weights, values, strict=True)
            ) / sum(weights)
        selected = sorted(decayed, key=lambda item: (-decayed[item], item))[0]

        benchmark = {
            str(row.instrument): float(row.benchmark_weight)
            for row in benchmark_frame.itertuples()
        }
        assert set(benchmark) == set(STOCKS)
        physical = {
            instrument: 0.70 * benchmark[instrument]
            for instrument in STOCKS
        }
        cap = max(0.10, benchmark[selected])
        physical[selected] = min(cap, physical[selected] + 0.05)
        physical[ETF] = 1.0 - sum(physical.values())
        assert physical[ETF] >= 0

        transaction_cost = sum(
            fill.total_cost
            for entry in feedback.entries
            for fill in entry.fills
        )
        previous_performance = None
        if account.positions:
            previous_performance = view.latest_session_performance()  # type: ignore[attr-defined]

        proposed_memory = {
            "signal_history": updated_history,
            "selected": selected,
            "consumed_feedback_cursor": feedback.next_cursor,
            "feedback_transaction_cost": transaction_cost,
            "previous_portfolio_return": (
                None
                if previous_performance is None
                else previous_performance.portfolio_return
            ),
        }
        return StrategyDraft(
            weights=tuple(
                WeightEntry(instrument=instrument, weight=physical[instrument])
                for instrument in (*STOCKS, ETF)
            ),
            budget_mode=BudgetMode.FIXED,
            target_gross=1.0,
            decision_action=DecisionAction.TARGET,
            diagnostics=(
                "peer group is the bounded two-member K200 stock subset",
                "physical residual is held through KODEX 200",
            ),
            path_dependent=True,
            state_identity=(
                f"{account.account_id}:v{account.version}:"
                f"cursor{feedback.next_cursor}"
            ),
            feedback_cursor=str(feedback.next_cursor),
            proposed_memory=proposed_memory,
            expected_memory_version=memory.version,
        )


def _exchange() -> KrxExchange:
    start = datetime(2020, 1, 1, tzinfo=KST)
    exchange = KrxExchange(
        KrxExchangeConfig(
            schedule_version="peer-momentum-cost-v1",
            cost_rules=tuple(
                CostRule(
                    rule_id=f"{product}-{side.value.lower()}",
                    product_type=product,
                    side=side,
                    effective_from=start,
                    rate=rate,
                    minimum_cost=0,
                )
                for product, rate in (("stock", 0.0003), ("etf", 0.0002))
                for side in (Side.BUY, Side.SELL)
            ),
        )
    )
    for instrument in STOCKS:
        exchange.add_instrument(
            StockInstrument(
                instrument_id=instrument,
                exchange_id="XKRX",
                currency="KRW",
                lot_size=1,
            )
        )
    exchange.add_instrument(
        EtfInstrument(
            instrument_id=ETF,
            exchange_id="XKRX",
            currency="KRW",
            lot_size=1,
        )
    )
    return exchange


def _run(case: RealDwProject, run_id: str):
    sessions = tuple(
        close_at(2024, 1, day)
        for day in (3, 4, 5, 8)
    )
    account = Account(
        account_id="peer-momentum-account",
        base_currency="KRW",
        initial_cash=100_000_000,
        instrument_ids=frozenset((*STOCKS, ETF)),
    )
    memory = StrategyMemoryStore()
    outcome = DailyExecutionFlow(
        clock=BacktestClock(sessions[0]),
        registry=case.project.registry_snapshot(),
        artifacts=case.project.artifacts,
        exchange=_exchange(),
        account=account,
        memory=memory,
        profile=DailyExecutionProfile(
            market_dataset_id="peer-momentum-market",
            execution_price_role="execution_price",
            valuation_price_role="valuation_price",
        ),
    ).run(
        PeerMomentumEnhancedIndexStrategy(),
        DailyRunRequest(
            run_id=run_id,
            config_fingerprint="peer-momentum-enhanced-index-v1",
            session_closes=sessions,
        ),
    )
    return outcome, memory


def test_prd_native_peer_momentum_enhanced_index_closed_loop(
    tmp_path: Path,
    bounded_real_k200_source: Path,
) -> None:
    case = _peer_project(tmp_path / "peer-project", bounded_real_k200_source)
    first, first_memory = _run(case, "peer-momentum-native")
    second, _ = _run(case, "peer-momentum-native")

    assert first.status is OutcomeStatus.COMPLETE
    assert second.status is OutcomeStatus.COMPLETE
    assert first.result.decision_intents == second.result.decision_intents
    assert first.result.executions == second.result.executions
    assert first.result.session_performance == second.result.session_performance
    assert first.result.final_account == second.result.final_account

    benchmark_rows = duckdb.connect().sql(
        f"""
        SELECT ticker, index_weight
        FROM read_parquet(
            '{(case.root / "peer-momentum-benchmark.parquet").as_posix()}'
        )
        ORDER BY ticker
        """
    ).fetchall()
    benchmark = {ticker: float(weight) for ticker, weight in benchmark_rows}
    assert len(first.result.decision_intents) == 2
    for intent in first.result.decision_intents:
        target = {item.instrument_id: item.weight for item in intent.targets}
        assert set(target) == {*STOCKS, ETF}
        assert sum(target.values()) == pytest.approx(1.0)
        assert all(weight >= 0 for weight in target.values())
        for instrument in STOCKS:
            assert target[instrument] <= max(0.10, benchmark[instrument]) + 1e-12

    assert len(first.result.executions) == 2
    assert all(execution.fills for execution in first.result.executions)
    assert any(
        fill.instrument_id == ETF
        for execution in first.result.executions
        for fill in execution.fills
    )

    second_decision = first.result.strategy_results[1]
    assert second_decision.feedback_accesses[0].after_cursor == 0
    assert second_decision.feedback_accesses[0].next_cursor == 2
    assert second_decision.feedback_accesses[0].change_types == (
        "FillBatch",
        "MarkBatch",
    )
    assert len(second_decision.performance_accesses) == 1
    assert second_decision.performance_accesses[0].event_time == close_at(2024, 1, 4)
    assert second_decision.performance_accesses[0].feedback_cursor == 2

    assert len(first.result.memory_commits) == 2
    assert first.result.memory_commits[0].update_kind == "INITIALIZATION"
    assert first.result.memory_commits[0].feedback_cursor == 0
    assert first.result.memory_commits[1].update_kind == "FEEDBACK_UPDATE"
    assert first.result.memory_commits[1].feedback_cursor == 2
    committed_memory = first_memory.snapshot(
        PeerMomentumEnhancedIndexStrategy.strategy_id
    )
    assert committed_memory.version == 2
    assert committed_memory.feedback_cursor == 2
    assert committed_memory.value["previous_portfolio_return"] == pytest.approx(
        first.result.session_performance[1].portfolio_return
    )

    assert all(
        record.portfolio_return == pytest.approx(
            record.closing_nav / record.opening_nav - 1
        )
        for record in first.result.session_performance
    )
