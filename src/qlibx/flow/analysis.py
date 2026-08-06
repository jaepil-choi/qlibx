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
    SignalAnalysisInput,
    SignalAnalysisRequest,
    SignalValue,
    SimulationAnalysisInput,
    SimulationAnalysisRequest,
    analyze_monitoring,
    analyze_signal,
    analyze_simulation,
    render_analysis,
)
from qlibx.context import ViewGate
from qlibx.data import ObservationStore, RegistrySnapshot, RequirementResolver
from qlibx.errors import CommitStatus, OperationError, OperationOutcome, OutcomeStatus
from qlibx.evidence import ArtifactContract, DependencyEdge, LocalArtifactBackend
from qlibx.flow.composition import STORED_SIGNAL_CONTRACT
from qlibx.flow.daily import ExecutionEvidence, SimulationCheckpoint
from qlibx.flow.monitoring import CONSTRAINT_MONITORING_CONTRACT
from qlibx.kernel import BacktestClock

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

    def __init__(
        self,
        *,
        artifacts: LocalArtifactBackend,
        registry: RegistrySnapshot | None = None,
        resolver: RequirementResolver | None = None,
        store: ObservationStore | None = None,
    ) -> None:
        self._artifacts = artifacts
        self._registry = registry or RegistrySnapshot(())
        self._resolver = resolver or RequirementResolver()
        self._store = store or ObservationStore()

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

    def analyze_signal(self, request: SignalAnalysisRequest) -> OperationOutcome:
        loaded = self._artifacts.load_model(
            request.signal_artifact_id,
            STORED_SIGNAL_CONTRACT,
        )
        if loaded.status is not OutcomeStatus.COMPLETE:
            return loaded
        resolution = self._resolver.resolve(
            operation="analysis.run",
            idempotency_identity=request.invocation_id,
            requirements=(request.return_requirement,),
            registry=self._registry,
        )
        if resolution.failed:
            published = tuple(self._artifacts.publish_failure(error) for error in resolution.errors)
            return OperationOutcome(
                status=OutcomeStatus.FAILED,
                diagnostics=tuple(
                    item.result for item in published if item.status is OutcomeStatus.COMPLETE
                ),
                errors=resolution.errors,
            )
        view = ViewGate(self._registry, self._store).materialize_view(
            BacktestClock(request.evaluation_time),
            resolution.bindings,
        )
        role = request.return_requirement.semantic_role
        try:
            frame = view.session(role, request.return_session)
            frame = frame.drop_duplicates(subset=["instrument"], keep="last")
            result = analyze_signal(
                request,
                SignalAnalysisInput(
                    signal_semantics=loaded.result.payload.signal_semantics,
                    signal_observation_time=loaded.result.payload.observation_time,
                    signals=tuple(
                        SignalValue(instrument=item.instrument, value=item.value)
                        for item in loaded.result.payload.entries
                    ),
                    returns=tuple(
                        SignalValue(
                            instrument=str(row.instrument),
                            value=float(getattr(row, role)),
                        )
                        for row in frame.itertuples(index=False)
                    ),
                    accesses=view.accessed(),
                ),
            )
        except AnalysisError as exc:
            return self._failure(
                request.invocation_id,
                "analysis.run.compute",
                exc.code,
                {**exc.context, "accesses": self._access_context(view)},
            )
        except Exception as exc:
            return self._failure(
                request.invocation_id,
                "analysis.run.data",
                "ANALYSIS_DATA_READ_FAILED",
                {
                    "exception": type(exc).__name__,
                    "message": str(exc)[:500],
                    "accesses": self._access_context(view),
                },
            )
        additional_dependencies = tuple(
            ()
            if request.resolves_error_artifact_id is None
            else (
                DependencyEdge(
                    dependency_kind="error",
                    dependency_id=request.resolves_error_artifact_id,
                    consumer_role="resolves_error",
                ),
            )
        )
        return self._publish_analysis(
            request.invocation_id,
            request.config_fingerprint,
            result,
            additional_dependencies=additional_dependencies,
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
        *,
        additional_dependencies: tuple[DependencyEdge, ...] = (),
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
                *(
                    DependencyEdge(
                        dependency_kind="dataset",
                        dependency_id=access.registration_identity,
                        consumer_role=access.semantic_role,
                        selected_fields=(access.selected_field,),
                    )
                    for access in result.accesses
                ),
                *additional_dependencies,
            ),
        )
        if publication.status is not OutcomeStatus.COMPLETE:
            return publication
        return OperationOutcome(
            status=OutcomeStatus.COMPLETE,
            result=result,
            diagnostics=(publication.result,),
        )

    @staticmethod
    def _access_context(view: object) -> list[dict[str, object]]:
        return [
            item.model_dump(mode="json")
            for item in view.accessed()  # type: ignore[attr-defined]
        ]

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
