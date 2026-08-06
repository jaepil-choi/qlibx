from datetime import date

import duckdb
import pytest

from qlibx import OutcomeStatus
from qlibx.analysis import SignalAnalysisRequest
from qlibx.data import AvailableAtField, ComponentRequirement, DatasetRegistration, SourceFormat
from qlibx.flow import STORED_SIGNAL_CONTRACT, AnalysisFlow, StoredSignalEntry, StoredSignalResult
from tests.acceptance.real_dw_support import RealDwProject, close_at


def _publish_real_signal(case: RealDwProject):
    rows = duckdb.sql(
        f"""
        SELECT ticker, decision_return
        FROM read_parquet('{case.source.as_posix()}')
        WHERE CAST(date AS DATE) = DATE '2024-01-02'
        ORDER BY ticker
        """
    ).fetchall()
    signal = StoredSignalResult(
        signal_semantics="real_dw_close_to_base_return",
        observation_time=close_at(2024, 1, 2),
        entries=tuple(
            StoredSignalEntry(instrument=ticker, value=float(value))
            for ticker, value in rows
        ),
    )
    return case.project.artifacts.import_model_bytes(
        logical_identity="analysis-input:real-dw-signal-2024-01-02",
        contract=STORED_SIGNAL_CONTRACT,
        producer_id="external.real-dw-signal",
        payload_bytes=signal.model_dump_json().encode(),
    )


def _request(
    invocation_id: str,
    signal_artifact_id: str,
    *,
    resolves_error_artifact_id: str | None = None,
) -> SignalAnalysisRequest:
    return SignalAnalysisRequest(
        invocation_id=invocation_id,
        signal_artifact_id=signal_artifact_id,
        evaluation_time=close_at(2024, 1, 3),
        return_session=date(2024, 1, 3),
        return_requirement=ComponentRequirement(
            requirement_id="analysis.realized_return",
            semantic_role="analysis_return",
            dataset_id="real-analysis-return",
        ),
        config_fingerprint="signal-analysis-zero-cost-v1",
        resolves_error_artifact_id=resolves_error_artifact_id,
    )


def test_uc_error_001_and_uc_research_001_short_analysis_fails_then_retries(
    real_dw_case: RealDwProject,
) -> None:
    imported = _publish_real_signal(real_dw_case)
    assert imported.status is OutcomeStatus.COMPLETE
    account_absent = not hasattr(
        AnalysisFlow(
            artifacts=real_dw_case.project.artifacts,
            registry=real_dw_case.project.registry_snapshot(),
        ),
        "account",
    )
    assert account_absent

    missing = AnalysisFlow(
        artifacts=real_dw_case.project.artifacts,
        registry=real_dw_case.project.registry_snapshot(),
    ).analyze_signal(
        _request("signal-analysis-missing-return", imported.result.artifact_id)
    )
    assert missing.status is OutcomeStatus.FAILED
    assert missing.errors[0].stage_path == "analysis.run.requirements.analysis_return"
    assert missing.errors[0].commit_status.value == "NONE"
    assert tuple(
        envelope.artifact_type
        for envelope in real_dw_case.project.artifacts.list_envelopes()
    ) == ("stored_signal_result",)
    failure_artifact = missing.diagnostics[0]

    registration = real_dw_case.project.register_dataset(
        DatasetRegistration(
            dataset_id="real-analysis-return",
            source=real_dw_case.source.name,
            source_format=SourceFormat.PARQUET,
            instrument_field="ticker",
            observation_time_field="date",
            available_at=AvailableAtField(field="available_at"),
            logical_key=("date", "available_at", "ticker"),
            semantic_bindings={"analysis_return": "decision_return"},
            semantic_category="krx_realized_daily_return",
            source_provenance=(
                "bounded unchanged close-to-base return from "
                "data/DW/fng_stock_daily_prices.csv"
            ),
        )
    )
    assert registration.status is OutcomeStatus.COMPLETE
    retry = AnalysisFlow(
        artifacts=real_dw_case.project.artifacts,
        registry=real_dw_case.project.registry_snapshot(),
    ).analyze_signal(
        _request(
            "signal-analysis-retry",
            imported.result.artifact_id,
            resolves_error_artifact_id=failure_artifact.artifact_id,
        )
    )
    assert retry.status is OutcomeStatus.COMPLETE
    assert retry.result.analysis_kind == "signal"
    assert retry.result.state_semantics == "not_applicable"
    assert retry.result.records == ()
    metrics = {item.name: item.value for item in retry.result.metrics}
    assert metrics["signal_count"] == 2.0

    source_rows = duckdb.sql(
        f"""
        SELECT CAST(date AS DATE), ticker, decision_return
        FROM read_parquet('{real_dw_case.source.as_posix()}')
        WHERE CAST(date AS DATE) IN (DATE '2024-01-02', DATE '2024-01-03')
        ORDER BY date, ticker
        """
    ).fetchall()
    values = {
        (session, ticker): float(value)
        for session, ticker, value in source_rows
    }
    tickers = sorted(ticker for session, ticker in values if session == date(2024, 1, 2))
    signals = [values[(date(2024, 1, 2), ticker)] for ticker in tickers]
    returns = [values[(date(2024, 1, 3), ticker)] for ticker in tickers]
    signal_mean = sum(signals) / len(signals)
    return_mean = sum(returns) / len(returns)
    centered_signal = [value - signal_mean for value in signals]
    centered_return = [value - return_mean for value in returns]
    expected_ic = sum(
        signal * realized
        for signal, realized in zip(centered_signal, centered_return, strict=True)
    ) / (
        sum(value * value for value in centered_signal)
        * sum(value * value for value in centered_return)
    ) ** 0.5
    expected_return = sum(
        signal / sum(abs(value) for value in centered_signal) * realized
        for signal, realized in zip(centered_signal, returns, strict=True)
    )
    assert metrics["information_coefficient"] == pytest.approx(expected_ic, abs=1e-15)
    assert metrics["hypothetical_long_short_return"] == pytest.approx(
        expected_return,
        abs=1e-15,
    )
    assert retry.result.accesses[0].max_available_at <= retry.result.evaluation_time
    assert any(
        edge.dependency_kind == "error"
        and edge.dependency_id == failure_artifact.artifact_id
        and edge.consumer_role == "resolves_error"
        for edge in retry.diagnostics[0].dependencies
    )
    complete_types = {
        envelope.artifact_type
        for envelope in real_dw_case.project.artifacts.list_envelopes()
    }
    assert complete_types == {"stored_signal_result", "analysis_result"}
