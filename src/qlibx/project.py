"""Public project facade."""

from pathlib import Path

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
from qlibx.flow import ResearchFlow
from qlibx.models import QlibxModel
from qlibx.onboarding import OnboardingRequest, ProjectOnboarder, TargetOnboardingResult
from qlibx.operations import StrategyInvocation, StrategyOperation


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

    def invoke(
        self,
        operation: StrategyOperation,
        invocation: StrategyInvocation,
    ) -> OperationOutcome:
        return ResearchFlow(
            registry=self.registry_snapshot(),
            artifacts=self.artifacts,
        ).invoke_strategy(operation, invocation)

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
