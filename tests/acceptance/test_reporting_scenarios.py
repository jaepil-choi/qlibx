import json

import pytest

from qlibx import OutcomeStatus
from qlibx.account import StrategyMemoryStore
from qlibx.analysis import (
    MonitoringAnalysisRequest,
    RendererKind,
    ReportRequest,
    SimulationAnalysisRequest,
)
from qlibx.flow import AnalysisFlow, MonitoringFlow
from qlibx.kernel import BacktestClock
from qlibx.portfolio import (
    ConstraintDeclaration,
    ConstraintMonitoringRequest,
)
from tests.acceptance.real_dw_support import (
    RealDwProject,
    close_at,
    initial_account,
    run_real_daily_flow,
)


def _artifacts(run: object, artifact_type: str):
    return tuple(
        artifact
        for artifact in run.result.artifacts  # type: ignore[attr-defined]
        if artifact.artifact_type == artifact_type
    )


def _metrics(result: object) -> dict[str, float]:
    return {
        item.name: item.value
        for item in result.metrics  # type: ignore[attr-defined]
    }


def test_uc_report_001_renderers_preserve_one_stored_analysis_value_set(
    real_dw_constraint_case: RealDwProject,
) -> None:
    account = initial_account("report-simulation-account")
    memory = StrategyMemoryStore()
    run = run_real_daily_flow(
        real_dw_constraint_case,
        run_id="report-source-simulation",
        account=account,
        memory=memory,
    )
    checkpoint = _artifacts(run, "simulation_checkpoint")
    executions = _artifacts(run, "execution_result")
    assert len(checkpoint) == 1
    assert executions
    account_before = account.checkpoint()
    memory_before = memory.checkpoint()

    flow = AnalysisFlow(artifacts=real_dw_constraint_case.project.artifacts)
    analysis = flow.analyze_simulation(
        SimulationAnalysisRequest(
            invocation_id="report-simulation-analysis",
            checkpoint_artifact_id=checkpoint[0].artifact_id,
            execution_artifact_ids=tuple(item.artifact_id for item in executions),
            evaluation_time=close_at(2024, 1, 5),
            config_fingerprint="report-simulation-analysis-v1",
        )
    )
    reports = tuple(
        flow.render(
            ReportRequest(
                invocation_id=f"report-simulation-{renderer.value}",
                analysis_artifact_id=analysis.diagnostics[0].artifact_id,
                renderer=renderer,
                config_fingerprint=f"renderer-{renderer.value}-v1",
            )
        )
        for renderer in RendererKind
    )

    assert analysis.status is OutcomeStatus.COMPLETE
    assert all(report.status is OutcomeStatus.COMPLETE for report in reports)
    metrics = _metrics(analysis.result)
    assert set(metrics) == {
        "total_return",
        "total_cost",
        "gross_exposure",
        "net_exposure",
        "fill_count",
        "failure_count",
        "journal_event_count",
    }
    assert metrics["total_cost"] == pytest.approx(
        sum(
            fill.total_cost
            for execution in run.result.executions
            for fill in execution.fills
        )
    )
    assert metrics["total_return"] == pytest.approx(
        run.result.final_account.nav
        / run.result.executions[0].account_before.nav
        - 1
    )
    assert metrics["failure_count"] == 0
    assert metrics["journal_event_count"] == len(
        run.result.checkpoint.account_checkpoint.journal
    )
    for report in reports:
        assert report.result.metrics == analysis.result.metrics
        assert report.result.records == analysis.result.records
        assert report.result.values_fingerprint == analysis.result.values_fingerprint
        assert report.result.source_analysis_artifact_id == (
            analysis.diagnostics[0].artifact_id
        )
        assert report.diagnostics[0].dependencies[0].dependency_id == (
            analysis.diagnostics[0].artifact_id
        )
    machine = next(
        report for report in reports
        if report.result.renderer is RendererKind.MACHINE
    )
    machine_payload = json.loads(machine.result.rendered_content)
    assert machine_payload["values_fingerprint"] == analysis.result.values_fingerprint
    chart = next(
        report for report in reports
        if report.result.renderer is RendererKind.CHART
    )
    assert {
        item["name"]: item["value"]
        for item in json.loads(chart.result.rendered_content)["series"]
    } == pytest.approx(metrics)
    assert account.checkpoint() == account_before
    assert memory.checkpoint() == memory_before


def test_uc_monitor_001_report_separates_actual_breach_and_missing_input(
    real_dw_constraint_case: RealDwProject,
) -> None:
    account = initial_account("report-monitoring-account")
    memory = StrategyMemoryStore()
    run_real_daily_flow(
        real_dw_constraint_case,
        run_id="report-monitoring-source",
        account=account,
        memory=memory,
    )
    declaration = ConstraintDeclaration(
        declaration_id="mvp-no-short-single-name-cap-v1",
        benchmark_weight_role="benchmark_weight",
        single_name_floor=0.10,
    )
    monitoring = MonitoringFlow(
        clock=BacktestClock(close_at(2024, 1, 5)),
        registry=real_dw_constraint_case.project.registry_snapshot(),
        artifacts=real_dw_constraint_case.project.artifacts,
        account=account,
    )
    finding = monitoring.run(
        declaration,
        ConstraintMonitoringRequest(
            invocation_id="report-monitoring-finding",
            config_fingerprint="report-monitoring-v1",
        ),
    )
    missing = monitoring.run(
        ConstraintDeclaration(
            declaration_id="missing-monitoring-binding-v1",
            benchmark_weight_role="unregistered_monitoring_weight",
            single_name_floor=0.10,
        ),
        ConstraintMonitoringRequest(
            invocation_id="report-monitoring-missing",
            config_fingerprint="report-monitoring-v1",
        ),
    )
    account_before_report = account.checkpoint()
    memory_before_report = memory.checkpoint()
    flow = AnalysisFlow(artifacts=real_dw_constraint_case.project.artifacts)
    analysis = flow.analyze_monitoring(
        MonitoringAnalysisRequest(
            invocation_id="report-monitoring-analysis",
            monitoring_artifact_ids=(finding.diagnostics[0].artifact_id,),
            missing_input_artifact_ids=(missing.diagnostics[0].artifact_id,),
            evaluation_time=close_at(2024, 1, 5),
            config_fingerprint="report-monitoring-analysis-v1",
        )
    )
    report = flow.render(
        ReportRequest(
            invocation_id="report-monitoring-machine",
            analysis_artifact_id=analysis.diagnostics[0].artifact_id,
            renderer=RendererKind.MACHINE,
            config_fingerprint="report-monitoring-render-v1",
        )
    )

    assert finding.status is OutcomeStatus.COMPLETE
    assert missing.status is OutcomeStatus.FAILED
    assert analysis.status is report.status is OutcomeStatus.COMPLETE
    metrics = _metrics(analysis.result)
    assert metrics == {
        "evaluated_finding_count": 2.0,
        "breach_count": 1.0,
        "missing_input_count": 1.0,
    }
    breach = next(
        record
        for record in analysis.result.records
        if record.record_type == "constraint_finding"
        and record.metric == "single_name_cap"
    )
    missing_record = next(
        record
        for record in analysis.result.records
        if record.record_type == "missing_input"
    )
    assert breach.passed is False
    assert breach.excess > 0
    assert breach.state_identity.startswith(
        f"{account.snapshot().account_id}:v{account.snapshot().version}:"
    )
    assert missing_record.error_code == "REQUIREMENT_NOT_RESOLVED"
    assert analysis.result.state_semantics == "actual_account"
    assert all(
        "target" not in edge.consumer_role
        and "intent" not in edge.consumer_role
        for edge in analysis.diagnostics[0].dependencies
    )
    assert report.result.records == analysis.result.records
    assert report.result.values_fingerprint == analysis.result.values_fingerprint
    assert account.checkpoint() == account_before_report
    assert memory.checkpoint() == memory_before_report
