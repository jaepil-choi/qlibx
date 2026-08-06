from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from qlibx import (
    DailyAccountSeed,
    DailyMarketBinding,
    DailySimulationSpec,
    OutcomeStatus,
    QlibxProject,
)
from qlibx.data import AvailableAtField, DatasetRegistration, SourceFormat
from qlibx.errors import CommitStatus
from qlibx.execution import CostRule, KrxExchangeConfig, Side, StockInstrument
from qlibx.operations import BudgetMode, DecisionAction, StrategyDraft, WeightEntry

KST = ZoneInfo("Asia/Seoul")


class RebalanceThenFailStrategy:
    strategy_id = "test.public-daily-rebalance"

    def requirements(self) -> tuple[object, ...]:
        return ()

    def run(self, view: object) -> StrategyDraft:
        account = view.account_snapshot()  # type: ignore[attr-defined]
        view.account_feedback()  # type: ignore[attr-defined]
        selected = "A000002" if account.positions else "A000001"
        return StrategyDraft(
            weights=(WeightEntry(instrument=selected, weight=1.0),),
            budget_mode=BudgetMode.FIXED,
            target_gross=1.0,
            decision_action=DecisionAction.TARGET,
        )


class PublicDailyStrategy:
    strategy_id = "test.public-daily"

    def requirements(self) -> tuple[object, ...]:
        return ()

    def run(self, view: object) -> StrategyDraft:
        account = view.account_snapshot()  # type: ignore[attr-defined]
        feedback = view.account_feedback()  # type: ignore[attr-defined]
        if account.positions:
            assert feedback.next_cursor > feedback.after_cursor
            return StrategyDraft(
                weights=(),
                budget_mode=BudgetMode.FLEXIBLE,
                target_gross=1.0,
                decision_action=DecisionAction.HOLD,
            )
        return StrategyDraft(
            weights=(WeightEntry(instrument="A000001", weight=1.0),),
            budget_mode=BudgetMode.FIXED,
            target_gross=1.0,
            decision_action=DecisionAction.TARGET,
        )


def at(day: int) -> datetime:
    return datetime(2024, 1, day, 15, 30, tzinfo=KST)


def spec(**updates: object) -> DailySimulationSpec:
    payload: dict[str, object] = {
        "run_id": "public-daily-run",
        "strategy_fingerprint": "test-public-daily-v1",
        "account": DailyAccountSeed(
            account_id="public-account",
            base_currency="KRW",
            initial_cash=10_000,
        ),
        "instruments": tuple(
            StockInstrument(
                instrument_id=instrument,
                exchange_id="XKRX",
                currency="KRW",
                lot_size=1,
            )
            for instrument in ("A000001", "A000002")
        ),
        "exchange": KrxExchangeConfig(
            schedule_version="test-cost-v1",
            cost_rules=tuple(
                CostRule(
                    rule_id=f"stock-{side.value.lower()}",
                    product_type="stock",
                    side=side,
                    effective_from=datetime(2020, 1, 1, tzinfo=KST),
                    rate=0,
                    minimum_cost=0,
                )
                for side in Side
            ),
        ),
        "market": DailyMarketBinding(market_dataset_id="public-market"),
        "decision_times": (at(2), at(4)),
        "session_closes": (at(2), at(3), at(4), at(5)),
    }
    payload.update(updates)
    return DailySimulationSpec.model_validate(payload)


def project(tmp_path: Path) -> QlibxProject:
    root = tmp_path / "public-project"
    QlibxProject.init(root, apply=True)
    market = root / "market.csv"
    market.write_text(
        "date,available_at,ticker,close\n"
        "2024-01-02T09:00:00+09:00,2024-01-02T15:30:00+09:00,A000001,100\n"
        "2024-01-02T09:00:00+09:00,2024-01-02T15:30:00+09:00,A000002,100\n"
        "2024-01-03T09:00:00+09:00,2024-01-03T15:30:00+09:00,A000001,100\n"
        "2024-01-03T09:00:00+09:00,2024-01-03T15:30:00+09:00,A000002,100\n"
        "2024-01-04T09:00:00+09:00,2024-01-04T15:30:00+09:00,A000001,101\n"
        "2024-01-04T09:00:00+09:00,2024-01-04T15:30:00+09:00,A000002,99\n"
        "2024-01-05T09:00:00+09:00,2024-01-05T15:30:00+09:00,A000001,102\n"
        "2024-01-05T09:00:00+09:00,2024-01-05T15:30:00+09:00,A000002,100\n",
        encoding="utf-8",
    )
    selected = QlibxProject.open(root)
    outcome = selected.register_dataset(
        DatasetRegistration(
            dataset_id="public-market",
            source="market.csv",
            source_format=SourceFormat.CSV,
            instrument_field="ticker",
            observation_time_field="date",
            available_at=AvailableAtField(field="available_at"),
            logical_key=("date", "available_at", "ticker"),
            semantic_bindings={
                "execution_price": "close",
                "valuation_price": "close",
            },
            source_provenance="bounded public daily facade fixture",
        )
    )
    assert outcome.status is OutcomeStatus.COMPLETE
    return selected


def test_public_daily_facade_runs_closed_loop(tmp_path: Path) -> None:
    outcome = project(tmp_path).run_daily(PublicDailyStrategy(), spec())

    assert outcome.status is OutcomeStatus.COMPLETE
    assert len(outcome.result.strategy_results) == 2
    assert len(outcome.result.executions) == 1
    assert outcome.result.final_account.positions[0].quantity == 100
    assert outcome.result.strategy_results[1].feedback_accesses[0].next_cursor == 2
    assert outcome.result.checkpoint.config_fingerprint == spec().frozen_config_fingerprint()


def test_public_daily_spec_rejects_runtime_capability_overclaims() -> None:
    base = spec().model_dump(mode="python")
    base["exchange"]["participation_rate"] = 0.1
    with pytest.raises(ValidationError, match="does not support volume participation"):
        DailySimulationSpec.model_validate(base)

    base = spec().model_dump(mode="python")
    base["exchange"]["impact_rate"] = 0.001
    with pytest.raises(ValidationError, match="does not support market impact"):
        DailySimulationSpec.model_validate(base)


def test_public_daily_spec_rejects_inconsistent_instrument_authority() -> None:
    duplicate = spec().model_dump(mode="python")
    duplicate["instruments"] = (
        duplicate["instruments"][0],
        duplicate["instruments"][0],
    )
    with pytest.raises(ValidationError, match="instruments must be unique"):
        DailySimulationSpec.model_validate(duplicate)

    wrong_currency = spec().model_dump(mode="python")
    wrong_currency["account"]["base_currency"] = "USD"
    with pytest.raises(ValidationError, match="currency must match"):
        DailySimulationSpec.model_validate(wrong_currency)

    wrong_exchange = spec().model_dump(mode="python")
    wrong_exchange["instruments"][0]["exchange_id"] = "OTHER"
    with pytest.raises(ValidationError, match="exchange_id must match"):
        DailySimulationSpec.model_validate(wrong_exchange)

    unsupported = spec().model_dump(mode="python")
    unsupported["instruments"] = (
        {
            "kind": "index",
            "instrument_id": "K200",
            "exchange_id": "XKRX",
            "currency": "KRW",
            "tracking_only": True,
        },
    )
    with pytest.raises(ValidationError, match="union_tag_invalid"):
        DailySimulationSpec.model_validate(unsupported)


def test_public_daily_is_deterministic_and_resumable(tmp_path: Path) -> None:
    selected = project(tmp_path)
    selected_spec = spec()

    first = selected.run_daily(PublicDailyStrategy(), selected_spec)
    repeated = selected.run_daily(PublicDailyStrategy(), selected_spec)
    resumed = selected.run_daily(PublicDailyStrategy(), selected_spec, resume=True)

    assert first.status is repeated.status is resumed.status is OutcomeStatus.COMPLETE
    assert (
        first.result.final_account
        == repeated.result.final_account
        == resumed.result.final_account
    )
    assert tuple(item.artifact_id for item in first.result.artifacts) == tuple(
        item.artifact_id for item in repeated.result.artifacts
    )
    assert {item.artifact_id for item in first.result.artifacts} == {
        item.artifact_id for item in resumed.result.artifacts
    }

    changed = spec(strategy_fingerprint="test-public-daily-v2")
    rejected = selected.run_daily(PublicDailyStrategy(), changed, resume=True)
    assert rejected.status is OutcomeStatus.FAILED
    assert rejected.errors[0].error_code == "RESUME_BRANCH_REQUIRED"
    assert rejected.errors[0].commit_status is CommitStatus.NONE


def test_public_daily_missing_market_role_fails_before_account_commit(tmp_path: Path) -> None:
    selected = project(tmp_path)
    missing = spec(
        market=DailyMarketBinding(
            market_dataset_id="public-market",
            execution_price_role="missing_execution_price",
        )
    )

    outcome = selected.run_daily(PublicDailyStrategy(), missing)

    assert outcome.status is OutcomeStatus.FAILED
    assert any(error.error_code == "REQUIREMENT_NOT_RESOLVED" for error in outcome.errors)
    assert all(error.commit_status is CommitStatus.NONE for error in outcome.errors)
    assert not any(
        artifact.artifact_type == "execution_result" for artifact in outcome.diagnostics
    )


def test_public_daily_missing_initial_buy_cost_fails_before_account_commit(
    tmp_path: Path,
) -> None:
    selected = project(tmp_path)
    sell_only = KrxExchangeConfig(
        schedule_version="sell-only-cost-v1",
        cost_rules=(
            CostRule(
                rule_id="stock-sell-only",
                product_type="stock",
                side=Side.SELL,
                effective_from=datetime(2020, 1, 1, tzinfo=KST),
                rate=0,
                minimum_cost=0,
            ),
        ),
    )

    outcome = selected.run_daily(PublicDailyStrategy(), spec(exchange=sell_only))

    assert outcome.status is OutcomeStatus.FAILED
    missing = next(
        error for error in outcome.errors if error.error_code == "EXACT_COST_RULE_MISSING"
    )
    assert missing.commit_status is CommitStatus.NONE
    assert not any(
        artifact.artifact_type == "execution_result" for artifact in outcome.diagnostics
    )


def test_public_daily_missing_later_sell_cost_preserves_prior_evidence(
    tmp_path: Path,
) -> None:
    selected = project(tmp_path)
    buy_only = KrxExchangeConfig(
        schedule_version="buy-only-cost-v1",
        cost_rules=(
            CostRule(
                rule_id="stock-buy-only",
                product_type="stock",
                side=Side.BUY,
                effective_from=datetime(2020, 1, 1, tzinfo=KST),
                rate=0,
                minimum_cost=0,
            ),
        ),
    )

    outcome = selected.run_daily(
        RebalanceThenFailStrategy(),
        spec(exchange=buy_only, strategy_fingerprint="rebalance-missing-sell-v1"),
    )

    assert outcome.status is OutcomeStatus.FAILED
    missing = next(
        error for error in outcome.errors if error.error_code == "EXACT_COST_RULE_MISSING"
    )
    assert missing.commit_status is CommitStatus.NONE
    assert any(
        artifact.artifact_type == "execution_result" for artifact in outcome.diagnostics
    )
    assert any(
        artifact.artifact_type == "simulation_recovery_point"
        for artifact in selected.artifacts.list_envelopes()
    )