import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml
from strategy import SampleDailyFeedbackStrategy

from qlibx import (
    DailyAccountSeed,
    DailyMarketBinding,
    DailySimulationSpec,
    OutcomeStatus,
    QlibxProject,
)
from qlibx.data import DatasetRegistration
from qlibx.execution import CostRule, KrxExchangeConfig, Side, StockInstrument

KST = ZoneInfo("Asia/Seoul")


def close_at(day: int) -> datetime:
    return datetime(2024, 1, day, 15, 30, tzinfo=KST)


def require_complete(outcome: object, label: str) -> object:
    if outcome.status is not OutcomeStatus.COMPLETE:  # type: ignore[attr-defined]
        raise RuntimeError(f"{label} failed: {outcome.errors}")  # type: ignore[attr-defined]
    return outcome


def main(project_root: Path) -> dict[str, object]:
    sample_dir = Path(__file__).resolve().parent
    project = QlibxProject.open(project_root)
    registration_payload = yaml.safe_load(
        (sample_dir / "registration.yaml").read_text(encoding="utf-8")
    )
    if project.registry_snapshot().get("sample-daily-market") is None:
        require_complete(
            project.register_dataset(
                DatasetRegistration.model_validate_json(
                    json.dumps(registration_payload, ensure_ascii=False)
                )
            ),
            "sample daily registration",
        )

    strategy_path = sample_dir / "strategy.py"
    strategy_fingerprint = hashlib.sha256(strategy_path.read_bytes()).hexdigest()
    sessions = tuple(close_at(day) for day in (2, 3, 4, 5))
    outcome = require_complete(
        project.run_daily(
            SampleDailyFeedbackStrategy(),
            DailySimulationSpec(
                run_id="sample-daily-closed-loop",
                strategy_fingerprint=strategy_fingerprint,
                account=DailyAccountSeed(
                    account_id="sample-daily-account",
                    base_currency="KRW",
                    initial_cash=10_000_000,
                ),
                instruments=tuple(
                    StockInstrument(
                        instrument_id=instrument,
                        exchange_id="XKRX",
                        currency="KRW",
                        lot_size=1,
                    )
                    for instrument in ("A000660", "A005930")
                ),
                exchange=KrxExchangeConfig(
                    schedule_version="sample-daily-cost-v1",
                    cost_rules=tuple(
                        CostRule(
                            rule_id=f"sample-stock-{side.value.lower()}",
                            product_type="stock",
                            side=side,
                            effective_from=datetime(2020, 1, 1, tzinfo=KST),
                            rate=0.0015,
                            minimum_cost=0,
                        )
                        for side in Side
                    ),
                ),
                market=DailyMarketBinding(
                    market_dataset_id="sample-daily-market"
                ),
                decision_times=(sessions[0], sessions[2]),
                session_closes=sessions,
            ),
        ),
        "sample daily simulation",
    )
    result = outcome.result
    return {
        "selected_instruments": [
            next(item.instrument for item in record.weights if item.weight > 0)
            for record in result.strategy_results
        ],
        "execution_count": len(result.executions),
        "fills": [
            {
                "instrument": fill.instrument_id,
                "side": fill.side.value,
                "quantity": fill.dealt_quantity,
                "price": fill.price,
                "cost": fill.total_cost,
            }
            for execution in result.executions
            for fill in execution.fills
        ],
        "feedback_ranges": [
            [access.after_cursor, access.next_cursor]
            for record in result.strategy_results
            for access in record.feedback_accesses
        ],
        "session_returns": [
            record.portfolio_return for record in result.session_performance
        ],
        "final_cash": result.final_account.cash,
        "final_positions": {
            item.instrument_id: item.quantity
            for item in result.final_account.positions
        },
        "checkpoint_run_id": result.checkpoint.run_id,
        "artifact_types": sorted(
            {envelope.artifact_type for envelope in result.artifacts}
        ),
    }


if __name__ == "__main__":
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    print(json.dumps(main(root), ensure_ascii=False, indent=2, sort_keys=True))