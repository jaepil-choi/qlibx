"""Public project facade."""

from pathlib import Path

from qlibx.account import Account
from qlibx.config.project import (
    ProjectConfig,
    ProjectInitResult,
    apply_project,
    load_project_config,
    preview_project,
)
from qlibx.data.contracts import DatasetRegistration
from qlibx.data.registry import DatasetRegistry, RegistrySnapshot
from qlibx.errors import OperationOutcome
from qlibx.evidence import ArtifactContract, LocalArtifactBackend
from qlibx.execution import KrxExchange
from qlibx.extensions import ExtensionRegistration, ExtensionValidationRequest
from qlibx.flow import (
    DailyExecutionFlow,
    DailyExecutionProfile,
    DailyRunRequest,
    ExtensionFlow,
    ResearchFlow,
)
from qlibx.kernel import BacktestClock
from qlibx.models import QlibxModel
from qlibx.onboarding import OnboardingRequest, ProjectOnboarder, TargetOnboardingResult
from qlibx.operations import StrategyInvocation, StrategyOperation
from qlibx.sample import SampleMaterializationResult, SampleMaterializer
from qlibx.simulation import DailySimulationSpec


class QlibxProject:
    """A user-owned qlibx project rooted at an explicit directory."""

    def __init__(self, root: Path, config: ProjectConfig) -> None:
        self._root = root.resolve()
        self._config = config

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
    def artifacts(self) -> LocalArtifactBackend:
        return LocalArtifactBackend(
            self._root / self._config.catalog_path,
            self._root / self._config.artifact_dir,
        )

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

    def run_daily(
        self,
        strategy: StrategyOperation,
        spec: DailySimulationSpec,
        *,
        resume: bool = False,
    ) -> OperationOutcome:
        """Run the supported next-session-close profile from frozen public input."""

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
        )
        return flow.run(
            strategy,
            DailyRunRequest(
                run_id=spec.run_id,
                config_fingerprint=spec.frozen_config_fingerprint(),
                decision_times=spec.decision_times,
                session_closes=spec.session_closes,
            ),
            resume=resume,
        )

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
