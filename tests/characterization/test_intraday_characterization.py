from datetime import datetime

from qlibx import OutcomeStatus
from qlibx.data import AvailableAtField, DatasetRegistration, SourceFormat
from qlibx.flow.daily import FrozenDecision
from qlibx.flow.intraday import (
    IntradayExecutionFlow,
    IntradayExecutionProfile,
    IntradayRunRequest,
)
from qlibx.kernel import BacktestClock
from tests.acceptance.real_dw_support import (
    KST,
    RealDwProject,
    configured_exchange,
    initial_account,
    run_real_daily_flow,
)


def _parent_decision(case: RealDwProject):
    outcome = run_real_daily_flow(case, run_id="intraday-parent")
    intent = outcome.result.decision_intents[0]
    artifact = next(
        item
        for item in outcome.result.artifacts
        if item.artifact_type == "decision_intent"
    )
    return intent, artifact


def test_uc_exec_001_future_multi_event_characterization_has_no_daily_fallback(
    characterization_dw_case: RealDwProject,
) -> None:
    intent, artifact = _parent_decision(characterization_dw_case)
    source = characterization_dw_case.root / "intraday-characterization.csv"
    source.write_text(
        "timestamp,available_at,ticker,point_price,event_volume\n"
        "2024-01-03T09:30:00+09:00,2024-01-03T09:30:00+09:00,A005930,77000,30\n"
        "2024-01-03T11:00:00+09:00,2024-01-03T11:00:00+09:00,A005930,77000,30\n"
        "2024-01-03T15:20:00+09:00,2024-01-03T15:20:00+09:00,A005930,77000,30\n",
        encoding="utf-8",
    )
    registration = characterization_dw_case.project.register_dataset(
        DatasetRegistration(
            dataset_id="intraday-characterization",
            source=source.name,
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
    assert registration.status is OutcomeStatus.COMPLETE
    event_times = (
        datetime(2024, 1, 3, 9, 30, tzinfo=KST),
        datetime(2024, 1, 3, 11, 0, tzinfo=KST),
        datetime(2024, 1, 3, 15, 20, tzinfo=KST),
    )
    result = IntradayExecutionFlow(
        clock=BacktestClock(intent.decision_time),
        registry=characterization_dw_case.project.registry_snapshot(),
        artifacts=characterization_dw_case.project.artifacts,
        exchange=configured_exchange(participation_rate=1.0),
        account=initial_account("intraday-child"),
        profile=IntradayExecutionProfile(
            profile_id="intraday-characterization.v1",
            market_dataset_id="intraday-characterization",
        ),
    ).execute_frozen(
        FrozenDecision(intent=intent, artifact=artifact),
        IntradayRunRequest(
            run_id="synthetic-intraday-child",
            config_fingerprint="synthetic-intraday-v1",
            execution_times=event_times,
        ),
    )

    assert result.status is OutcomeStatus.COMPLETE
    assert [item.execution.account_before.version for item in result.result.executions] == [
        0,
        1,
        2,
    ]
    assert [item.execution.fills[0].dealt_quantity for item in result.result.executions] == [
        30,
        30,
        30,
    ]
    assert result.result.executions[-1].remaining[0].remaining_quantity == 39
    assert result.result.executions[-1].completes_decision is False
    assert result.result.final_account.holdings() == {"A005930": 90}

    missing_account = initial_account("missing-intraday")
    missing = IntradayExecutionFlow(
        clock=BacktestClock(intent.decision_time),
        registry=characterization_dw_case.project.registry_snapshot(),
        artifacts=characterization_dw_case.project.artifacts,
        exchange=configured_exchange(participation_rate=1.0),
        account=missing_account,
        profile=IntradayExecutionProfile(
            profile_id="missing-intraday.v1",
            market_dataset_id="dw-real-market",
        ),
    ).execute_frozen(
        FrozenDecision(intent=intent, artifact=artifact),
        IntradayRunRequest(
            run_id="missing-intraday-child",
            config_fingerprint="missing-intraday-v1",
            execution_times=(event_times[0],),
        ),
    )
    assert missing.status is OutcomeStatus.FAILED
    assert missing.errors[0].error_code == "REQUIREMENT_NOT_RESOLVED"
    assert missing_account.snapshot().version == 0
