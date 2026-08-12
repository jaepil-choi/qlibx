"""Compare exact frozen next-close and next-open execution children."""

import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from qlibx import (
    BudgetMode,
    CostRule,
    DailyAccountSeed,
    DailyMarketBinding,
    DailySimulationSpec,
    DecisionAction,
    EveryNSessions,
    FrozenDailyExecutionSpec,
    KrxExchangeConfig,
    OutcomeStatus,
    QlibxProject,
    Side,
    StockInstrument,
    StrategyDraft,
    WeightEntry,
)
from qlibx.data import DatasetRegistration

KST = ZoneInfo("Asia/Seoul")


def at_open(day: int) -> datetime:
    return datetime(2024, 1, day, 9, 0, tzinfo=KST)


def at_close(day: int) -> datetime:
    return datetime(2024, 1, day, 15, 30, tzinfo=KST)


class CountingParentStrategy:
    strategy_id = "sample.execution-convention-parent"

    def __init__(self) -> None:
        self.calls = 0

    def requirements(self) -> tuple[object, ...]:
        return ()

    def trigger(self) -> EveryNSessions:
        return EveryNSessions(n=2)

    def run(self, view: object) -> StrategyDraft:
        self.calls += 1
        return StrategyDraft(
            weights=(WeightEntry(instrument="A000001", weight=1.0),),
            budget_mode=BudgetMode.FIXED,
            target_gross=1.0,
            decision_action=DecisionAction.TARGET,
        )


def require_complete(outcome: object, label: str) -> object:
    if outcome.status is not OutcomeStatus.COMPLETE:  # type: ignore[attr-defined]
        raise RuntimeError(f"{label} failed: {outcome.errors}")  # type: ignore[attr-defined]
    return outcome


def instruments() -> tuple[StockInstrument, ...]:
    return tuple(
        StockInstrument(
            instrument_id=instrument,
            exchange_id="XKRX",
            currency="KRW",
            lot_size=1,
        )
        for instrument in ("A000001", "A000002")
    )


def exchange() -> KrxExchangeConfig:
    return KrxExchangeConfig(
        schedule_version="sample-execution-convention-v1",
        cost_rules=tuple(
            CostRule(
                rule_id=f"sample-stock-{side.value.lower()}",
                product_type="stock",
                side=side,
                effective_from=datetime(2020, 1, 1, tzinfo=KST),
                rate=0,
                minimum_cost=0,
            )
            for side in Side
        ),
    )


def market(price_role: str) -> DailyMarketBinding:
    return DailyMarketBinding(
        market_dataset_id="sample-execution-events",
        execution_price_role=price_role,
        valuation_price_role="valuation_price",
    )


def child_spec(
    *,
    run_id: str,
    account_id: str,
    parent_artifact_id: str,
    timing: str,
    price_role: str,
) -> FrozenDailyExecutionSpec:
    return FrozenDailyExecutionSpec(
        run_id=run_id,
        parent_decision_artifact_ids=(parent_artifact_id,),
        account=DailyAccountSeed(
            account_id=account_id,
            base_currency="KRW",
            initial_cash=10_000,
        ),
        instruments=instruments(),
        exchange=exchange(),
        market=market(price_role),
        execution_timing=timing,
        session_closes=(at_close(3),),
        session_opens=(at_open(3),) if timing == "next_session_open" else (),
    )


def execution_summary(outcome: object) -> dict[str, object]:
    result = outcome.result  # type: ignore[attr-defined]
    execution = result.executions[0]
    execution_artifact = next(
        item for item in result.artifacts if item.artifact_type == "execution_result"
    )
    fill = execution.fills[0]
    return {
        "profile_id": execution.profile_id,
        "convention_id": execution.convention_id,
        "event_time": execution.event_time.isoformat(),
        "price_role": execution.sizing_price_role,
        "price": fill.price,
        "quantity": fill.dealt_quantity,
        "account_before": execution.account_before.account_id,
        "account_after": execution.account_after.account_id,
        "strategy_result_count": len(result.strategy_results),
        "strategy_state": result.final_strategy_state,
        "decision_dependency_ids": [
            edge.dependency_id
            for edge in execution_artifact.dependencies
            if edge.consumer_role == "decision_intent"
        ],
        "dataset_dependency_roles": sorted(
            edge.consumer_role
            for edge in execution_artifact.dependencies
            if edge.dependency_kind == "dataset"
        ),
    }


def main(project_root: Path) -> dict[str, object]:
    sample_dir = Path(__file__).resolve().parent
    project = QlibxProject.open(project_root)
    registration = yaml.safe_load(
        (sample_dir / "registration.yaml").read_text(encoding="utf-8")
    )
    if project.registry_snapshot().get("sample-execution-events") is None:
        require_complete(
            project.register_dataset(
                DatasetRegistration.model_validate_json(
                    json.dumps(registration, ensure_ascii=False)
                )
            ),
            "execution event registration",
        )

    strategy = CountingParentStrategy()
    parent = require_complete(
        project.run_daily(
            strategy,
            DailySimulationSpec(
                run_id="sample-execution-convention-parent",
                strategy_fingerprint="sample-execution-convention-parent-v1",
                account=DailyAccountSeed(
                    account_id="sample-parent-account",
                    base_currency="KRW",
                    initial_cash=10_000,
                ),
                instruments=instruments(),
                exchange=exchange(),
                market=market("close_execution_price"),
                session_closes=(at_close(2), at_close(3)),
            ),
        ),
        "parent daily run",
    )
    parent_artifact = next(
        item
        for item in parent.result.artifacts
        if item.artifact_type == "decision_intent"
    )
    loaded_before = project.artifacts.load_envelope(parent_artifact.artifact_id)
    require_complete(loaded_before, "parent envelope before children")
    calls_before = strategy.calls

    close_child = require_complete(
        project.execute_frozen_daily(
            child_spec(
                run_id="sample-next-close-child",
                account_id="sample-next-close-account",
                parent_artifact_id=parent_artifact.artifact_id,
                timing="next_session_close",
                price_role="close_execution_price",
            )
        ),
        "next-close child",
    )
    open_child = require_complete(
        project.execute_frozen_daily(
            child_spec(
                run_id="sample-next-open-child",
                account_id="sample-next-open-account",
                parent_artifact_id=parent_artifact.artifact_id,
                timing="next_session_open",
                price_role="open_execution_price",
            )
        ),
        "next-open child",
    )
    future_hidden = project.execute_frozen_daily(
        child_spec(
            run_id="sample-future-hidden-open-child",
            account_id="sample-future-hidden-open-account",
            parent_artifact_id=parent_artifact.artifact_id,
            timing="next_session_open",
            price_role="close_execution_price",
        )
    )
    if future_hidden.status is not OutcomeStatus.FAILED:
        raise RuntimeError("close-available price unexpectedly executed at the open event")

    loaded_after = project.artifacts.load_envelope(parent_artifact.artifact_id)
    require_complete(loaded_after, "parent envelope after children")
    return {
        "parent_artifact_id": parent_artifact.artifact_id,
        "parent_content_hash_before": loaded_before.result.content_hash,
        "parent_content_hash_after": loaded_after.result.content_hash,
        "producer_calls_before_children": calls_before,
        "producer_calls_after_children": strategy.calls,
        "close_child": execution_summary(close_child),
        "open_child": execution_summary(open_child),
        "future_hidden_failure_code": future_hidden.errors[0].error_code,
        "future_hidden_commit_status": future_hidden.errors[0].commit_status.value,
        "future_hidden_execution_artifacts": sum(
            item.artifact_type == "execution_result" for item in future_hidden.diagnostics
        ),
    }


if __name__ == "__main__":
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    print(json.dumps(main(root), ensure_ascii=False, indent=2, sort_keys=True))
