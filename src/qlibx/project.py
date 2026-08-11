"""Public project facade."""

import hashlib
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import TypeVar

from qlibx.account import Account
from qlibx.analysis import (
    AnalysisResult,
    MonitoringAnalysisRequest,
    ReportRequest,
    ReportResult,
    SignalAnalysisRequest,
    SimulationAnalysisRequest,
)
from qlibx.config.project import (
    ProjectConfig,
    ProjectInitResult,
    apply_project,
    load_project_config,
    preview_project,
)
from qlibx.contracts import (
    AccountHistoryRecordingSpec,
    ModelInvocation,
    ResearchModel,
    StrategyArtifactBinding,
    StrategyInvocation,
    StrategyOperation,
)
from qlibx.data.contracts import DatasetRegistration, DatasetReindexResult
from qlibx.data.registry import DatasetRegistry, RegistrySnapshot
from qlibx.data.store import ObservationStore
from qlibx.errors import CommitStatus, OperationError, OperationOutcome, OutcomeStatus
from qlibx.evidence import (
    ArtifactContract,
    CatalogSessionConflictError,
    DependencyEdge,
    LocalArtifactBackend,
)
from qlibx.evidence.local import CatalogSchemaError
from qlibx.execution import (
    BaseExchange,
    KrxBatchRequest,
    KrxExchange,
    KrxExchangeConfig,
    MatchBatchResult,
)
from qlibx.execution.academic import (
    AcademicBatchRequest,
    AcademicExchange,
    AcademicMatchResult,
)
from qlibx.extensions import (
    ExtensionRegistration,
    ExtensionValidationRequest,
    RegisteredStrategyExtension,
    StrategyExtensionValidationRequest,
)
from qlibx.flow import (
    DECISION_INTENT_CONTRACT,
    AcademicExecutionFlow,
    AnalysisFlow,
    CompositionFlow,
    ConstraintFlow,
    DailyExecutionFlow,
    DailyExecutionProfile,
    DailyRunRequest,
    EnsembleDefinition,
    ExtensionFlow,
    FrozenDecision,
    LoadedStrategyExtension,
    ModelFlow,
    MonitoringFlow,
    PortfolioConstructionFlow,
    ResearchFlow,
    StoredSignalWeighting,
    StrategyExtensionFlow,
)
from qlibx.flow.analysis import SIMULATION_CHECKPOINT_CONTRACT
from qlibx.flow.artifact_inputs import StrategyArtifactContractRegistry
from qlibx.flow.composition import EnsembleRunResult
from qlibx.flow.research import StrategyRunResult
from qlibx.models import QlibxModel
from qlibx.onboarding import OnboardingRequest, ProjectOnboarder, TargetOnboardingResult
from qlibx.portfolio import PortfolioConstructionRequest, PortfolioConstructionResult
from qlibx.runtime import BacktestClock
from qlibx.sample import SampleMaterializationResult, SampleMaterializer
from qlibx.specs.academic import AcademicRunSpec
from qlibx.specs.constraints import (
    ConstraintAdjustmentSpec,
    ConstraintMonitoringSpec,
    ConstraintValidationSpec,
    MvpConstraintPolicy,
)
from qlibx.specs.daily import (
    DailyAccountSeed,
    DailyMarketBinding,
    DailySimulationSpec,
    ExecutableInstrument,
    ExecutionTiming,
    FrozenDailyExecutionSpec,
)

ResultT = TypeVar("ResultT")


class QlibxProject:
    """A user-owned qlibx project rooted at an explicit directory."""

    default_sample_id = SampleMaterializer.default_sample_id

    def __init__(self, root: Path, config: ProjectConfig) -> None:
        self._root = root.resolve()
        self._config = config
        self._artifacts: LocalArtifactBackend | None = None
        self._store = ObservationStore()
        self._instruments: dict[str, ExecutableInstrument] = {}
        self._exchange: KrxExchangeConfig | None = None

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

    def add_instrument(self, instrument: ExecutableInstrument) -> None:
        """Accumulate one executable instrument for later spec construction (PRD 7.10.1).

        Accumulation is deliberately incremental so an onboarding interview can confirm one
        instrument at a time. Nothing here is frozen; `daily_spec` takes the snapshot.
        """

        existing = self._instruments.get(instrument.instrument_id)
        if existing is not None and existing != instrument:
            raise ValueError(
                f"instrument {instrument.instrument_id!r} is already configured differently; "
                "remove the earlier declaration before replacing it"
            )
        self._instruments[instrument.instrument_id] = instrument

    def set_exchange(self, exchange: KrxExchangeConfig) -> None:
        """Declare the venue configuration later specs freeze into their identity."""

        self._exchange = exchange

    @property
    def configured_instruments(self) -> tuple[ExecutableInstrument, ...]:
        return tuple(
            self._instruments[key] for key in sorted(self._instruments)
        )

    @property
    def configured_exchange(self) -> KrxExchangeConfig | None:
        return self._exchange

    def daily_spec(
        self,
        *,
        run_id: str,
        strategy_fingerprint: str,
        account: DailyAccountSeed,
        market: DailyMarketBinding,
        session_closes: tuple[datetime, ...],
        session_opens: tuple[datetime, ...] = (),
        execution_timing: ExecutionTiming = "next_session_close",
        artifact_bindings: tuple[StrategyArtifactBinding, ...] = (),
        account_history: AccountHistoryRecordingSpec | None = None,
        initial_strategy_state: object = None,
        constraint_policy: MvpConstraintPolicy | None = None,
    ) -> DailySimulationSpec:
        """Freeze the accumulated execution environment into one complete simulation spec.

        The returned spec carries the instruments and exchange config by value, so it replays
        without this project instance and later `add_instrument`/`set_exchange` calls cannot
        change a run that already started (PRD 7.10, 7.10.1).
        """

        if not self._instruments:
            raise ValueError("declare at least one instrument with add_instrument() first")
        if self._exchange is None:
            raise ValueError("declare the venue with set_exchange() first")
        return DailySimulationSpec(
            run_id=run_id,
            strategy_fingerprint=strategy_fingerprint,
            account=account,
            instruments=self.configured_instruments,
            exchange=self._exchange,
            market=market,
            execution_timing=execution_timing,
            session_closes=session_closes,
            session_opens=session_opens,
            artifact_bindings=artifact_bindings,
            account_history=account_history or AccountHistoryRecordingSpec(),
            initial_strategy_state=initial_strategy_state,
            constraint_policy=constraint_policy,
        )

    def reindex_datasets(
        self,
        dataset_ids: tuple[str, ...] | None = None,
    ) -> OperationOutcome[DatasetReindexResult]:
        return self.dataset_registry.reindex(dataset_ids)

    def registry_snapshot(self) -> RegistrySnapshot:
        return self.dataset_registry.snapshot()

    @property
    def extension_flow(self) -> ExtensionFlow:
        return ExtensionFlow(
            project_root=self._root,
            extension_root=self._root / self._config.extension_dir,
            registry=self.registry_snapshot(),
            artifacts=self.artifacts,
            store=self._store,
        )

    def validate_extension(self, request: ExtensionValidationRequest) -> OperationOutcome:
        return self._with_catalog_session(
            operation="extension.validate",
            identity=request.invocation_id,
            callback=lambda: self.extension_flow.validate_local(request),
        )

    def registered_extensions(self) -> tuple[ExtensionRegistration, ...]:
        return self.extension_flow.registered()

    @property
    def strategy_extension_flow(self) -> StrategyExtensionFlow:
        return StrategyExtensionFlow(
            project_root=self._root,
            extension_root=self._root / self._config.extension_dir,
            registry=self.registry_snapshot(),
            artifacts=self.artifacts,
            store=self._store,
        )

    def validate_strategy_extension(
        self,
        request: StrategyExtensionValidationRequest,
    ) -> OperationOutcome:
        return self._with_catalog_session(
            operation="strategy.extension.validate",
            identity=request.invocation_id,
            callback=lambda: self.strategy_extension_flow.validate_local(request),
        )

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
        return self._with_catalog_session(
            operation="strategy.invoke",
            identity=invocation.invocation_id,
            callback=lambda: ResearchFlow(
                registry=self.registry_snapshot(),
                artifacts=self.artifacts,
                store=self._store,
            ).invoke_strategy(operation, invocation),
        )

    def materialize(
        self,
        operation: ResearchModel,
        invocation: ModelInvocation,
    ) -> OperationOutcome:
        """Run one direct optional research-data materialization invocation."""

        return self._with_catalog_session(
            operation="materialization.run",
            identity=invocation.invocation_id,
            callback=lambda: ModelFlow(
                registry=self.registry_snapshot(),
                artifacts=self.artifacts,
                store=self._store,
            ).invoke(operation, invocation),
        )

    def invoke_registered_strategy(
        self,
        registration_artifact_id: str,
        invocation: StrategyInvocation,
    ) -> OperationOutcome:
        def invoke_registered() -> OperationOutcome:
            loaded = self.strategy_extension_flow.load_registered(registration_artifact_id)
            if loaded.status is not OutcomeStatus.COMPLETE:
                return loaded
            selected = loaded.result
            return ResearchFlow(
                registry=self.registry_snapshot(),
                artifacts=self.artifacts,
                store=self._store,
                artifact_contracts=selected.artifact_contracts,
                strategy_dependencies=(self._strategy_registration_dependency(selected),),
            ).invoke_strategy(selected.operation, invocation)

        return self._with_catalog_session(
            operation="strategy.invoke.registered",
            identity=invocation.invocation_id,
            callback=invoke_registered,
        )

    def run_ensemble(
        self,
        definition: EnsembleDefinition,
        invocation: StrategyInvocation,
    ) -> OperationOutcome[EnsembleRunResult]:
        return self._with_catalog_session(
            operation="ensemble.run",
            identity=invocation.invocation_id,
            callback=lambda: CompositionFlow(
                registry=self.registry_snapshot(),
                artifacts=self.artifacts,
            ).invoke_ensemble(definition, invocation),
        )

    def invoke_stored_signal_strategy(
        self,
        artifact_id: str,
        strategy_id: str,
        weighting: StoredSignalWeighting,
        invocation: StrategyInvocation,
    ) -> OperationOutcome[StrategyRunResult]:
        return self._with_catalog_session(
            operation="strategy.invoke.stored_signal",
            identity=invocation.invocation_id,
            callback=lambda: CompositionFlow(
                registry=self.registry_snapshot(),
                artifacts=self.artifacts,
            ).invoke_stored_signal_strategy(
                artifact_id=artifact_id,
                strategy_id=strategy_id,
                weighting=weighting,
                invocation=invocation,
            ),
        )

    def construct_portfolio(
        self,
        request: PortfolioConstructionRequest,
    ) -> OperationOutcome[PortfolioConstructionResult]:
        return self._with_catalog_session(
            operation="portfolio.construct",
            identity=request.invocation_id,
            callback=lambda: PortfolioConstructionFlow(artifacts=self.artifacts).construct(request),
        )

    def analyze_simulation(
        self,
        request: SimulationAnalysisRequest,
    ) -> OperationOutcome[AnalysisResult]:
        return self._with_catalog_session(
            operation="analysis.simulation",
            identity=request.invocation_id,
            callback=lambda: self._analysis_flow().analyze_simulation(request),
        )

    def analyze_monitoring(
        self,
        request: MonitoringAnalysisRequest,
    ) -> OperationOutcome[AnalysisResult]:
        return self._with_catalog_session(
            operation="analysis.monitoring",
            identity=request.invocation_id,
            callback=lambda: self._analysis_flow().analyze_monitoring(request),
        )

    def analyze_signal(
        self,
        request: SignalAnalysisRequest,
    ) -> OperationOutcome[AnalysisResult]:
        return self._with_catalog_session(
            operation="analysis.signal",
            identity=request.invocation_id,
            callback=lambda: self._analysis_flow().analyze_signal(request),
        )

    def render_report(self, request: ReportRequest) -> OperationOutcome[ReportResult]:
        return self._with_catalog_session(
            operation="report.render",
            identity=request.invocation_id,
            callback=lambda: self._analysis_flow().render(request),
        )

    def _analysis_flow(self) -> AnalysisFlow:
        return AnalysisFlow(
            artifacts=self.artifacts,
            registry=self.registry_snapshot(),
            store=self._store,
        )

    def adjust_constraints(self, spec: ConstraintAdjustmentSpec) -> OperationOutcome:
        """Adjust one portfolio candidate under the explicitly selected MVP policy."""

        return self._with_catalog_session(
            operation="constraint.adjust",
            identity=spec.invocation_id,
            callback=lambda: ConstraintFlow(
                registry=self.registry_snapshot(),
                artifacts=self.artifacts,
                store=self._store,
            ).adjust(spec.policy.to_declaration(), spec.to_request()),
        )

    def validate_constraints(self, spec: ConstraintValidationSpec) -> OperationOutcome:
        """Independently validate a prior adjustment under the selected MVP policy."""

        return self._with_catalog_session(
            operation="constraint.validate",
            identity=spec.invocation_id,
            callback=lambda: ConstraintFlow(
                registry=self.registry_snapshot(),
                artifacts=self.artifacts,
                store=self._store,
            ).validate(spec.policy.to_declaration(), spec.to_request()),
        )

    def monitor_constraints(self, spec: ConstraintMonitoringSpec) -> OperationOutcome:
        """Independently monitor committed Account state under the selected MVP policy."""

        def monitor() -> OperationOutcome:
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
                store=self._store,
            ).run(spec.policy.to_declaration(), spec.to_request())

        return self._with_catalog_session(
            operation="constraint.monitor",
            identity=spec.invocation_id,
            callback=monitor,
        )

    def run_academic(
        self,
        spec: AcademicRunSpec,
        *,
        exchange: BaseExchange[AcademicBatchRequest, AcademicMatchResult] | None = None,
    ) -> OperationOutcome:
        """Execute exact signed portfolios in the hypothetical academic venue."""

        selected_exchange = exchange or AcademicExchange(
            profile=spec.profile,
            listings=spec.listings,
        )
        return self._with_catalog_session(
            operation="academic.run",
            identity=spec.run_id,
            callback=lambda: AcademicExecutionFlow(
                registry=self.registry_snapshot(),
                artifacts=self.artifacts,
                store=self._store,
                exchange=selected_exchange,
            ).run(spec),
        )

    def run_daily(
        self,
        strategy: StrategyOperation,
        spec: DailySimulationSpec,
        *,
        exchange: BaseExchange[KrxBatchRequest, MatchBatchResult] | None = None,
    ) -> OperationOutcome:
        """Run a supported daily close/open profile from frozen public input."""

        return self._with_catalog_session(
            operation="simulation.daily",
            identity=spec.run_id,
            callback=lambda: self._run_daily(
                strategy,
                spec,
                exchange=exchange,
            ),
        )

    def run_daily_registered_strategy(
        self,
        registration_artifact_id: str,
        spec: DailySimulationSpec,
        *,
        exchange: BaseExchange[KrxBatchRequest, MatchBatchResult] | None = None,
    ) -> OperationOutcome:
        """Run an exact registered Strategy after source and contract revalidation."""

        def run_registered() -> OperationOutcome:
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
                exchange=exchange,
                config_fingerprint=registered_identity,
                artifact_contracts=selected.artifact_contracts,
                strategy_dependencies=(self._strategy_registration_dependency(selected),),
            )

        return self._with_catalog_session(
            operation="simulation.daily.registered",
            identity=spec.run_id,
            callback=run_registered,
        )
    def execute_frozen_daily(
        self,
        spec: FrozenDailyExecutionSpec,
    ) -> OperationOutcome:
        """Execute exact DecisionIntent artifacts without rerunning their producers."""

        return self._with_catalog_session(
            operation="simulation.daily.frozen",
            identity=spec.run_id,
            callback=lambda: self._execute_frozen_daily(spec),
        )

    def _execute_frozen_daily(
        self,
        spec: FrozenDailyExecutionSpec,
    ) -> OperationOutcome:
        frozen: list[FrozenDecision] = []
        for artifact_id in spec.parent_decision_artifact_ids:
            loaded = self.load_artifact(artifact_id, DECISION_INTENT_CONTRACT)
            if loaded.status is not OutcomeStatus.COMPLETE:
                return loaded
            frozen.append(
                FrozenDecision(
                    intent=loaded.result.payload,
                    artifact=loaded.result.envelope,
                )
            )

        exchange = KrxExchange(spec.exchange)
        for instrument in spec.instruments:
            exchange.add_instrument(instrument)
        account = Account(
            account_id=spec.account.account_id,
            base_currency=spec.account.base_currency,
            initial_cash=spec.account.initial_cash,
            instrument_ids=frozenset(item.instrument_id for item in spec.instruments),
        )
        first_event = min(
            *(item.intent.decision_time for item in frozen),
            *spec.session_closes,
            *spec.session_opens,
        )
        flow = DailyExecutionFlow(
            clock=BacktestClock(first_event),
            registry=self.registry_snapshot(),
            artifacts=self.artifacts,
            exchange=exchange,
            account=account,
            store=self._store,
            profile=self._daily_profile(spec),
        )
        return flow.execute_frozen(
            tuple(frozen),
            DailyRunRequest(
                run_id=spec.run_id,
                config_fingerprint=spec.frozen_config_fingerprint(),
                session_closes=spec.session_closes,
                session_opens=spec.session_opens,
            ),
        )

    def _run_daily(
        self,
        strategy: StrategyOperation,
        spec: DailySimulationSpec,
        *,
        exchange: BaseExchange[KrxBatchRequest, MatchBatchResult] | None,
        config_fingerprint: str | None = None,
        artifact_contracts: StrategyArtifactContractRegistry | None = None,
        strategy_dependencies: tuple[DependencyEdge, ...] = (),
    ) -> OperationOutcome:
        selected_exchange = exchange
        if selected_exchange is None:
            built_in = KrxExchange(spec.exchange)
            for instrument in spec.instruments:
                built_in.add_instrument(instrument)
            selected_exchange = built_in
        effective_fingerprint = hashlib.sha256(
            (
                f"{config_fingerprint or spec.frozen_config_fingerprint()}|"
                f"exchange:{selected_exchange.exchange_id}|"
                f"exchange-config:{selected_exchange.config_fingerprint}"
            ).encode()
        ).hexdigest()
        account = Account(
            account_id=spec.account.account_id,
            base_currency=spec.account.base_currency,
            initial_cash=spec.account.initial_cash,
            instrument_ids=frozenset(item.instrument_id for item in spec.instruments),
        )
        first_event = min((*spec.session_closes, *spec.session_opens))
        flow = DailyExecutionFlow(
            clock=BacktestClock(first_event),
            registry=self.registry_snapshot(),
            artifacts=self.artifacts,
            exchange=selected_exchange,
            account=account,
            store=self._store,
            profile=self._daily_profile(spec),
            artifact_contracts=artifact_contracts,
            strategy_dependencies=strategy_dependencies,
        )
        return flow.run(
            strategy,
            DailyRunRequest(
                run_id=spec.run_id,
                config_fingerprint=effective_fingerprint,
                session_closes=spec.session_closes,
                session_opens=spec.session_opens,
                artifact_bindings=spec.artifact_bindings,
                account_history=spec.account_history,
                initial_strategy_state=spec.initial_strategy_state,
            ),
        )
    @staticmethod
    def _daily_profile(
        spec: DailySimulationSpec | FrozenDailyExecutionSpec,
    ) -> DailyExecutionProfile:
        if spec.execution_timing == "next_session_open":
            return DailyExecutionProfile(
                profile_id="daily.next-session-open.v1",
                convention_id="open-price.v1",
                execution_timing="next_session_open",
                market_dataset_id=spec.market.market_dataset_id,
                execution_price_role=spec.market.execution_price_role,
                valuation_price_role=spec.market.valuation_price_role,
                feedback_entry_limit=spec.market.feedback_entry_limit,
                execution_lots=tuple(
                    (item.instrument_id, float(item.lot_size)) for item in spec.instruments
                ),
                constraint_policy=spec.constraint_policy,
                limitations=(
                    "single open price for the full cross-sectional batch",
                    "overnight gap is reflected but intraday path is not modelled",
                    "market impact and partial fill are not modelled",
                ),
            )
        return DailyExecutionProfile(
            market_dataset_id=spec.market.market_dataset_id,
            execution_price_role=spec.market.execution_price_role,
            valuation_price_role=spec.market.valuation_price_role,
            feedback_entry_limit=spec.market.feedback_entry_limit,
            execution_lots=tuple(
                (item.instrument_id, float(item.lot_size)) for item in spec.instruments
            ),
            constraint_policy=spec.constraint_policy,
        )

    def _with_catalog_session(
        self,
        *,
        operation: str,
        identity: str,
        callback: Callable[[], OperationOutcome[ResultT]],
    ) -> OperationOutcome[ResultT]:
        try:
            with self.artifacts.session(), self._store.frozen():
                return callback()
        except CatalogSessionConflictError as exc:
            return self._catalog_scope_failure(
                operation=operation,
                identity=identity,
                stage="catalog_session",
                error_code=exc.error_code,
                context={"catalog_path": str(exc.catalog_path), "message": exc.detail},
                retry=exc.retry_preconditions,
            )
        except CatalogSchemaError as exc:
            return self._catalog_scope_failure(
                operation=operation,
                identity=identity,
                stage="catalog_schema",
                error_code="CATALOG_SCHEMA_UNSUPPORTED",
                context={"message": str(exc)[:500]},
                retry=("migrate the catalog with an explicitly supported schema",),
            )

    @staticmethod
    def _catalog_scope_failure(
        *,
        operation: str,
        identity: str,
        stage: str,
        error_code: str,
        context: dict[str, object],
        retry: tuple[str, ...],
    ) -> OperationOutcome:
        stage_path = f"{operation}.{stage}"
        seed = hashlib.sha256(f"{identity}:{stage_path}:{error_code}".encode()).hexdigest()[:24]
        error = OperationError(
            operation=operation,
            stage_path=stage_path,
            error_code=error_code,
            context=context,
            commit_status=CommitStatus.NONE,
            retry_preconditions=retry,
            idempotency_identity=identity,
            error_id=f"error-{seed}",
        )
        return OperationOutcome(status=OutcomeStatus.FAILED, errors=(error,))

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
