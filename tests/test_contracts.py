from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from qlibx import (
    ConstraintMonitoringSpec,
    CostRule,
    DailyAccountSeed,
    DailyMarketBinding,
    DailySimulationSpec,
    EtfInstrument,
    KrxExchangeConfig,
    MvpConstraintPolicy,
    OperationError,
    OperationOutcome,
    OutcomeStatus,
    QlibxModel,
    Side,
    StockInstrument,
)


class ExampleBoundary(QlibxModel):
    count: int


def make_error(**overrides: Any) -> OperationError:
    values: dict[str, Any] = {
        "operation": "dataset.register",
        "stage_path": "dataset.register.schema",
        "error_code": "SCHEMA_VALIDATION_FAILED",
        "idempotency_identity": "invocation-1",
        "error_id": "error-1",
    }
    values.update(overrides)
    return OperationError.model_validate(values)


def test_boundary_models_are_strict_and_frozen() -> None:
    with pytest.raises(ValidationError):
        ExampleBoundary.model_validate({"count": "1"})

    model = ExampleBoundary(count=1)
    with pytest.raises(ValidationError):
        model.count = 2


def test_complete_outcome_cannot_hide_error_evidence() -> None:
    with pytest.raises(ValueError, match="complete outcome"):
        OperationOutcome(status=OutcomeStatus.COMPLETE, errors=(make_error(),))


@pytest.mark.parametrize("status", [OutcomeStatus.FAILED, OutcomeStatus.UNSUPPORTED])
def test_failure_outcome_requires_error_evidence(status: OutcomeStatus) -> None:
    with pytest.raises(ValueError, match="requires error evidence"):
        OperationOutcome(status=status)


def test_operation_error_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        make_error(guessed_resolution="use DATE as available_at")


def test_future_intraday_types_are_not_current_flow_exports() -> None:
    import qlibx.flow as flow

    assert "IntradayExecutionFlow" not in flow.__all__
    assert not hasattr(flow, "IntradayExecutionFlow")


def test_top_level_exports_construct_daily_and_monitoring_specs() -> None:
    kst = ZoneInfo("Asia/Seoul")
    effective_from = datetime(2024, 1, 1, tzinfo=kst)
    session_close = datetime(2024, 1, 2, 15, 30, tzinfo=kst)
    instruments = (
        StockInstrument(
            instrument_id="A005930",
            exchange_id="XKRX",
            currency="KRW",
            lot_size=1,
        ),
        EtfInstrument(
            instrument_id="A069500",
            exchange_id="XKRX",
            currency="KRW",
            lot_size=1,
        ),
    )
    exchange = KrxExchangeConfig(
        schedule_version="top-level-smoke-v1",
        cost_rules=tuple(
            CostRule(
                rule_id=f"{product}-{side.value.lower()}",
                product_type=product,
                side=side,
                effective_from=effective_from,
                rate=0,
                minimum_cost=0,
            )
            for product in ("stock", "etf")
            for side in Side
        ),
    )

    daily = DailySimulationSpec(
        run_id="top-level-daily",
        strategy_fingerprint="top-level-strategy-v1",
        account=DailyAccountSeed(
            account_id="top-level-account",
            base_currency="KRW",
            initial_cash=1_000_000,
        ),
        instruments=instruments,
        exchange=exchange,
        market=DailyMarketBinding(market_dataset_id="market"),
        decision_times=(session_close,),
        session_closes=(session_close,),
    )
    monitoring = ConstraintMonitoringSpec(
        invocation_id="top-level-monitoring",
        checkpoint_artifact_id="artifact-checkpoint",
        evaluation_time=session_close,
        policy=MvpConstraintPolicy(
            policy_id="top-level-policy",
            benchmark_dataset_id="benchmark",
        ),
    )

    assert daily.instruments == instruments
    assert monitoring.to_request().config_fingerprint == (
        monitoring.frozen_config_fingerprint()
    )
