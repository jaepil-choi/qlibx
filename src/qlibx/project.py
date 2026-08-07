"""Public project facade."""

import hashlib
from pathlib import Path

from qlibx.account import Account
from qlibx.config.project import (
    ProjectConfig,
    ProjectInitResult,
    apply_project,
    load_project_config,
    preview_project,
)
from qlibx.constraints import (
    ConstraintAdjustmentSpec,
    ConstraintMonitoringSpec,
    ConstraintValidationSpec,
)
from qlibx.data.contracts import DatasetRegistration
from qlibx.data.registry import DatasetRegistry, RegistrySnapshot
from qlibx.errors import CommitStatus, OperationError, OperationOutcome, OutcomeStatus
from qlibx.evidence import ArtifactContract, DependencyEdge, LocalArtifactBackend
from qlibx.execution import KrxExchange
from qlibx.extensions import (
    ExtensionRegistration,
    ExtensionValidationRequest,
    RegisteredStrategyExtension,
    StrategyExtensionValidationRequest,
)
from qlibx.flow import (
    ConstraintFlow,
    DailyExecutionFlow,
    DailyExecutionProfile,
    DailyRunRequest,
    ExtensionFlow,
    LoadedStrategyExtension,
    MonitoringFlow,
    ResearchFlow,
    StrategyExtensionFlow,
)
from qlibx.flow.analysis import SIMULATION_CHECKPOINT_CONTRACT
from qlibx.flow.artifact_inputs import StrategyArtifactContractRegistry
from qlibx.kernel import BacktestClock
from qlibx.models import QlibxModel
from qlibx.onboarding import OnboardingRequest, ProjectOnboarder, TargetOnboardingResult
from qlibx.operations import StrategyInvocation, StrategyOperation
from qlibx.sample import SampleMaterializationResult, SampleMaterializer
from qlibx.simulation import DailySimulationSpec


class QlibxProject:
    """A user-owned qlibx project rooted at an explicit directory."""

    default_sample_id = SampleMaterializer.default_sample_id

    def __init__(self, root: Path, config: ProjectConfig) -> None:
        self._root = root.resolve()
        self._config = config
        self._artifacts: LocalArtifactBackend | None = None

    @property
    def root(self) -> Path:
        return self._root

    @property
    def config(self) -> ProjectConfig:
        return self._config

    @property
    def dataset_registry(self) -> DatasetRegistry:
        registry_dir = self._root / self._config.data_dir / "registrations"
        return DatasetRegistry(self._root, registry_dir)

    def register_dataset(self, registration: DatasetRegistration) -> OperationOutcome:
        return self.dataset_registry.register(registration)

    def registry_snapshot(self) -> RegistrySnapshot:
        return self.dataset_registry.snapshot()

    @property
    def extension_flow(self) -> ExtensionFlow:
        return ExtensionFlow(
            project_root=self._root,
            extension_root=self._root / self._config.extension_dir,
            registry=self.registry_snapshot(),
            artifacts=self.artifacts,
        )

    def validate_extension(self, request: ExtensionValidationRequest) -> OperationOutcome:
        return self.extension_flow.validate_local(request)

    def registered_extensions(self) -> tuple[ExtensionRegistration, ...]:
        return self.extension_flow.registered()

    @property
    def strategy_extension_flow(self) -> StrategyExtensionFlow:
        return StrategyExtensionFlow(
            project_root=self._root,
            extension_root=self._root / self._config.extension_dir,
            registry=self.registry_snapshot(),
            artifacts=self.artifacts,
        )

    def validate_strategy_extension(
        self,
        request: StrategyExtensionValidationRequest,
    ) -> OperationOutcome:
        return self.strategy_extension_flow.validate_local(request)

    def registered_strategy_extensions(self) -> tuple[RegisteredStrategyExtension, ...]:
        return self.strategy_extension_flow.registered()

    @property
    def artifacts(self) -> LocalArtifactBackend:
        if self._artifacts is None:
            self._artifacts = LocalArtifactBackend(
                self._root / self._config.catalog_path,
                self._root / self._config.artifact_dir,
            )
        return self._artifacts

    def load_artifact(
        self,
        artifact_id: str,
        contract: ArtifactContract[QlibxModel],
        *,
        include_failure: bool = False,
    ) -> OperationOutcome:
        return self.artifacts.load_model(
            artifact_id,
            contract,
            include_failure=include_failure,
        )

    def onboard(
        self,
        requests: tuple[OnboardingRequest, ...],
        *,
        apply: bool = False,
    ) -> tuple[TargetOnboardingResult, ...]:
        return ProjectOnboarder(self._root).onboard(requests, apply=apply)

    @classmethod
    def available_sample_ids(cls) -> tuple[str, ...]:
        """Return the bundled sample identities accepted by the public facade."""

        return SampleMaterializer.sample_ids()

    def materialize_sample(
        self,
        sample_id: str = SampleMaterializer.default_sample_id,
        *,
        apply: bool = False,
    ) -> SampleMaterializationResult:
        return SampleMaterializer(self._root, sample_id).materialize(apply=apply)

    def invoke(
        self,
        operation: StrategyOperation,
        invocation: StrategyInvocation,
    ) -> OperationOutcome:
        return ResearchFlow(
            registry=self.registry_snapshot(),
            artifacts=self.artifacts,
        ).invoke_strategy(operation, invocation)

    def invoke_registered_strategy(
        self,
        registration_artifact_id: str,
        invocation: StrategyInvocation,
    ) -> OperationOutcome:
        loaded = self.strategy_extension_flow.load_registered(registration_artifact_id)
        if loaded.status is not OutcomeStatus.COMPLETE:
            return loaded
        selected = loaded.result
        return ResearchFlow(
            registry=self.registry_snapshot(),
            artifacts=self.artifacts,
            artifact_contracts=selected.artifact_contracts,
            strategy_dependencies=(self._strategy_registration_dependency(selected),),
        ).invoke_strategy(selected.operation, invocation)

    def adjust_constraints(self, spec: ConstraintAdjustmentSpec) -> OperationOutcome:
        """Adjust one portfolio candidate under the explicitly selected MVP policy."""

        return ConstraintFlow(
            registry=self.registry_snapshot(),
            artifacts=self.artifacts,
        ).adjust(spec.policy.to_declaration(), spec.to_request())

    def validate_constraints(self, spec: ConstraintValidationSpec) -> OperationOutcome:
        """Independently validate a prior adjustment under the selected MVP policy."""

        return ConstraintFlow(
            registry=self.registry_snapshot(),
            artifacts=self.artifacts,
        ).validate(spec.policy.to_declaration(), spec.to_request())

    def monitor_constraints(self, spec: ConstraintMonitoringSpec) -> OperationOutcome:
        """Independently monitor committed Account state under the selected MVP policy."""

        loaded = self.load_artifact(
            spec.checkpoint_artifact_id,
            SIMULATION_CHECKPOINT_CONTRACT,
        )
        if loaded.status is not OutcomeStatus.COMPLETE:
            return loaded
        try:
            account = Account.from_checkpoint(loaded.result.payload.account_checkpoint)
        except ValueError as exc:
            return self._checkpoint_failure(spec, exc)
        return MonitoringFlow(
            clock=BacktestClock(spec.evaluation_time),
            registry=self.registry_snapshot(),
            artifacts=self.artifacts,
            account=account,
        ).run(spec.policy.to_declaration(), spec.to_request())

    def run_daily(
        self,
        strategy: StrategyOperation,
        spec: DailySimulationSpec,
        *,
        resume: bool = False,
    ) -> OperationOutcome:
        """Run the supported next-session-close profile from frozen public input."""

        return self._run_daily(strategy, spec, resume=resume)

    def run_daily_registered_strategy(
        self,
        registration_artifact_id: str,
        spec: DailySimulationSpec,
        *,
        resume: bool = False,
    ) -> OperationOutcome:
        """Run an exact registered Strategy after source and contract revalidation."""

        loaded = self.strategy_extension_flow.load_registered(registration_artifact_id)
        if loaded.status is not OutcomeStatus.COMPLETE:
            return loaded
        selected = loaded.result
        registered_identity = hashlib.sha256(
            (
                f"{spec.frozen_config_fingerprint()}|"
                f"registration:{selected.registration_artifact_id}|"
                f"source:{selected.registration.source_hash}"
            ).encode()
        ).hexdigest()
        return self._run_daily(
            selected.operation,
            spec,
            resume=resume,
            config_fingerprint=registered_identity,
            artifact_contracts=selected.artifact_contracts,
            strategy_dependencies=(self._strategy_registration_dependency(selected),),
        )

    def _run_daily(
        self,
        strategy: StrategyOperation,
        spec: DailySimulationSpec,
        *,
        resume: bool,
        config_fingerprint: str | None = None,
        artifact_contracts: StrategyArtifactContractRegistry | None = None,
        strategy_dependencies: tuple[DependencyEdge, ...] = (),
    ) -> OperationOutcome:
        exchange = KrxExchange(spec.exchange)
        for instrument in spec.instruments:
            exchange.add_instrument(instrument)
        account = Account(
            account_id=spec.account.account_id,
            base_currency=spec.account.base_currency,
            initial_cash=spec.account.initial_cash,
            instrument_ids=frozenset(item.instrument_id for item in spec.instruments),
        )
        first_event = min((*spec.decision_times, *spec.session_closes))
        flow = DailyExecutionFlow(
            clock=BacktestClock(first_event),
            registry=self.registry_snapshot(),
            artifacts=self.artifacts,
            exchange=exchange,
            account=account,
            profile=DailyExecutionProfile(
                market_dataset_id=spec.market.market_dataset_id,
                execution_price_role=spec.market.execution_price_role,
                valuation_price_role=spec.market.valuation_price_role,
                feedback_entry_limit=spec.market.feedback_entry_limit,
            ),
            artifact_contracts=artifact_contracts,
            strategy_dependencies=strategy_dependencies,
        )
        return flow.run(
            strategy,
            DailyRunRequest(
                run_id=spec.run_id,
                config_fingerprint=(
                    config_fingerprint or spec.frozen_config_fingerprint()
                ),
                decision_times=spec.decision_times,
                session_closes=spec.session_closes,
                artifact_bindings=spec.artifact_bindings,
            ),
            resume=resume,
        )

    @staticmethod
    def _strategy_registration_dependency(
        selected: LoadedStrategyExtension,
    ) -> DependencyEdge:
        return DependencyEdge(
            dependency_kind="artifact",
            dependency_id=selected.registration_artifact_id,
            consumer_role="strategy_extension_registration",
            compatibility_fingerprint=selected.registration.source_hash,
        )

    @staticmethod
    def _checkpoint_failure(
        spec: ConstraintMonitoringSpec,
        exc: ValueError,
    ) -> OperationOutcome:
        stage_path = "monitoring.constraint.checkpoint"
        error_code = "MONITORING_ACCOUNT_CHECKPOINT_INVALID"
        seed = hashlib.sha256(
            f"{spec.invocation_id}:{stage_path}:{error_code}".encode()
        ).hexdigest()[:24]
        error = OperationError(
            operation="monitoring.constraint",
            stage_path=stage_path,
            error_code=error_code,
            context={
                "checkpoint_artifact_id": spec.checkpoint_artifact_id,
                "exception": type(exc).__name__,
                "message": str(exc)[:500],
            },
            commit_status=CommitStatus.NONE,
            retry_preconditions=(
                "provide a simulation checkpoint with a valid Account checkpoint",
            ),
            idempotency_identity=spec.invocation_id,
            error_id=f"error-{seed}",
        )
        return OperationOutcome(status=OutcomeStatus.FAILED, errors=(error,))

    @classmethod
    def init(
        cls,
        root: str | Path,
        *,
        apply: bool = False,
        config: ProjectConfig | None = None,
    ) -> ProjectInitResult:
        selected = config or ProjectConfig()
        path = Path(root)
        if apply:
            return apply_project(path, selected)
        return preview_project(path, selected)

    @classmethod
    def open(cls, root: str | Path) -> "QlibxProject":
        path = Path(root).resolve()
        return cls(path, load_project_config(path))
