"""두 전략의 등록 이후 data flow를 qlibx 공개 API로 재현한다."""

from __future__ import annotations

import hashlib
import json
import math
import sys
from datetime import date, datetime, time
from importlib.metadata import version
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import duckdb
import pandas as pd
from strategies import FiveSessionTopTenStrategy, PeerMomentumLongShortStrategy

from qlibx import (
    ACADEMIC_EXECUTION_CONTRACT,
    AcademicInstrumentKind,
    AcademicInstrumentListing,
    AcademicPriceSemantics,
    AcademicRunSpec,
    AvailableAtField,
    ConstructionProfile,
    CostRule,
    DailyAccountSeed,
    DailyMarketBinding,
    DatasetRegistration,
    KrxExchangeConfig,
    OutcomeStatus,
    PortfolioConstructionRequest,
    QlibxProject,
    Side,
    SourceFormat,
    StockInstrument,
    StrategyInvocation,
    TriggerContext,
)

SHOWCASE_ID = "show_004_two_strategy_data_flow"
DATASET_ID = "showcase-two-strategy-market-v1"
KST = ZoneInfo("Asia/Seoul")
INITIAL_NAV = 100_000_000.0
SOURCE_START = 20240102
SOURCE_END = 20240329
ACADEMIC_CANDIDATE_START = date.fromisoformat("2024-01-30")
KRX_CANDIDATE_START = date.fromisoformat("2024-01-09")
DECISION_END = date.fromisoformat("2024-03-22")
KRX_FLOW_END = date.fromisoformat("2024-03-25")

# Candidate calendar는 price coverage가 아니라 이 showcase가 선언한 KRX session 사실이다.
DECLARED_MARKET_HOLIDAYS = frozenset(
    date.fromisoformat(value) for value in ("2024-02-09", "2024-02-12", "2024-03-01")
)
DECLARED_SESSION_DATES = tuple(
    timestamp.date()
    for timestamp in pd.bdate_range("2024-01-02", "2024-03-29")
    if timestamp.date() not in DECLARED_MARKET_HOLIDAYS
)

# 고정 universe와 peer 분류는 데이터에서 추론하지 않는다. 이 선택은 showcase의 연구 가정이다.
PEER_GROUPS = {
    "auto_mobility": ("A000270", "A005380", "A012330", "A161390"),
    "semiconductor_electronics": ("A000660", "A005930", "A006400", "A066570"),
    "digital_platforms": ("A018260", "A035420", "A035720", "A259960"),
    "finance": ("A032830", "A055550", "A086790", "A105560"),
    "bio_healthcare": ("A068270", "A128940", "A207940", "A326030"),
}
UNIVERSE = tuple(sorted(instrument for group in PEER_GROUPS.values() for instrument in group))

# 원본 CSV의 16개 물리 컬럼을 ASCII 이름으로 명시해 Windows code-page 의존성을 제거한다.
DW_COLUMNS = (
    "{'ticker':'VARCHAR','trade_date':'BIGINT','base_price':'DOUBLE',"
    "'open_price':'DOUBLE','high_price':'DOUBLE','low_price':'DOUBLE',"
    "'close_price':'DOUBLE','prev_close':'DOUBLE','adjustment_factor':'DOUBLE',"
    "'volume':'DOUBLE','amount':'DOUBLE','shares':'DOUBLE',"
    "'listing_type':'VARCHAR','change_type':'VARCHAR','halt_code':'DOUBLE',"
    "'admin_code':'DOUBLE'}"
)


def require_complete(outcome: Any, label: str) -> Any:
    if outcome.status is not OutcomeStatus.COMPLETE:
        errors = [error.model_dump(mode="json") for error in outcome.errors]
        raise RuntimeError(f"{label} failed: {json.dumps(errors, ensure_ascii=False)}")
    return outcome


def close_at(value: date | pd.Timestamp) -> datetime:
    selected = value.date() if isinstance(value, pd.Timestamp) else value
    return datetime.combine(selected, time(15, 30), tzinfo=KST)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_declared_market_coverage(frame: pd.DataFrame) -> None:
    """Fail if any declared session/universe cell is absent; never shrink the calendar."""

    observed = frame.copy()
    observed["session"] = pd.to_datetime(observed["session"]).dt.date
    expected = pd.MultiIndex.from_product(
        [DECLARED_SESSION_DATES, UNIVERSE],
        names=("session", "instrument"),
    )
    actual = pd.MultiIndex.from_frame(observed[["session", "instrument"]])
    missing = expected.difference(actual)
    unexpected_sessions = sorted(set(observed["session"]) - set(DECLARED_SESSION_DATES))
    if len(missing) or unexpected_sessions:
        missing_preview = [f"{session}:{instrument}" for session, instrument in missing[:10]]
        raise RuntimeError(
            "BOUNDED_MARKET_COVERAGE_INCOMPLETE: "
            f"missing_count={len(missing)}, missing_preview={missing_preview}, "
            f"unexpected_sessions={unexpected_sessions}"
        )
    if observed["close"].isna().any():
        raise RuntimeError("BOUNDED_MARKET_COVERAGE_INCOMPLETE: null close")


def triggered_candidates(strategy: Any, candidates: tuple[datetime, ...]) -> tuple[datetime, ...]:
    """Apply one Strategy-owned schedule policy without exposing Clock or data."""

    policy = strategy.trigger()
    if tuple(policy.requirements()):
        raise RuntimeError("showcase supports schedule-shaped trigger requirements only")
    fired_at: list[datetime] = []
    for index, candidate in enumerate(candidates):
        decision = policy.evaluate(
            TriggerContext(
                candidate_time=candidate,
                candidate_index=index,
                fired_at=tuple(fired_at),
            )
        )
        if decision.accesses:
            raise RuntimeError("schedule-shaped showcase trigger must not access data")
        if decision.decision == "FIRE":
            fired_at.append(candidate)
    return tuple(fired_at)


def extract_bounded_market(source: Path, destination: Path) -> pd.DataFrame:
    """실제 DW에서 고정 universe와 기간만 읽어 portable showcase input을 만든다."""

    quoted = ",".join(repr(instrument) for instrument in UNIVERSE)
    source_sql = source.resolve().as_posix().replace("'", "''")
    connection = duckdb.connect()
    try:
        frame = connection.sql(
            f"""
            SELECT
                ticker AS instrument,
                strptime(CAST(trade_date AS VARCHAR), '%Y%m%d')::DATE AS session,
                close_price AS close
            FROM read_csv('{source_sql}', header=true, columns={DW_COLUMNS})
            WHERE ticker IN ({quoted})
              AND trade_date BETWEEN {SOURCE_START} AND {SOURCE_END}
            ORDER BY session, instrument
            """
        ).df()
    finally:
        connection.close()

    if frame.empty:
        raise RuntimeError("bounded real-DW selection returned no rows")
    frame["session"] = pd.to_datetime(frame["session"])
    if frame.duplicated(["session", "instrument"]).any():
        raise RuntimeError("bounded source contains duplicate instrument/session rows")
    validate_declared_market_coverage(frame)
    if (frame["close"] <= 0).any():
        raise RuntimeError("bounded source contains a non-positive close")

    timestamps = frame["session"].map(close_at)
    frame.insert(2, "observation_time", timestamps.map(datetime.isoformat))
    frame.insert(3, "available_at", timestamps.map(datetime.isoformat))
    frame = frame[
        ["instrument", "session", "observation_time", "available_at", "close"]
    ].sort_values(["session", "instrument"], kind="mergesort")
    frame["session"] = frame["session"].dt.strftime("%Y-%m-%d")
    destination.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(destination, index=False, float_format="%.17g", lineterminator="\n")
    return frame


def register_reproduction_dataset(
    project: QlibxProject,
) -> Any:
    """재현 setup만 담당한다. 아래 두 학습 flow는 registry snapshot부터 시작한다."""

    return require_complete(
        project.register_dataset(
            DatasetRegistration(
                dataset_id=DATASET_ID,
                source="data/two_strategy_market.csv",
                source_format=SourceFormat.CSV,
                instrument_field="instrument",
                observation_time_field="observation_time",
                available_at=AvailableAtField(field="available_at"),
                logical_key=("observation_time", "available_at", "instrument"),
                semantic_bindings={
                    "research_close": "close",
                    "execution_price": "close",
                    "valuation_price": "close",
                },
                semantic_category="bounded_krx_stock_daily_close",
                source_provenance=(
                    "Bounded projection of data/DW/fng_stock_daily_prices.csv. "
                    "This showcase explicitly treats each close as available at the same "
                    "15:30 Asia/Seoul session close."
                ),
            )
        ),
        "reproduction dataset registration",
    )


def portfolio_artifact(
    project: QlibxProject,
    *,
    strategy: PeerMomentumLongShortStrategy,
    decision_time: datetime,
    ordinal: int,
) -> tuple[str, str, Any]:
    strategy_run = require_complete(
        project.invoke(
            strategy,
            StrategyInvocation(
                invocation_id=f"showcase-peer-momentum-{ordinal:02d}-v1",
                evaluation_time=decision_time,
                config_fingerprint="peer-momentum-20-session-groups-v1",
            ),
        ),
        f"peer momentum Strategy {decision_time.date()}",
    )
    strategy_artifact_id = strategy_run.result.artifact.artifact_id
    construction = require_complete(
        project.construct_portfolio(
            PortfolioConstructionRequest(
                invocation_id=f"showcase-peer-portfolio-{ordinal:02d}-v1",
                source_artifact_id=strategy_artifact_id,
                evaluation_time=decision_time,
                config_fingerprint="peer-momentum-hypothetical-signed-v1",
                profile=ConstructionProfile.HYPOTHETICAL_SIGNED,
                requested_budget=1.0,
            )
        ),
        f"peer momentum signed portfolio {decision_time.date()}",
    )
    evidence = construction.diagnostics[0]
    if not hasattr(evidence, "artifact_id"):
        raise RuntimeError("portfolio construction returned no artifact evidence")
    return strategy_artifact_id, str(evidence.artifact_id), strategy_run.result.result


def peer_weight_oracle(prices: pd.DataFrame, decision_time: datetime) -> dict[str, float]:
    """Strategy 구현과 분리된 단순 pandas 산식으로 peer weight를 교차검증한다."""

    window = prices.loc[: pd.Timestamp(decision_time.date())].tail(21)
    if len(window) != 21 or window.isna().any().any():
        raise RuntimeError("academic oracle has an incomplete 21-row window")
    own_returns = window.iloc[-1] / window.iloc[0] - 1.0
    signals: dict[str, float] = {}
    for group in PEER_GROUPS.values():
        for instrument in group:
            peers = [peer for peer in group if peer != instrument]
            signals[instrument] = float(own_returns.loc[peers].mean())
    mean_signal = sum(signals.values()) / len(signals)
    centered = {key: value - mean_signal for key, value in signals.items()}
    gross = sum(abs(value) for value in centered.values())
    return {key: value / gross for key, value in centered.items()}


def run_academic_flow(
    project: QlibxProject,
    *,
    sessions: tuple[datetime, ...],
    prices: pd.DataFrame,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """registered data -> StrategyView -> signed artifact -> AcademicExchange를 추적한다."""

    strategy = PeerMomentumLongShortStrategy(
        dataset_id=DATASET_ID,
        peer_groups=PEER_GROUPS,
    )
    eligible_candidates = tuple(
        candidate
        for candidate in sessions
        if ACADEMIC_CANDIDATE_START <= candidate.date() <= DECISION_END
    )
    fired_candidates = triggered_candidates(strategy, eligible_candidates)
    strategy_artifact_ids: list[str] = []
    portfolio_artifact_ids: list[str] = []
    strategy_results: list[Any] = []
    decision_rows: list[dict[str, Any]] = []
    max_weight_delta = 0.0

    for ordinal, decision_time in enumerate(fired_candidates, start=1):
        strategy_id, portfolio_id, result = portfolio_artifact(
            project,
            strategy=strategy,
            decision_time=decision_time,
            ordinal=ordinal,
        )
        weights = {item.instrument: float(item.weight) for item in result.weights}
        oracle = peer_weight_oracle(prices, decision_time)
        oracle_delta = max(abs(weights[key] - oracle[key]) for key in oracle)
        max_weight_delta = max(max_weight_delta, oracle_delta)
        if oracle_delta > 1e-15:
            raise RuntimeError("peer momentum weights do not match the independent oracle")
        gross = sum(abs(value) for value in weights.values())
        net = sum(weights.values())
        if not math.isclose(gross, 1.0, rel_tol=0, abs_tol=1e-12):
            raise RuntimeError("peer momentum weights are not unit gross")
        if not math.isclose(net, 0.0, rel_tol=0, abs_tol=1e-12):
            raise RuntimeError("peer momentum weights are not net zero")
        if not any(value > 0 for value in weights.values()) or not any(
            value < 0 for value in weights.values()
        ):
            raise RuntimeError("peer momentum did not produce both long and short weights")
        access = result.accesses[0]
        if access.max_available_at is None or access.max_available_at > decision_time:
            raise RuntimeError("peer momentum breached the PIT availability boundary")
        if access.instruments_below_window != 0:
            raise RuntimeError("peer momentum used an incomplete lookback window")
        strategy_artifact_ids.append(strategy_id)
        portfolio_artifact_ids.append(portfolio_id)
        strategy_results.append(result)
        decision_rows.append(
            {
                "decision_time": decision_time.isoformat(),
                "visible_rows": access.row_count,
                "max_available_at": access.max_available_at.isoformat(),
                "snapshot_fingerprint": access.snapshot_fingerprint,
                "gross_weight": gross,
                "net_weight": net,
                "long_names": sum(value > 0 for value in weights.values()),
                "short_names": sum(value < 0 for value in weights.values()),
                "maximum_oracle_weight_delta": oracle_delta,
                "strategy_artifact_id": strategy_id,
                "portfolio_artifact_id": portfolio_id,
            }
        )

    spec = AcademicRunSpec(
        run_id="showcase-peer-momentum-academic-v1",
        portfolio_artifact_ids=tuple(portfolio_artifact_ids),
        initial_nav=INITIAL_NAV,
        base_currency="KRW",
        # Academic 경로에는 add_instrument가 없다. exact listing이 이 venue의 종목 계약이다.
        listings=tuple(
            AcademicInstrumentListing(
                instrument_id=instrument,
                kind=AcademicInstrumentKind.STOCK,
                currency="KRW",
                dataset_id=DATASET_ID,
                price_role="execution_price",
                price_semantics=AcademicPriceSemantics.TRADED_REFERENCE,
            )
            for instrument in UNIVERSE
        ),
        session_closes=sessions,
    )
    academic = require_complete(
        project.run_academic(spec, resume=True),
        "peer momentum AcademicExchange run",
    )

    fill_count = 0
    negative_position_observed = False
    for result, execution_id, row in zip(
        strategy_results,
        academic.result.execution_artifact_ids,
        decision_rows,
        strict=True,
    ):
        loaded = require_complete(
            project.load_artifact(execution_id, ACADEMIC_EXECUTION_CONTRACT),
            "academic execution artifact load",
        )
        match = loaded.result.payload.match
        fill_count += len(match.fills)
        negative_position_observed |= any(
            position.quantity < 0 for position in match.after.positions
        )
        target = {item.instrument_id: item.weight for item in match.target_weights}
        expected = {item.instrument: item.weight for item in result.weights}
        delta = max(abs(target[key] - expected[key]) for key in expected)
        if delta > 1e-15:
            raise RuntimeError("AcademicExchange targets differ from Strategy weights")
        row.update(
            {
                "execution_time": match.event_time.isoformat(),
                "execution_artifact_id": execution_id,
                "fill_count": len(match.fills),
                "nav_after": match.after.nav,
                "turnover": match.turnover,
            }
        )

    if not negative_position_observed:
        raise RuntimeError("AcademicExchange produced no negative position")
    if academic.result.total_cost != 0:
        raise RuntimeError("academic v1 must serialize zero total cost")
    return (
        {
            "decision_count": len(decision_rows),
            "fill_count": fill_count,
            "final_nav": academic.result.final_snapshot.nav,
            "total_turnover": academic.result.total_turnover,
            "total_cost": academic.result.total_cost,
            "negative_position_observed": negative_position_observed,
            "maximum_independent_oracle_weight_delta": max_weight_delta,
            "maximum_strategy_to_exchange_weight_delta": 0.0,
            "final_checkpoint_artifact_id": academic.result.final_checkpoint_artifact_id,
            "strategy_artifact_ids": strategy_artifact_ids,
            "portfolio_artifact_ids": portfolio_artifact_ids,
            "execution_artifact_ids": list(academic.result.execution_artifact_ids),
            "limitations": list(academic.result.limitations),
        },
        decision_rows,
    )


def run_krx_flow(
    project: QlibxProject,
    *,
    sessions: tuple[datetime, ...],
    prices: pd.DataFrame,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """registered data -> add_instrument -> frozen spec -> KRX/Account를 추적한다."""

    # Instrument는 dataset row가 아니다. 주문 lot/currency/venue 의미를 가진 실행 계약이다.
    for instrument in UNIVERSE:
        project.add_instrument(
            StockInstrument(
                instrument_id=instrument,
                exchange_id="XKRX",
                currency="KRW",
                lot_size=1,
            )
        )
    project.set_exchange(
        KrxExchangeConfig(
            schedule_version="showcase-explicit-stock-cost-v1",
            cost_rules=tuple(
                CostRule(
                    rule_id=f"showcase-stock-{side.value.lower()}-v1",
                    product_type="stock",
                    side=side,
                    effective_from=datetime(2020, 1, 1, tzinfo=KST),
                    rate=0.0003,
                    minimum_cost=0,
                )
                for side in Side
            ),
        )
    )
    strategy_path = Path(__file__).with_name("strategies.py")
    flow_sessions = tuple(
        candidate
        for candidate in sessions
        if KRX_CANDIDATE_START <= candidate.date() <= KRX_FLOW_END
    )
    spec = project.daily_spec(
        run_id="showcase-five-session-top-ten-krx-v1",
        strategy_fingerprint=sha256(strategy_path),
        account=DailyAccountSeed(
            account_id="showcase-top-ten-account",
            base_currency="KRW",
            initial_cash=INITIAL_NAV,
        ),
        market=DailyMarketBinding(market_dataset_id=DATASET_ID),
        session_closes=flow_sessions,
    )
    if tuple(item.instrument_id for item in spec.instruments) != UNIVERSE:
        raise RuntimeError("daily_spec did not freeze the incrementally added instruments")

    strategy = FiveSessionTopTenStrategy(dataset_id=DATASET_ID, instruments=UNIVERSE)
    outcome = require_complete(
        # 첫 실행은 checkpoint resume가 아니라 명시적인 fresh simulation이다.
        project.run_daily(strategy, spec, resume=False),
        "five-session top-ten KRX run",
    )
    result = outcome.result
    decision_rows: list[dict[str, Any]] = []
    for strategy_result in result.strategy_results:
        decision_time = strategy_result.evaluation_time
        weights = {item.instrument: float(item.weight) for item in strategy_result.weights}
        if len(weights) != 10 or any(value != 0.1 for value in weights.values()):
            raise RuntimeError("KRX Strategy did not produce ten equal 10% targets")
        window = prices.loc[: pd.Timestamp(decision_time.date())].tail(6)
        if len(window) != 6 or window.isna().any().any():
            raise RuntimeError("KRX oracle has an incomplete 6-row window")
        trailing = window.iloc[-1] / window.iloc[0] - 1.0
        expected = tuple(
            sorted(UNIVERSE, key=lambda item: (-float(trailing.loc[item]), item))[:10]
        )
        if set(weights) != set(expected):
            raise RuntimeError("KRX top-ten selection differs from the independent oracle")
        access = strategy_result.accesses[0]
        if access.max_available_at is None or access.max_available_at > decision_time:
            raise RuntimeError("KRX Strategy breached the PIT availability boundary")
        if access.instruments_below_window != 0:
            raise RuntimeError("KRX Strategy used an incomplete lookback window")
        decision_rows.append(
            {
                "decision_time": decision_time.isoformat(),
                "selected_instruments": "|".join(sorted(weights)),
                "selected_count": len(weights),
                "weight_each": 0.1,
                "visible_rows": access.row_count,
                "max_available_at": access.max_available_at.isoformat(),
                "snapshot_fingerprint": access.snapshot_fingerprint,
            }
        )

    fill_rows = []
    for execution in result.executions:
        for fill, diagnostic in zip(
            execution.fills, execution.diagnostics, strict=True
        ):
            fill_rows.append(
                {
                    "event_time": execution.event_time.isoformat(),
                    "event_id": execution.event_id,
                    "instrument": fill.instrument_id,
                    "side": fill.side.value,
                    "requested_quantity": fill.requested_quantity,
                    "dealt_quantity": fill.dealt_quantity,
                    "price": fill.price,
                    "trade_value": fill.trade_value,
                    "total_cost": fill.total_cost,
                    "diagnostic_reasons": "|".join(diagnostic.reasons),
                }
            )
    final_positions = {
        position.instrument_id: position.quantity
        for position in result.final_account.positions
        if position.quantity != 0
    }
    return (
        {
            "configured_instrument_count": len(project.configured_instruments),
            "frozen_instrument_count": len(spec.instruments),
            "decision_count": len(result.strategy_results),
            "execution_count": len(result.executions),
            "fill_record_count": len(fill_rows),
            "positive_fill_count": sum(row["dealt_quantity"] > 0 for row in fill_rows),
            "zero_dealt_fill_record_count": sum(
                row["dealt_quantity"] == 0 for row in fill_rows
            ),
            "total_cost": sum(row["total_cost"] for row in fill_rows),
            "final_cash": result.final_account.cash,
            "final_positions": final_positions,
            "checkpoint_run_id": result.checkpoint.run_id,
            "artifact_types": sorted(
                {artifact.artifact_type for artifact in result.artifacts}
            ),
            "all_top_ten_decisions_match_independent_oracle": True,
        },
        decision_rows,
        fill_rows,
    )


def run(repo_root: Path) -> dict[str, Any]:
    showcase_root = Path(__file__).resolve().parent
    output_root = showcase_root / "outputs"
    project_root = output_root / "project-trigger-v1"
    bounded_path = project_root / "data" / "two_strategy_market.csv"
    source = repo_root / "data" / "DW" / "fng_stock_daily_prices.csv"
    if not source.is_file():
        raise FileNotFoundError(f"required real-DW source is missing: {source}")

    bounded = extract_bounded_market(source, bounded_path)
    QlibxProject.init(project_root, apply=True)
    project = QlibxProject.open(project_root)
    registration = register_reproduction_dataset(project)
    registered = project.registry_snapshot().get(DATASET_ID)
    if registered is None or registered.query_snapshot is None:
        raise RuntimeError("registered dataset has no immutable query snapshot")

    sessions = tuple(close_at(value) for value in DECLARED_SESSION_DATES)
    price_frame = bounded.copy()
    price_frame["session"] = pd.to_datetime(price_frame["session"])
    prices = price_frame.pivot(
        index="session", columns="instrument", values="close"
    ).sort_index()
    academic, academic_rows = run_academic_flow(
        project, sessions=sessions, prices=prices
    )
    krx, krx_rows, fill_rows = run_krx_flow(
        project, sessions=sessions, prices=prices
    )

    summary = {
        "showcase_id": SHOWCASE_ID,
        "status": "complete",
        "verified_against": f"qlibx-{version('qlibx')}+implementations-061-through-066",
        "dataset": {
            "dataset_id": DATASET_ID,
            "source": str(source.relative_to(repo_root).as_posix()),
            "source_size_bytes": source.stat().st_size,
            "source_sha256": sha256(source),
            "bounded_path": str(bounded_path.relative_to(showcase_root).as_posix()),
            "bounded_sha256": sha256(bounded_path),
            "row_count": int(registration.result.evidence.row_count),
            "session_count": len(sessions),
            "instrument_count": len(UNIVERSE),
            "registration_identity": registered.registration_identity,
            "query_snapshot_fingerprint": registered.query_snapshot.fingerprint,
            "availability_assumption": "same-session 15:30 Asia/Seoul close",
        },
        "academic_peer_momentum": academic,
        "krx_five_session_top_ten": krx,
        "boundaries": {
            "dataset_registration": "reproduction setup; taught flow starts from registry snapshot",
            "academic_instruments": "AcademicRunSpec.listings",
            "krx_instruments": "QlibxProject.add_instrument -> daily_spec frozen copy",
            "academic_short": "hypothetical only; no borrow, locate, margin, or real short claim",
            "krx_direction": "physical long-only current profile",
        },
    }
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
        newline="\n",
    )
    pd.DataFrame(academic_rows).to_csv(
        output_root / "academic_rebalances.csv", index=False, lineterminator="\n"
    )
    pd.DataFrame(krx_rows).to_csv(
        output_root / "krx_decisions.csv", index=False, lineterminator="\n"
    )
    pd.DataFrame(fill_rows).to_csv(
        output_root / "krx_fills.csv", index=False, lineterminator="\n"
    )
    trace = [
        "[0] 재현 setup: real-DW bounded projection -> minimal dataset registration",
        (
            f"[1] 공통 시작점: registry snapshot {registered.registration_identity[:12]} / "
            f"query snapshot {registered.query_snapshot.fingerprint[:12]}"
        ),
        (
            "[2A] Academic: requirement -> 21-row PIT history -> peer signal -> "
            "signed StrategyResult:v3"
        ),
        (
            "[3A] Academic: hypothetical_signed portfolio -> exact listing/next-close "
            "quote -> fractional signed Fill -> academic checkpoint"
        ),
        "[2K] KRX: add_instrument x20 -> set_exchange -> daily_spec가 실행 환경을 값으로 동결",
        (
            "[3K] KRX: Strategy EveryNSessions(5) -> FIRE/SKIP -> "
            "6-row PIT history -> top 10 DecisionIntent"
        ),
        (
            "[4K] KRX: next-close preparation -> KrxExchange -> integer Fill/cost -> "
            "Account commit -> mark/performance/checkpoint"
        ),
    ]
    (output_root / "flow_trace_ko.txt").write_text(
        "\n".join(trace) + "\n", encoding="utf-8", newline="\n"
    )
    return summary


if __name__ == "__main__":
    root = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).parents[2]).resolve()
    print(json.dumps(run(root), ensure_ascii=False, indent=2, sort_keys=True))
