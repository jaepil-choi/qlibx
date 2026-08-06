"""Stored-artifact analysis and presentation-only report orchestration."""

import hashlib

from qlibx.analysis import (
    AnalysisError,
    AnalysisResult,
    ExecutionAnalysisInput,
    MonitoringAnalysisInput,
    MonitoringAnalysisRequest,
    MonitoringFindingInput,
    ReportRequest,
    ReportResult,
    SimulationAnalysisInput,
    SimulationAnalysisRequest,
    analyze_monitoring,
    analyze_simulation,
    render_analysis,
)
from qlibx.errors import CommitStatus, OperationError, OperationOutcome, OutcomeStatus
from qlibx.evidence import ArtifactContract, DependencyEdge, LocalArtifactBackend
from qlibx.flow.daily import ExecutionEvidence, SimulationCheckpoint
from qlibx.flow.monitoring import CONSTRAINT_MONITORING_CONTRACT

ANALYSIS_RESULT_CONTRACT = ArtifactContract(
    artifact_type="analysis_result",
    artifact_schema_version=1,
    payload_model=AnalysisResult,
)

REPORT_RESULT_CONTRACT = ArtifactContract(
    artifact_type="report_result",
    artifact_schema_version=1,
    payload_model=ReportResult,
)

EXECUTION_EVIDENCE_CONTRACT = ArtifactContract(
    artifact_type="execution_result",
    artifact_schema_version=1,
    payload_model=ExecutionEvidence,
)

SIMULATION_CHECKPOINT_CONTRACT = ArtifactContract(
    artifact_type="simulation_checkpoint",
    artifact_schema_version=1,
    payload_model=SimulationCheckpoint,
)

OPERATION_ERROR_CONTRACT = ArtifactContract(
    artifact_type="operation_error",
    artifact_schema_version=1,
    payload_model=OperationError,
)


class AnalysisFlow:
    """Load frozen evidence, calculate once, and render only stored values."""

    def __init__(self, *, artifacts: LocalArtifactBackend) -> None:
        self._artifacts = artifacts

    def analyze_simulation(
        self,
        request: SimulationAnalysisRequest,
    ) -> OperationOutcome:
        checkpoint = self._artifacts.load_model(
            request.checkpoint_artifact_id,
            SIMULATION_CHECKPOINT_CONTRACT,
        )
        if checkpoint.status is not OutcomeStatus.COMPLETE:
            return checkpoint
        executions = []
        for artifact_id in request.execution_artifact_ids:
            loaded = self._artifacts.load_model(
                artifact_id,
                EXECUTION_EVIDENCE_CONTRACT,
            )
            if loaded.status is not OutcomeStatus.COMPLETE:
                return loaded
            executions.append(loaded.result.payload)
        failures = []
        for artifact_id in request.failure_artifact_ids:
            loaded = self._artifacts.load_model(
                artifact_id,
                OPERATION_ERROR_CONTRACT,
                include_failure=True,
            )
            if loaded.status is not OutcomeStatus.COMPLETE:
                return loaded
            failures.append(loaded.result.payload)
        try:
            result = analyze_simulation(
                request,
                SimulationAnalysisInput(
                    checkpoint_state=checkpoint.result.payload.account,
                    journal_event_count=len(
                        checkpoint.result.payload.account_checkpoint.journal
                    ),
                    executions=tuple(
                        ExecutionAnalysisInput(
                            account_id=item.account_before.account_id,
                            initial_nav=item.account_before.nav,
                            total_cost=sum(fill.total_cost for fill in item.fills),
                            fill_count=sum(fill.dealt_quantity > 0 for fill in item.fills),
                            limitations=item.limitations,
                        )
                        for item in executions
                    ),
                    failure_count=len(failures),
                ),
            )
        except AnalysisError as exc:
            return self._failure(
                request.invocation_id,
                "analysis.simulation.compute",
                exc.code,
                exc.context,
            )
        return self._publish_analysis(
            request.invocation_id,
            request.config_fingerprint,
            result,
        )

    def analyze_monitoring(
        self,
        request: MonitoringAnalysisRequest,
    ) -> OperationOutcome:
        monitoring_results = []
        for artifact_id in request.monitoring_artifact_ids:
            loaded = self._artifacts.load_model(
                artifact_id,
                CONSTRAINT_MONITORING_CONTRACT,
            )
            if loaded.status is not OutcomeStatus.COMPLETE:
                return loaded
            monitoring_results.append(loaded.result.payload)
        missing_errors = []
        for artifact_id in request.missing_input_artifact_ids:
            loaded = self._artifacts.load_model(
                artifact_id,
                OPERATION_ERROR_CONTRACT,
                include_failure=True,
            )
            if loaded.status is not OutcomeStatus.COMPLETE:
                return loaded
            missing_errors.append(loaded.result.payload)
        result = analyze_monitoring(
            request,
            MonitoringAnalysisInput(
                findings=tuple(
                    MonitoringFindingInput(
                        state_identity=(
                            f"{monitor.account_state.account_id}:"
                            f"v{monitor.account_state.version}:"
                            f"cursor{monitor.account_state.feedback_cursor}"
                        ),
                        instrument=finding.instrument,
                        metric=finding.metric,
                        measured=finding.measured,
                        bound=finding.bound,
                        excess=finding.excess,
                        passed=finding.passed,
                    )
                    for monitor in monitoring_results
                    for finding in monitor.findings
                ),
                missing_error_codes=tuple(error.error_code for error in missing_errors),
            ),
        )
        return self._publish_analysis(
            request.invocation_id,
            request.config_fingerprint,
            result,
        )

    def render(self, request: ReportRequest) -> OperationOutcome:
        loaded = self._artifacts.load_model(
            request.analysis_artifact_id,
            ANALYSIS_RESULT_CONTRACT,
        )
        if loaded.status is not OutcomeStatus.COMPLETE:
            return loaded
        report = render_analysis(request, loaded.result.payload)
        publication = self._artifacts.publish_model(
            logical_identity=f"report:{request.invocation_id}",
            artifact_type="report_result",
            artifact_schema_version=1,
            producer_id=f"renderer.{request.renderer.value}",
            payload=report,
            dependencies=(
                DependencyEdge(
                    dependency_kind="artifact",
                    dependency_id=request.analysis_artifact_id,
                    consumer_role="stored_analysis_values",
                ),
                DependencyEdge(
                    dependency_kind="config",
                    dependency_id=request.config_fingerprint,
                    consumer_role="renderer_config",
                ),
            ),
        )
        if publication.status is not OutcomeStatus.COMPLETE:
            return publication
        return OperationOutcome(
            status=OutcomeStatus.COMPLETE,
            result=report,
            diagnostics=(publication.result,),
        )

    def _publish_analysis(
        self,
        invocation_id: str,
        config_fingerprint: str,
        result: AnalysisResult,
    ) -> OperationOutcome:
        publication = self._artifacts.publish_model(
            logical_identity=f"analysis:{invocation_id}",
            artifact_type="analysis_result",
            artifact_schema_version=1,
            producer_id=f"analysis.{result.analysis_kind}",
            payload=result,
            dependencies=(
                *(
                    DependencyEdge(
                        dependency_kind="artifact",
                        dependency_id=artifact_id,
                        consumer_role="stored_analysis_input",
                    )
                    for artifact_id in result.source_artifact_ids
                ),
                DependencyEdge(
                    dependency_kind="config",
                    dependency_id=config_fingerprint,
                    consumer_role="analysis_config",
                ),
            ),
        )
        if publication.status is not OutcomeStatus.COMPLETE:
            return publication
        return OperationOutcome(
            status=OutcomeStatus.COMPLETE,
            result=result,
            diagnostics=(publication.result,),
        )

    def _failure(
        self,
        identity: str,
        stage_path: str,
        code: str,
        context: dict[str, object],
    ) -> OperationOutcome:
        seed = hashlib.sha256(f"{identity}:{stage_path}:{code}".encode()).hexdigest()[:24]
        error = OperationError(
            operation="analysis.run",
            stage_path=stage_path,
            error_code=code,
            context=context,
            commit_status=CommitStatus.NONE,
            retry_preconditions=("provide complete compatible stored evidence",),
            idempotency_identity=identity,
            error_id=f"error-{seed}",
        )
        published = self._artifacts.publish_failure(error)
        diagnostics = (
            (published.result,) if published.status is OutcomeStatus.COMPLETE else published.errors
        )
        return OperationOutcome(
            status=OutcomeStatus.FAILED,
            diagnostics=diagnostics,
            errors=(error,),
        )
